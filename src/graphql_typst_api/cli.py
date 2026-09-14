"""Command line interface.

``argparse`` rather than click/typer: five subcommands with a handful of flags do
not justify a runtime dependency in a container image.

``check`` and ``warm-cache`` are not conveniences — ``check`` is the CI and
pre-deploy bundle validator, and ``warm-cache`` is the Docker build step that makes
the runtime image work without network access.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from graphql_typst_api import __version__
from graphql_typst_api.bundle import load_bundle
from graphql_typst_api.errors import BundleConfigError, ConfigurationError, GraphQLTypstError
from graphql_typst_api.graphql_client import GraphQLGateway
from graphql_typst_api.log import configure_logging
from graphql_typst_api.metrics import build_metrics
from graphql_typst_api.renderer import TypstRenderer
from graphql_typst_api.service import RenderService
from graphql_typst_api.settings import Settings


def _settings(args: argparse.Namespace) -> Settings:
    overrides: dict[str, Any] = {}
    if getattr(args, "bundle_dir", None):
        overrides["bundle_dir"] = args.bundle_dir
    return Settings(**overrides)


def _parse_arg_pairs(pairs: list[str] | None) -> dict[str, Any]:
    args: dict[str, Any] = {}
    for pair in pairs or []:
        key, sep, value = pair.partition("=")
        if not sep:
            raise SystemExit(f"--arg expects key=value, got {pair!r}")
        args[key] = value
    return args


def cmd_version(_args: argparse.Namespace) -> int:
    print(__version__)
    return 0


def cmd_check(args: argparse.Namespace) -> int:
    root = Path(args.bundle_dir) if args.bundle_dir else _settings(args).bundle_dir
    try:
        bundle = load_bundle(Path(root))
    except BundleConfigError as exc:
        print(exc.message, file=sys.stderr)
        return 1
    print(f"ok: {len(bundle.templates)} template(s) in {bundle.root}")
    for name in bundle.names():
        template = bundle.templates[name]
        accepted = ", ".join(
            f"{a.name}: {a.gql_type}" for a in (template.args[k] for k in sorted(template.args))
        )
        print(f"  - {name}({accepted})")
    return 0


def cmd_warm_cache(args: argparse.Namespace) -> int:
    settings = _settings(args)
    bundle = load_bundle(Path(args.bundle_dir) if args.bundle_dir else settings.bundle_dir)
    renderer = TypstRenderer(bundle, settings)
    renderer.prepare()
    warmed = renderer.warm()
    print(f"warmed {len(bundle.templates)} template(s); {len(warmed)} compiled cleanly")
    return 0


def cmd_serve(args: argparse.Namespace) -> int:
    # Imported lazily: `check` and `version` must not pay for uvicorn's import.
    import uvicorn  # noqa: PLC0415

    settings = _settings(args)
    settings.require_graphql_url()
    uvicorn.run(
        "graphql_typst_api.app:create_app",
        factory=True,
        host=args.host or settings.host,
        port=args.port or settings.port,
        workers=None if args.reload else (args.workers or settings.workers),
        reload=args.reload,
        log_config=None,
        access_log=False,
    )
    return 0


async def _render(args: argparse.Namespace) -> bytes:
    settings = _settings(args)
    configure_logging(settings)
    bundle = load_bundle(Path(args.bundle_dir) if args.bundle_dir else settings.bundle_dir)
    renderer = TypstRenderer(bundle, settings)
    renderer.prepare()
    gateway = GraphQLGateway(settings)
    await gateway.start()
    service = RenderService(bundle, gateway, renderer, settings, build_metrics(settings))
    try:
        # Same code path as the HTTP route, so the CLI never diverges from production.
        result = await service.render(args.name, _collect_args(args))
    finally:
        await gateway.aclose()
    return result.pdf


def _collect_args(args: argparse.Namespace) -> dict[str, Any]:
    collected = _parse_arg_pairs(args.arg)
    if args.args_json:
        parsed = json.loads(args.args_json)
        if not isinstance(parsed, dict):
            raise SystemExit("--args-json must be a JSON object")
        collected.update(parsed)
    return collected


def cmd_render(args: argparse.Namespace) -> int:
    try:
        pdf = asyncio.run(_render(args))
    except GraphQLTypstError as exc:
        print(exc.message, file=sys.stderr)
        if exc.details:
            print(json.dumps(exc.details, indent=2, default=str), file=sys.stderr)
        return 1
    if args.output == "-":
        sys.stdout.buffer.write(pdf)
    else:
        Path(args.output).write_bytes(pdf)
        print(f"wrote {args.output} ({len(pdf)} bytes)")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="graphql-typst-api", description=__doc__.splitlines()[0])
    parser.add_argument("--version", action="version", version=__version__)
    sub = parser.add_subparsers(dest="command", required=True)

    def with_bundle(p: argparse.ArgumentParser) -> argparse.ArgumentParser:
        p.add_argument(
            "--bundle-dir",
            help="Template bundle directory (default: GRAPHQL_TYPST_API_BUNDLE_DIR)",
        )
        return p

    serve = with_bundle(sub.add_parser("serve", help="Run the HTTP API"))
    serve.add_argument("--host")
    serve.add_argument("--port", type=int)
    serve.add_argument("--workers", type=int)
    serve.add_argument("--reload", action="store_true")
    serve.set_defaults(func=cmd_serve)

    render = with_bundle(sub.add_parser("render", help="Render one template to a PDF"))
    render.add_argument("name")
    render.add_argument("--arg", action="append", metavar="KEY=VALUE")
    render.add_argument("--args-json", metavar="JSON")
    render.add_argument("-o", "--output", default="-", help="Output file, or - for stdout")
    render.set_defaults(func=cmd_render)

    check = with_bundle(sub.add_parser("check", help="Validate a template bundle"))
    check.set_defaults(func=cmd_check)

    warm = with_bundle(
        sub.add_parser("warm-cache", help="Populate the Typst @preview package cache")
    )
    warm.set_defaults(func=cmd_warm_cache)

    version = sub.add_parser("version", help="Print the version")
    version.set_defaults(func=cmd_version)

    return parser


def _report_settings_error(exc: ValidationError) -> None:
    """Turn a pydantic failure into the environment variables the operator must set."""
    prefix = str(Settings.model_config.get("env_prefix", ""))
    print("invalid configuration:", file=sys.stderr)
    for err in exc.errors():
        field = ".".join(str(part) for part in err["loc"])
        print(f"  {prefix}{field.upper()}: {err['msg']}", file=sys.stderr)


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        result: int = args.func(args)
    except (BundleConfigError, ConfigurationError) as exc:
        print(exc.message, file=sys.stderr)
        return 1
    except ValidationError as exc:
        # A missing required setting is an operator mistake, not a crash.
        _report_settings_error(exc)
        return 1
    return result


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
