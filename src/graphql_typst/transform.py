"""Turn a GraphQL response into the data document a Typst template consumes."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from graphql_typst.bundle import Bundle, LoadedTemplate
from graphql_typst.errors import EmptyResultError
from graphql_typst.merge import deep_merge, prune_none


def apply_transform(template: LoadedTemplate, gql_data: Mapping[str, Any]) -> Any:
    """Run the template's JMESPath transform, or pass the response through."""
    if template.transform is None:
        return dict(gql_data)
    return template.transform.search(dict(gql_data))


def build_document_data(
    bundle: Bundle, template: LoadedTemplate, gql_data: Mapping[str, Any]
) -> dict[str, Any]:
    """Assemble the final document data.

    Precedence, lowest to highest::

        global defaults  <  template defaults  <  prune_none(transform output)

    The pruning matters: a JMESPath multi-select hash returns ``{"k": None}`` for any
    field the upstream response omitted, and merging that would wipe out the very
    default the bundle supplies for that case.
    """
    result = apply_transform(template, gql_data)
    if not isinstance(result, Mapping):
        raise EmptyResultError(template.name, sorted(gql_data))

    document = deep_merge(bundle.global_defaults, template.defaults)
    document = deep_merge(document, prune_none(result))
    if not document:
        raise EmptyResultError(template.name, sorted(gql_data))
    return document
