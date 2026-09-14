from __future__ import annotations

from graphql_typst_api.merge import deep_merge, prune_none


def test_dicts_merge_recursively():
    base = {"a": {"x": 1, "y": 2}, "b": 1}
    override = {"a": {"y": 20, "z": 30}}
    assert deep_merge(base, override) == {"a": {"x": 1, "y": 20, "z": 30}, "b": 1}


def test_lists_are_replaced_not_concatenated():
    # Invoice positions from the query must replace the default list wholesale.
    assert deep_merge({"p": [1, 2, 3]}, {"p": [9]}) == {"p": [9]}


def test_scalar_replaces_dict_and_vice_versa():
    assert deep_merge({"a": {"x": 1}}, {"a": 5}) == {"a": 5}
    assert deep_merge({"a": 5}, {"a": {"x": 1}}) == {"a": {"x": 1}}


def test_inputs_are_never_mutated():
    base = {"a": {"x": 1}}
    override = {"a": {"y": 2}}
    deep_merge(base, override)
    assert base == {"a": {"x": 1}}
    assert override == {"a": {"y": 2}}


def test_prune_none_drops_null_keys_recursively():
    assert prune_none({"a": None, "b": {"c": None, "d": 1}}) == {"b": {"d": 1}}


def test_prune_none_leaves_lists_untouched():
    # deep_merge replaces a list wholesale, so no default can show through one.
    # Pruning inside a list could only destroy data.
    assert prune_none({"xs": [1, None, 3]}) == {"xs": [1, None, 3]}


def test_prune_none_keeps_null_keys_inside_list_elements():
    # Regression: a GraphQL position legitimately carries "vatRate": null, and the
    # template reads that key.
    positions = [{"name": "a", "vatRate": None}]
    assert prune_none({"positions": positions}) == {"positions": positions}


def test_prune_none_keeps_empty_containers_that_were_already_empty():
    assert prune_none({"a": {}, "b": []}) == {"a": {}, "b": []}


def test_prune_none_drops_objects_that_pruned_to_nothing():
    assert prune_none({"qr": {"amount": None}}) == {}


def test_three_layer_precedence():
    global_defaults = {"author": "Example AG", "title": "global"}
    template_defaults = {"title": "template", "qr": {"amount": "0.00", "currency": "CHF"}}
    transform = {"title": "from graphql", "qr": {"amount": None, "iban": "CH93"}}

    merged = deep_merge(deep_merge(global_defaults, template_defaults), prune_none(transform))

    assert merged["author"] == "Example AG"
    assert merged["title"] == "from graphql"
    # The null from the transform did not erase the template default.
    assert merged["qr"] == {"amount": "0.00", "currency": "CHF", "iban": "CH93"}
