from __future__ import annotations

import pytest
from gql.transport.exceptions import TransportServerError
from httpx import ASGITransport, AsyncClient

from graphql_typst.app import create_app
from graphql_typst.metrics import NullMetrics
from graphql_typst.service import RenderService

RENDER = "/v1/render/hello"


@pytest.fixture
def make_client(bundle, renderer, settings):
    async def build(gateway, **overrides) -> AsyncClient:
        used = settings.model_copy(update=overrides) if overrides else settings
        app = create_app(used)
        app.state.service = RenderService(bundle, gateway, renderer, used, NullMetrics())
        return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")

    return build


async def test_render_returns_a_pdf(client):
    response = await client.post(RENDER, json={"args": {"id": "10"}})
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/pdf"
    assert response.content.startswith(b"%PDF-")
    assert response.headers["cache-control"] == "no-store"
    assert 'filename="hello-10.pdf"' in response.headers["content-disposition"]
    assert float(response.headers["x-render-duration-ms"]) > 0


async def test_filename_pattern_uses_the_arguments(client):
    response = await client.post(RENDER, json={"args": {"id": "10"}})
    assert "hello-10.pdf" in response.headers["content-disposition"]


async def test_client_supplied_filename_is_sanitised(client):
    response = await client.post(
        RENDER, json={"args": {"id": "10"}, "filename": "../../etc/Rechnung Öl.pdf"}
    )
    disposition = response.headers["content-disposition"]
    assert "../" not in disposition
    # Both the ASCII fallback and the RFC 5987 form are present for the umlaut.
    assert 'filename="Rechnung _l.pdf"' in disposition
    assert "filename*=UTF-8''Rechnung%20%C3%96l.pdf" in disposition


async def test_inline_disposition(client):
    response = await client.post(f"{RENDER}?disposition=inline", json={"args": {"id": "10"}})
    assert response.headers["content-disposition"].startswith("inline;")


async def test_unknown_template_is_404(client):
    response = await client.post("/v1/render/nope", json={"args": {}})
    assert response.status_code == 404
    body = response.json()["error"]
    assert body["code"] == "template_not_found"
    assert body["details"]["available"] == ["hello", "plain"]


async def test_missing_argument_is_422(client):
    response = await client.post(RENDER, json={"args": {}})
    assert response.status_code == 422
    assert response.json()["error"]["details"]["missing"] == ["id"]


async def test_unknown_argument_is_422(client):
    response = await client.post(RENDER, json={"args": {"id": "10", "x": 1}})
    assert response.status_code == 422
    assert response.json()["error"]["details"]["unknown"] == ["x"]


async def test_unknown_body_field_is_422(client):
    response = await client.post(RENDER, json={"args": {"id": "10"}, "nope": 1})
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "invalid_request"


async def test_oversized_arguments_are_rejected(make_client, gateway):
    async with await make_client(gateway, max_args_bytes=32) as http:
        response = await http.post(RENDER, json={"args": {"id": "x" * 200}})
    assert response.status_code == 422
    assert "byte limit" in response.json()["error"]["message"]


async def test_upstream_graphql_error_is_502(client):
    response = await client.post(RENDER, json={"args": {"id": "boom"}})
    assert response.status_code == 502
    body = response.json()["error"]
    assert body["code"] == "upstream_graphql_error"
    assert "greeting exploded" in body["details"]["errors"][0]["message"]


async def test_upstream_transport_error_is_502(make_client, failing_gateway_factory):
    gateway = await failing_gateway_factory(TransportServerError("nope", code=502))
    async with await make_client(gateway) as http:
        response = await http.post(RENDER, json={"args": {"id": "10"}})
    assert response.status_code == 502
    assert response.json()["error"]["code"] == "upstream_transport_error"


async def test_upstream_timeout_is_504(make_client, failing_gateway_factory):
    gateway = await failing_gateway_factory(TimeoutError())
    async with await make_client(gateway) as http:
        response = await http.post(RENDER, json={"args": {"id": "10"}})
    assert response.status_code == 504
    assert response.json()["error"]["code"] == "upstream_timeout"


async def test_template_compile_failure_hides_details_by_default(client):
    # The 'plain' template is fed data that lacks the keys its typst source reads.
    response = await client.post("/v1/render/plain", json={"args": {}})
    assert response.status_code == 500
    body = response.json()["error"]
    assert body["code"] == "render_failed"
    assert body["details"] is None


async def test_template_compile_failure_exposes_details_when_debugging(make_client, gateway):
    async with await make_client(gateway, debug_errors=True) as http:
        response = await http.post("/v1/render/plain", json={"args": {}})
    assert response.status_code == 500
    assert "greeting" in response.json()["error"]["details"]["message"]


async def test_request_id_is_echoed_and_present_in_errors(client):
    response = await client.post(
        "/v1/render/nope", json={"args": {}}, headers={"X-Request-ID": "abc123"}
    )
    assert response.headers["X-Request-ID"] == "abc123"
    assert response.json()["error"]["request_id"] == "abc123"


async def test_request_id_is_generated_when_absent(client):
    response = await client.post(RENDER, json={"args": {"id": "10"}})
    assert len(response.headers["X-Request-ID"]) == 32


async def test_defaults_survive_a_sparse_upstream_response(client):
    # End-to-end proof of the null-pruning rule: nothing came back, yet the PDF is
    # rendered from the bundle's defaults instead of failing on a null.
    response = await client.post(RENDER, json={"args": {"id": "sparse"}})
    assert response.status_code == 200
    assert response.content.startswith(b"%PDF-")
