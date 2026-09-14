from __future__ import annotations

import pytest
from gql.transport.exceptions import TransportProtocolError, TransportServerError

from graphql_typst_api.errors import (
    UpstreamGraphQLError,
    UpstreamTimeoutError,
    UpstreamTransportError,
)
from graphql_typst_api.graphql_client import GraphQLGateway


async def test_executes_with_variables(gateway, bundle):
    result = await gateway.execute(bundle.get("hello"), {"id": "10"})
    assert result["greetingById"]["title"] == "Invoice 10"


async def test_variables_actually_reach_the_resolver(gateway, bundle):
    result = await gateway.execute(bundle.get("hello"), {"id": "10", "loud": True})
    assert result["greetingById"]["body"] == "HELLO FROM GRAPHQL"


async def test_resolver_failure_becomes_upstream_graphql_error(gateway, bundle):
    with pytest.raises(UpstreamGraphQLError) as excinfo:
        await gateway.execute(bundle.get("hello"), {"id": "boom"})
    errors = excinfo.value.details["errors"]
    assert "greeting exploded" in errors[0]["message"]
    # extensions can carry server stack traces and must never be forwarded.
    assert set(errors[0]) <= {"message", "path"}


async def test_missing_required_variable_is_an_upstream_error(gateway, bundle):
    # gql/graphql-core rejects this before it reaches a resolver; the service must
    # surface it rather than crashing.
    with pytest.raises(UpstreamGraphQLError):
        await gateway.execute(bundle.get("hello"), {})


async def test_server_error_is_mapped(failing_gateway_factory, bundle, server_error):
    gateway = await failing_gateway_factory(server_error)
    with pytest.raises(UpstreamTransportError) as excinfo:
        await gateway.execute(bundle.get("hello"), {"id": "10"})
    assert excinfo.value.status == 503


async def test_protocol_error_is_mapped(failing_gateway_factory, bundle):
    gateway = await failing_gateway_factory(TransportProtocolError("garbled"))
    with pytest.raises(UpstreamTransportError):
        await gateway.execute(bundle.get("hello"), {"id": "10"})


async def test_timeout_is_mapped(failing_gateway_factory, bundle):
    gateway = await failing_gateway_factory(TimeoutError())
    with pytest.raises(UpstreamTimeoutError):
        await gateway.execute(bundle.get("hello"), {"id": "10"})


async def test_execute_without_connect_is_an_error(settings, bundle):
    gateway = GraphQLGateway(settings)
    with pytest.raises(UpstreamTransportError, match="not connected"):
        await gateway.execute(bundle.get("hello"), {"id": "10"})


async def test_start_is_idempotent_and_close_is_safe(gateway):
    await gateway.start()
    assert gateway.connected
    await gateway.aclose()
    assert not gateway.connected
    await gateway.aclose()


def test_transport_server_error_fixture_shape(server_error: TransportServerError):
    assert server_error.code == 503
