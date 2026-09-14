from __future__ import annotations

import pytest

from graphql_typst.arguments import validate_args
from graphql_typst.bundle import Bundle
from graphql_typst.errors import InvalidArgumentsError


@pytest.fixture
def hello(bundle: Bundle):
    return bundle.get("hello")


def test_required_arg_is_passed_through(hello):
    assert validate_args(hello, {"id": "10"}) == {"id": "10"}


def test_unknown_arg_is_rejected(hello):
    with pytest.raises(InvalidArgumentsError) as excinfo:
        validate_args(hello, {"id": "10", "nope": 1})
    assert excinfo.value.details["unknown"] == ["nope"]
    assert excinfo.value.details["accepted"] == ["id", "loud"]


def test_missing_required_arg_is_rejected(hello):
    with pytest.raises(InvalidArgumentsError) as excinfo:
        validate_args(hello, {})
    assert excinfo.value.details["missing"] == ["id"]


def test_optional_arg_is_omitted_not_nulled(hello):
    # Sending an explicit null would override the query's own default value.
    assert "loud" not in validate_args(hello, {"id": "10"})


def test_boolean_strings_are_coerced(hello):
    assert validate_args(hello, {"id": "1", "loud": "true"})["loud"] is True
    assert validate_args(hello, {"id": "1", "loud": "no"})["loud"] is False


def test_boolean_garbage_is_rejected(hello):
    with pytest.raises(InvalidArgumentsError):
        validate_args(hello, {"id": "1", "loud": "maybe"})


def test_id_strings_are_not_coerced(hello):
    # GraphQL ID serialises either form; guessing would corrupt zero-padded ids.
    assert validate_args(hello, {"id": "007"})["id"] == "007"


def test_native_json_values_pass_through(hello):
    assert validate_args(hello, {"id": 10, "loud": True}) == {"id": 10, "loud": True}
