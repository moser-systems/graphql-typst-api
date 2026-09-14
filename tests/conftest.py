"""Shared fixtures.

The GraphQL test double is a real ``gql.Client`` over ``LocalSchemaTransport``, not a
mock: variable binding, operation selection and error propagation are exactly where
the bugs live, and a mock would validate none of them.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable, Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from gql import Client
from gql.transport import AsyncTransport
from gql.transport.exceptions import TransportServerError
from gql.transport.local_schema import LocalSchemaTransport
from graphql import GraphQLResolveInfo, GraphQLSchema, build_schema
from httpx import ASGITransport, AsyncClient

from graphql_typst.app import create_app
from graphql_typst.bundle import Bundle, load_bundle
from graphql_typst.graphql_client import GraphQLGateway
from graphql_typst.metrics import NullMetrics
from graphql_typst.renderer import TypstRenderer
from graphql_typst.service import RenderService
from graphql_typst.settings import Settings

FIXTURES = Path(__file__).parent / "fixtures"
BUNDLE_DIR = FIXTURES / "bundle"

GREETINGS: dict[str, dict[str, Any]] = {
    "10": {
        "id": "10",
        "title": "Invoice 10",
        "body": "Hello from GraphQL",
        "nested": {"replaced": "from graphql"},
    },
    # Everything the transform selects is missing, so the defaults must survive.
    "sparse": {"id": "sparse", "title": None, "body": None, "nested": None},
}


def _resolve_greeting(_root: Any, _info: GraphQLResolveInfo, id: str, loud: bool = False) -> Any:  # noqa: A002
    if id == "boom":
        raise ValueError("greeting exploded")
    if id not in GREETINGS:
        return None
    record = dict(GREETINGS[id])
    if loud and record.get("body"):
        record["body"] = str(record["body"]).upper()
    return record


def _resolve_plain(_root: Any, _info: GraphQLResolveInfo) -> Any:
    return {"title": "Plain title", "greeting": "Plain greeting", "publisher": "Plain AG"}


@pytest.fixture(scope="session")
def schema() -> GraphQLSchema:
    built = build_schema((FIXTURES / "schema.graphql").read_text())
    query = built.query_type
    assert query is not None
    query.fields["greetingById"].resolve = _resolve_greeting
    query.fields["plain"].resolve = _resolve_plain
    return built


class FailingTransport(AsyncTransport):
    """Reproduces transport-level faults a local schema cannot produce."""

    def __init__(self, exc: Exception) -> None:
        self.exc = exc

    async def connect(self) -> None:
        return

    async def close(self) -> None:
        return

    async def execute(self, *_args: Any, **_kwargs: Any) -> Any:
        raise self.exc

    def subscribe(self, *_args: Any, **_kwargs: Any) -> Any:  # pragma: no cover
        raise NotImplementedError


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(
        bundle_dir=BUNDLE_DIR,
        graphql_url="http://graphql.invalid/graphql",
        # Hermetic: the fixture template selects no font, so typst falls back to its
        # embedded faces and the suite does not depend on host fonts.
        ignore_system_fonts=True,
        render_concurrency=4,
        typst_package_cache_path=tmp_path / "typst-packages",
        log_format="console",
    )


@pytest.fixture
def bundle() -> Bundle:
    return load_bundle(BUNDLE_DIR)


@pytest.fixture
def renderer(bundle: Bundle, settings: Settings) -> Iterator[TypstRenderer]:
    instance = TypstRenderer(bundle, settings)
    instance.prepare()
    yield instance
    instance.close()


@pytest.fixture
async def gateway(settings: Settings, schema: GraphQLSchema) -> AsyncIterator[GraphQLGateway]:
    client = Client(transport=LocalSchemaTransport(schema), fetch_schema_from_transport=False)
    instance = GraphQLGateway(settings, client=client)
    await instance.start()
    yield instance
    await instance.aclose()


@pytest.fixture
def service(
    bundle: Bundle, gateway: GraphQLGateway, renderer: TypstRenderer, settings: Settings
) -> RenderService:
    return RenderService(bundle, gateway, renderer, settings, NullMetrics())


@pytest.fixture
def app(settings: Settings, service: RenderService) -> FastAPI:
    # The lifespan is bypassed on purpose: it would build a gateway against a real
    # URL. Wiring state directly keeps the tests exercising the true request path
    # while pointing at the local schema.
    instance = create_app(settings)
    instance.state.service = service
    return instance


@pytest.fixture
async def client(app: FastAPI) -> AsyncIterator[AsyncClient]:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as http_client:
        yield http_client


@pytest.fixture
def failing_gateway_factory(settings: Settings) -> Callable[[Exception], Awaitable[GraphQLGateway]]:
    async def build(exc: Exception) -> GraphQLGateway:
        client = Client(transport=FailingTransport(exc), fetch_schema_from_transport=False)
        gateway = GraphQLGateway(settings, client=client)
        await gateway.start()
        return gateway

    return build


@pytest.fixture
def server_error() -> TransportServerError:
    return TransportServerError("upstream exploded", code=503)
