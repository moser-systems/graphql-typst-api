"""The gateway to the upstream GraphQL endpoint.

One client is built for the lifetime of the process. ``Client.execute_async()``
opens and tears down an aiohttp session per call, so a long-lived session is
established with ``connect_async(reconnecting=True)`` instead: that also brings
backoff reconnects and execute retries which correctly give up on a
``TransportQueryError`` — retrying transport faults, never a query the server
already rejected.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import TYPE_CHECKING, Any

import aiohttp
from gql import Client, GraphQLRequest
from gql.transport.aiohttp import AIOHTTPTransport
from gql.transport.exceptions import (
    TransportClosed,
    TransportConnectionFailed,
    TransportError,
    TransportProtocolError,
    TransportQueryError,
    TransportServerError,
)

from graphql_typst.errors import (
    UpstreamGraphQLError,
    UpstreamTimeoutError,
    UpstreamTransportError,
)
from graphql_typst.settings import Settings

if TYPE_CHECKING:
    from gql.client import AsyncClientSession

    from graphql_typst.bundle import LoadedTemplate

_log = logging.getLogger(__name__)


class GraphQLGateway:
    """Executes a template's query against the configured endpoint."""

    def __init__(self, settings: Settings, client: Client | None = None) -> None:
        self._settings = settings
        self._client = client
        self._session: AsyncClientSession | None = None

    @property
    def connected(self) -> bool:
        return self._session is not None

    def _build_client(self) -> Client:
        settings = self._settings
        transport = AIOHTTPTransport(
            url=settings.require_graphql_url(),
            headers=settings.upstream_headers(),
            ssl=settings.graphql_verify_ssl,
            # aiohttp accepts a float here; gql's annotation says int.
            timeout=settings.graphql_timeout_s,  # type: ignore[arg-type]
            client_session_args={
                "connector": aiohttp.TCPConnector(
                    limit=settings.graphql_pool_size,
                    ssl=settings.graphql_verify_ssl,
                )
            },
        )
        return Client(
            transport=transport,
            execute_timeout=settings.graphql_execute_timeout_s,
            # No introspection round-trip: startup must not depend on the upstream
            # being reachable (/readyz reports that instead), and introspection is
            # commonly disabled in production anyway.
            fetch_schema_from_transport=False,
        )

    async def start(self) -> None:
        if self._session is not None:
            return
        if self._client is None:
            self._client = self._build_client()
        self._session = await self._client.connect_async(  # type: ignore[no-untyped-call]
            reconnecting=self._settings.graphql_retry_execute
        )
        _log.info("graphql.connected", extra={"url": str(self._settings.graphql_url)})

    async def aclose(self) -> None:
        if self._session is None or self._client is None:
            return
        try:
            await self._client.close_async()  # type: ignore[no-untyped-call]
        except (TransportError, aiohttp.ClientError):  # pragma: no cover - best effort
            _log.warning("graphql.close_failed", exc_info=True)
        finally:
            self._session = None

    async def execute(
        self, template: LoadedTemplate, variables: Mapping[str, Any]
    ) -> dict[str, Any]:
        if self._session is None:
            raise UpstreamTransportError("GraphQL session is not connected")

        request = GraphQLRequest(
            template.document,
            variable_values=dict(variables) or None,
            operation_name=template.operation_name,
        )
        try:
            result = await self._session.execute(request)
        except TransportQueryError as exc:
            raise UpstreamGraphQLError(_errors_of(exc)) from exc
        except TransportServerError as exc:
            raise UpstreamTransportError(
                f"GraphQL endpoint returned HTTP {exc.code}", status=exc.code
            ) from exc
        except TimeoutError as exc:
            raise UpstreamTimeoutError("GraphQL endpoint timed out") from exc
        except (
            TransportProtocolError,
            TransportConnectionFailed,
            TransportClosed,
            aiohttp.ClientError,
        ) as exc:
            raise UpstreamTransportError(f"GraphQL transport error: {exc}") from exc
        if not isinstance(result, dict):  # pragma: no cover - gql always returns a dict
            raise UpstreamTransportError("GraphQL endpoint returned an unexpected payload")
        return result


def _errors_of(exc: TransportQueryError) -> list[dict[str, Any]]:
    """Normalise ``errors`` into plain dicts.

    Over HTTP gql hands back the decoded JSON objects, but a locally executed schema
    yields graphql-core ``GraphQLError`` instances, which expose the same shape via
    ``.formatted``.
    """
    normalised: list[dict[str, Any]] = []
    for err in exc.errors or ():
        if isinstance(err, Mapping):
            normalised.append(dict(err))
        elif hasattr(err, "formatted"):
            normalised.append(dict(err.formatted))
        else:  # pragma: no cover - defensive
            normalised.append({"message": str(err)})
    return normalised or [{"message": str(exc)}]
