from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient
from pydantic import SecretStr

from graphql_typst.app import create_app
from graphql_typst.metrics import NullMetrics, PrometheusMetrics, build_metrics
from graphql_typst.service import RenderService


@pytest.fixture
def make_client(bundle, gateway, renderer, settings):
    def build(**overrides) -> AsyncClient:
        used = settings.model_copy(update=overrides) if overrides else settings
        app = create_app(used)
        app.state.service = RenderService(bundle, gateway, renderer, used, build_metrics(used))
        return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")

    return build


async def test_healthz_is_always_ok(client):
    response = await client.get("/healthz")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


async def test_readyz_reports_ready(client):
    response = await client.get("/readyz")
    assert response.status_code == 200
    body = response.json()
    assert body == {
        "status": "ready",
        "version": body["version"],
        "templates": 2,
        "upstream": "connected",
    }


async def test_readyz_is_503_when_upstream_is_disconnected(client, service):
    await service.gateway.aclose()
    response = await client.get("/readyz")
    assert response.status_code == 503
    assert response.json()["upstream"] == "disconnected"


async def test_templates_listing(client):
    response = await client.get("/v1/templates")
    assert response.status_code == 200
    templates = {t["name"]: t for t in response.json()["templates"]}
    assert templates["hello"]["filename"] == "hello-{id}.pdf"
    assert templates["hello"]["args"] == [
        {"name": "id", "type": "ID!", "required": True, "is_list": False},
        {"name": "loud", "type": "Boolean", "required": False, "is_list": False},
    ]
    assert templates["plain"]["args"] == []


async def test_api_is_open_when_no_key_is_configured(client):
    assert (await client.get("/v1/templates")).status_code == 200


async def test_missing_key_is_401(make_client):
    async with make_client(api_key=SecretStr("s3cret")) as http:
        assert (await http.get("/v1/templates")).status_code == 401


async def test_wrong_key_is_401(make_client):
    async with make_client(api_key=SecretStr("s3cret")) as http:
        response = await http.get("/v1/templates", headers={"X-API-Key": "nope"})
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "unauthorized"


async def test_correct_key_is_accepted(make_client):
    async with make_client(api_key=SecretStr("s3cret")) as http:
        response = await http.get("/v1/templates", headers={"X-API-Key": "s3cret"})
    assert response.status_code == 200


async def test_custom_header_name_is_honoured(make_client):
    async with make_client(api_key=SecretStr("s3cret"), api_key_header="X-Token") as http:
        assert (await http.get("/v1/templates", headers={"X-Token": "s3cret"})).status_code == 200
        assert (await http.get("/v1/templates", headers={"X-API-Key": "s3cret"})).status_code == 401


async def test_probes_stay_open_when_a_key_is_required(make_client):
    # Kubernetes probes must not need a secret.
    async with make_client(api_key=SecretStr("s3cret")) as http:
        assert (await http.get("/healthz")).status_code == 200
        assert (await http.get("/readyz")).status_code == 200


async def test_openapi_is_served_by_default(client):
    response = await client.get("/openapi.json")
    assert response.status_code == 200
    assert "/v1/render/{name}" in response.json()["paths"]


async def test_openapi_can_be_disabled(make_client):
    async with make_client(docs_enabled=False) as http:
        assert (await http.get("/openapi.json")).status_code == 404


async def test_metrics_endpoint_exposes_prometheus_text(make_client):
    async with make_client(metrics_enabled=True) as http:
        await http.post("/v1/render/hello", json={"args": {"id": "10"}})
        response = await http.get("/metrics")
    assert response.status_code == 200
    assert "graphql_typst_render_duration_seconds" in response.text


def test_build_metrics_returns_null_when_disabled(settings):
    assert isinstance(build_metrics(settings), NullMetrics)


def test_build_metrics_returns_prometheus_when_enabled(settings):
    enabled = settings.model_copy(update={"metrics_enabled": True})
    assert isinstance(build_metrics(enabled), PrometheusMetrics)
