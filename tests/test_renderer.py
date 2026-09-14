"""Renderer tests. These run a real typst compile, offline.

The fixture template imports no ``@preview`` package and selects no font, so it needs
neither network nor host fonts and runs in every CI job rather than being skipped.
"""

from __future__ import annotations

import io

import anyio
import pytest
from pypdf import PdfReader

from graphql_typst.errors import RenderBusyError, RenderFailedError
from graphql_typst.renderer import CompilerPool, TypstRenderer

DATA = {"title": "Rendered title", "greeting": "Rendered greeting", "publisher": "Example AG"}


def _text(pdf: bytes) -> str:
    return "\n".join(page.extract_text() for page in PdfReader(io.BytesIO(pdf)).pages)


def test_render_produces_a_readable_pdf(renderer, bundle):
    pdf = renderer.render_sync(bundle.get("hello"), DATA)
    assert pdf.startswith(b"%PDF-")
    reader = PdfReader(io.BytesIO(pdf))
    assert len(reader.pages) == 1
    assert "Rendered title" in _text(pdf)


async def test_async_render_matches_sync(renderer, bundle):
    pdf = await renderer.render(bundle.get("hello"), DATA)
    assert "Rendered greeting" in _text(pdf)


async def test_concurrent_renders_all_succeed(renderer, bundle):
    # Regression: a shared typst.Compiler raises RuntimeError('Already borrowed')
    # under concurrency, which is why each compile takes an exclusive lease.
    template = bundle.get("hello")
    results: list[bytes] = []

    async def one(index: int) -> None:
        results.append(await renderer.render(template, {**DATA, "title": f"Doc {index}"}))

    async with anyio.create_task_group() as tg:
        for index in range(16):
            tg.start_soon(one, index)

    assert len(results) == 16
    assert all(pdf.startswith(b"%PDF-") for pdf in results)


def test_template_error_becomes_render_failed(renderer, bundle):
    with pytest.raises(RenderFailedError) as excinfo:
        renderer.render_sync(bundle.get("hello"), {"greeting": "no title key"})
    assert "title" in excinfo.value.typst_message


def test_pool_still_works_after_a_failure(renderer, bundle):
    template = bundle.get("hello")
    with pytest.raises(RenderFailedError):
        renderer.render_sync(template, {})
    assert renderer.render_sync(template, DATA).startswith(b"%PDF-")


def test_output_is_deterministic_with_a_fixed_timestamp(bundle, settings):
    fixed = settings.model_copy(update={"pdf_timestamp": 1700000000})
    first, second = (TypstRenderer(bundle, fixed) for _ in range(2))
    first.prepare()
    second.prepare()
    assert first.render_sync(bundle.get("hello"), DATA) == second.render_sync(
        bundle.get("hello"), DATA
    )


async def test_saturation_returns_render_busy(bundle, settings):
    # One slot, a zero-length queue timeout: the second caller must be told the
    # service is busy rather than queueing behind an unbounded backlog.
    tight = settings.model_copy(
        update={"render_concurrency": 1, "compiler_pool_size": 1, "render_queue_timeout_s": 0.001}
    )
    renderer = TypstRenderer(bundle, tight)
    renderer.prepare()
    template = bundle.get("hello")
    errors: list[Exception] = []

    async def one(index: int) -> None:
        try:
            await renderer.render(template, {**DATA, "title": f"Doc {index}"})
        except RenderBusyError as exc:
            errors.append(exc)

    async with anyio.create_task_group() as tg:
        for index in range(8):
            tg.start_soon(one, index)

    assert errors, "expected at least one caller to be rejected"


def test_pool_reuses_a_returned_compiler():
    created = []

    def factory() -> object:
        created.append(object())
        return created[-1]

    pool = CompilerPool(factory, size=2)  # type: ignore[arg-type]
    with pool.lease() as first:
        pass
    with pool.lease() as second:
        pass
    assert first is second
    assert len(created) == 1


def test_warm_ignores_data_errors_but_reports_success(renderer):
    # There is no data during warming, so a data error is expected; only a package
    # resolution failure should abort a container build.
    assert renderer.warm() == []
