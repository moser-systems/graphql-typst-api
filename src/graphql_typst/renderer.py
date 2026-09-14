"""Typst compilation.

Two measured facts shape this module:

* A ``typst.Compiler`` cannot be shared between threads — concurrent use raises
  ``RuntimeError('Already borrowed')`` from PyO3's ``RefCell``. Each compile
  therefore takes an exclusive lease from a small per-template pool.
* The GIL *is* released during compilation, so running compiles in a thread pool
  genuinely parallelises (~5x on four workers). A single global lock would have
  capped throughput at roughly four renders a second.

A compiler built from bytes is single-use (the second compile cannot find its own
source), so compilers are always constructed from an absolute path plus the bundle
root.
"""

from __future__ import annotations

import json
import logging
import queue
import threading
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from typing import Any

import anyio
import anyio.to_thread
import typst

from graphql_typst.bundle import Bundle, LoadedTemplate
from graphql_typst.errors import RenderBusyError, RenderFailedError
from graphql_typst.settings import Settings

_log = logging.getLogger(__name__)

# Typst resolves `#import "@preview/..."` while evaluating a module, before the body
# ever touches the supplied data. So during cache warming a *data* error proves the
# packages resolved, while these messages mean the package could not be fetched.
_PACKAGE_FAILURE_MARKERS = (
    "failed to download",
    "package not found",
    "unknown package",
    "failed to load package",
    "no such package",
)


class CompilerPool:
    """A bounded pool of compilers for one template, handing out exclusive leases."""

    def __init__(self, factory: Callable[[], typst.Compiler], size: int) -> None:
        self._factory = factory
        self._size = size
        # LIFO: reusing the most recently used compiler keeps its incremental
        # (comemo) cache warm, which turns a repeat compile from ~215ms into ~12ms.
        self._idle: queue.LifoQueue[typst.Compiler] = queue.LifoQueue()
        self._lock = threading.Lock()
        self._created = 0

    @contextmanager
    def lease(self) -> Iterator[typst.Compiler]:
        compiler = self._acquire()
        try:
            yield compiler
        finally:
            # Safe even after a TypstError: a compiler stays usable after a failure.
            self._idle.put(compiler)

    def _acquire(self) -> typst.Compiler:
        try:
            return self._idle.get_nowait()
        except queue.Empty:
            pass
        with self._lock:
            may_create = self._created < self._size
            if may_create:
                self._created += 1
        if not may_create:
            return self._idle.get()
        try:
            return self._factory()
        except BaseException:
            with self._lock:
                self._created -= 1
            raise


