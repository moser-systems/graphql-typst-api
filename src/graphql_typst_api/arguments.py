"""Validation and coercion of request arguments into GraphQL variables.

Argument names, types and required-ness are derived from the query's own variable
definitions rather than from ``templates.yaml``: one source of truth, and it is the
one the upstream server actually enforces.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from graphql_typst_api.bundle import ArgSpec, LoadedTemplate
from graphql_typst_api.errors import InvalidArgumentsError

_TRUE = frozenset({"true", "1", "yes", "on"})
_FALSE = frozenset({"false", "0", "no", "off"})


def _coerce(spec: ArgSpec, value: Any) -> Any:
    """Coerce a string into the declared scalar type, if that is unambiguous.

    This exists so ``--arg id=10`` on the CLI and form-ish HTTP clients work against
    ``Int``/``Float``/``Boolean`` variables. Anything deeper is the upstream server's
    job: it has the schema, we only have the variable declarations.
    """
    if not isinstance(value, str) or spec.is_list:
        return value
    if spec.named_type == "Int":
        try:
            return int(value)
        except ValueError as exc:
            raise InvalidArgumentsError(
                f"argument {spec.name!r} must be an integer, got {value!r}"
            ) from exc
    if spec.named_type == "Float":
        try:
            return float(value)
        except ValueError as exc:
            raise InvalidArgumentsError(
                f"argument {spec.name!r} must be a number, got {value!r}"
            ) from exc
    if spec.named_type == "Boolean":
        lowered = value.strip().lower()
        if lowered in _TRUE:
            return True
        if lowered in _FALSE:
            return False
        raise InvalidArgumentsError(f"argument {spec.name!r} must be a boolean, got {value!r}")
    return value


def validate_args(template: LoadedTemplate, raw: Mapping[str, Any]) -> dict[str, Any]:
    """Return the GraphQL ``variable_values`` for ``raw``.

    Raises :class:`InvalidArgumentsError` (HTTP 422) for unknown or missing arguments.
    """
    accepted = sorted(template.args)

    unknown = sorted(set(raw) - set(template.args))
    if unknown:
        raise InvalidArgumentsError(
            f"unknown argument(s): {', '.join(unknown)}",
            unknown=unknown,
            accepted=accepted,
        )

    missing = sorted(
        name for name, spec in template.args.items() if spec.required and name not in raw
    )
    if missing:
        raise InvalidArgumentsError(
            f"missing required argument(s): {', '.join(missing)}",
            missing=missing,
            accepted=accepted,
        )

    variables: dict[str, Any] = {}
    for name, spec in template.args.items():
        if name not in raw:
            # Omit rather than send an explicit null, so the query's own default
            # value applies instead of being overridden with null.
            continue
        variables[name] = _coerce(spec, raw[name])
    return variables
