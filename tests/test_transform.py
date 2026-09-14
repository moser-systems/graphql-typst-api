from __future__ import annotations

import pytest

from graphql_typst.errors import EmptyResultError
from graphql_typst.transform import apply_transform, build_document_data

FULL = {
    "greetingById": {
        "id": "10",
        "title": "Invoice 10",
        "body": "Hello from GraphQL",
        "nested": {"replaced": "from graphql"},
    }
}

SPARSE = {"greetingById": {"id": "sparse", "title": None, "body": None, "nested": None}}


def test_transform_reshapes_the_response(bundle):
    result = apply_transform(bundle.get("hello"), FULL)
    assert result == {
        "title": "Invoice 10",
        "greeting": "Hello from GraphQL",
        "nested": {"replaced": "from graphql"},
    }


def test_document_data_layers_defaults_under_the_transform(bundle):
    document = build_document_data(bundle, bundle.get("hello"), FULL)
    assert document["title"] == "Invoice 10"
    assert document["greeting"] == "Hello from GraphQL"
    assert document["publisher"] == "Example AG"  # global default survives
    assert document["nested"] == {"kept": "from defaults", "replaced": "from graphql"}


def test_missing_upstream_fields_fall_back_to_defaults(bundle):
    # Regression: jmespath yields {"title": None} for an omitted field, and merging
    # that as-is would erase the default instead of falling back to it.
    document = build_document_data(bundle, bundle.get("hello"), SPARSE)
    assert document["title"] == "Fallback title"
    assert document["greeting"] == "Fallback greeting"
    assert document["nested"] == {"kept": "from defaults", "replaced": "from defaults"}


def test_missing_transform_passes_the_response_through(bundle):
    data = {"plain": {"title": "t"}}
    assert build_document_data(bundle, bundle.get("plain"), data)["plain"] == {"title": "t"}


@pytest.mark.parametrize("result", [None, [1, 2, 3], "text"])
def test_non_mapping_transform_result_is_an_error(bundle, monkeypatch, result):
    template = bundle.get("hello")
    monkeypatch.setattr(template.transform, "search", lambda _data: result)
    with pytest.raises(EmptyResultError) as excinfo:
        build_document_data(bundle, template, FULL)
    assert excinfo.value.details["received_keys"] == ["greetingById"]