class TypstRenderer:
    """Compiles a template with request data into PDF bytes."""

    def __init__(self, bundle: Bundle, settings: Settings) -> None:
        self._bundle = bundle
        self._settings = settings
        self._fonts: typst.Fonts | None = None
        self._pools: dict[str, CompilerPool] = {}
        # The gate is a plain semaphore rather than a CapacityLimiter so it can be
        # acquired with a timeout by the same task that later runs the thread.
        self._gate = anyio.Semaphore(settings.render_concurrency)
        # A separate limiter for the thread pool itself, so typst can never occupy
        # anyio's shared 40-slot worker pool and starve unrelated to_thread work.
        self._thread_limiter = anyio.CapacityLimiter(settings.render_concurrency)
        self._prepared = False

    @property
    def prepared(self) -> bool:
        return self._prepared

    def prepare(self) -> None:
        """Scan fonts once and create the (empty) pools."""
        font_paths = [str(p) for p in self._settings.font_paths]
        bundle_fonts = self._bundle.root / "fonts"
        if bundle_fonts.is_dir():
            font_paths.append(str(bundle_fonts))
        # Building this once and handing it to every compiler saves ~35ms per render
        # versus letting each compiler rescan the system font directories.
        self._fonts = typst.Fonts(
            include_system_fonts=not self._settings.ignore_system_fonts,
            font_paths=font_paths,
        )
        self._pools = {
            name: CompilerPool(self._make_factory(template), self._settings.pool_size)
            for name, template in self._bundle.templates.items()
        }
        self._prepared = True

    def close(self) -> None:
        self._pools.clear()
        self._fonts = None
        self._prepared = False

    def _make_factory(self, template: LoadedTemplate) -> Callable[[], typst.Compiler]:
        settings = self._settings

        def factory() -> typst.Compiler:
            return typst.Compiler(
                input=str(template.template_path),
                root=str(self._bundle.root),
                font_paths=self._fonts if self._fonts is not None else [],
                package_path=(
                    str(settings.typst_package_path) if settings.typst_package_path else None
                ),
                package_cache_path=(
                    str(settings.typst_package_cache_path)
                    if settings.typst_package_cache_path
                    else None
                ),
            )

        return factory

    def _pool(self, template: LoadedTemplate) -> CompilerPool:
        pool = self._pools.get(template.name)
        if pool is None:  # a template loaded after prepare(), e.g. from the CLI
            pool = CompilerPool(self._make_factory(template), self._settings.pool_size)
            self._pools[template.name] = pool
        return pool

    def render_sync(self, template: LoadedTemplate, data: Mapping[str, Any]) -> bytes:
        """Compile ``template`` with ``data``. Blocking; used directly by the CLI."""
        payload = {"data": json.dumps(data, ensure_ascii=False, default=str)}
        return self._compile(template, payload)

    def _compile(self, template: LoadedTemplate, payload: dict[str, str]) -> bytes:
        settings = self._settings
        try:
            with self._pool(template).lease() as compiler:
                result, warnings = compiler.compile_with_warnings(
                    sys_inputs=payload,
                    format="pdf",
                    output=None,
                    pdf_standards=list(settings.pdf_standards),
                    timestamp=settings.pdf_timestamp,
                )
        except typst.TypstError as exc:
            raise RenderFailedError(
                template.name,
                getattr(exc, "message", str(exc)),
                list(getattr(exc, "hints", []) or []),
                list(getattr(exc, "trace", []) or []),
            ) from exc
        for warning in warnings:
            _log.warning(
                "typst.warning",
                extra={
                    "template": template.name,
                    "warning": getattr(warning, "message", str(warning)),
                },
            )
        if not isinstance(result, bytes):  # pragma: no cover - pdf output is always bytes
            raise RenderFailedError(
                template.name, f"expected PDF bytes, got {type(result).__name__}"
            )
        return result

    async def render(self, template: LoadedTemplate, data: Mapping[str, Any]) -> bytes:
        """Compile off the event loop, bounded by the render concurrency gate."""
        payload = {"data": json.dumps(data, ensure_ascii=False, default=str)}
        timeout = self._settings.render_queue_timeout_s
        try:
            with anyio.fail_after(timeout):
                await self._gate.acquire()
        except TimeoutError as exc:
            # Bounded queueing: a caller learns immediately that the service is
            # saturated instead of every client timing out on an unbounded queue.
            raise RenderBusyError(timeout) from exc
        try:
            # abandon_on_cancel=False: a thread cannot be killed, so abandoning one
            # would leak a limiter slot permanently. A client disconnecting mid-render
            # therefore costs one wasted compile, not a lost slot.
            return await anyio.to_thread.run_sync(
                self._compile,
                template,
                payload,
                limiter=self._thread_limiter,
                abandon_on_cancel=False,
            )
        finally:
            self._gate.release()

    def warm(self) -> list[str]:
        """Compile every template with empty data to populate the ``@preview`` cache.

        Returns the names that compiled cleanly. A data error is expected and ignored
        (there is no data), but a package-resolution failure is re-raised so a
        container build fails loudly rather than shipping an image that needs network
        at runtime.
        """
        if not self._prepared:
            self.prepare()
        warmed: list[str] = []
        for name, template in self._bundle.templates.items():
            try:
                self._compile(template, {"data": "{}"})
            except RenderFailedError as exc:
                lowered = exc.typst_message.lower()
                if any(marker in lowered for marker in _PACKAGE_FAILURE_MARKERS):
                    raise
                _log.info(
                    "warm.data_error_ignored",
                    extra={"template": name, "detail": exc.typst_message},
                )
            else:
                warmed.append(name)
        return warmed
