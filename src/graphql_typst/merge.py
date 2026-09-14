"""Deep-merge and null-pruning helpers for assembling document data."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any


def deep_merge(base: Mapping[str, Any], override: Mapping[str, Any]) -> dict[str, Any]:
    """Recursively merge ``override`` onto ``base`` without mutating either.

    Two dicts at the same key are merged recursively; anything else (including a
    list) is replaced wholesale. This matches the semantics the original script
    relied on: a list of invoice positions coming from the query must replace the
    default list, never be zipped into it.
    """
    merged = dict(base)
    for key, value in override.items():
        existing = merged.get(key)
        if isinstance(existing, Mapping) and isinstance(value, Mapping):
            merged[key] = deep_merge(existing, value)
        else:
            merged[key] = value
    return merged


def prune_none(value: Any) -> Any:
    """Recursively drop mapping keys whose value is ``None``.

    A JMESPath multi-select hash yields ``{"k": None}`` for every field the upstream
    response omitted. Merging that as-is would erase the default the bundle provides
    for exactly that case, so those keys are removed before the merge.

    Lists are left completely untouched, contents included. Pruning exists only so a
    default underneath can show through, and :func:`deep_merge` replaces a list
    wholesale — there is never a default under a list element. Recursing into one
    could only destroy real data, such as the ``vatRate: null`` that a GraphQL record
    legitimately carries and the template then reads.
    """
    if isinstance(value, Mapping):
        pruned: dict[str, Any] = {}
        for key, item in value.items():
            if item is None:
                continue
            cleaned = prune_none(item)
            # An object that pruned down to nothing carries no information either.
            if isinstance(cleaned, dict) and not cleaned and isinstance(item, Mapping) and item:
                continue
            pruned[key] = cleaned
        return pruned
    return value
