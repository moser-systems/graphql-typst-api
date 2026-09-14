from __future__ import annotations

from pathlib import Path

import pytest

from graphql_typst.bundle import load_bundle, strip_jmespath_comments
from graphql_typst.errors import BundleConfigError, TemplateNotFoundError

BAD = Path(__file__).parent / "fixtures" / "bad_bundles"


def test_loads_the_fixture_bundle(bundle):
    assert bundle.names() == ["hello", "plain"]
    hello = bundle.get("hello")
    assert hello.description == "Hermetic fixture template"
    assert hello.filename_pattern == "hello-{id}.pdf"
    assert hello.operation_name == "HelloById"
    assert hello.defaults["title"] == "Fallback title"
    assert bundle.global_defaults["publisher"] == "Example AG"


def test_arg_specs_come_from_the_query(bundle):
    args = bundle.get("hello").args
    assert args["id"].gql_type == "ID!"
    assert args["id"].required is True
    assert args["loud"].required is False
    assert args["loud"].has_default is True


def test_template_without_transform_or_defaults(bundle):
    plain = bundle.get("plain")
    assert plain.transform is None
    assert plain.defaults == {}
    assert plain.filename_pattern == "{name}.pdf"


def test_unknown_template_raises(bundle):
    with pytest.raises(TemplateNotFoundError) as excinfo:
        bundle.get("nope")
    assert excinfo.value.details["available"] == ["hello", "plain"]


def test_strip_jmespath_comments_preserves_line_count():
    source = "# a comment\n{x: y}\n  # indented\n"
    assert strip_jmespath_comments(source) == "\n{x: y}\n"


@pytest.mark.parametrize(
    ("directory", "expected"),
    [
        ("escaping_path", "'..' is not allowed"),
        ("symlink_escape", "escapes the bundle directory"),
        ("missing_file", "file not found"),
        ("bad_jmespath", "not a valid JMESPath"),
        ("bad_graphql", "not valid GraphQL"),
        ("dup_names", "duplicate template name"),
        ("args_mismatch", "does not match the query's variables"),
        ("mutation", "only queries can back a template"),
        ("bad_filename", "unknown field"),
        ("two_operations", "set operation_name to pick one"),
        ("defaults_not_mapping", "expected a mapping"),
    ],
)
def test_invalid_bundles_are_rejected(directory: str, expected: str):
    with pytest.raises(BundleConfigError) as excinfo:
        load_bundle(BAD / directory)
    assert any(expected in problem for problem in excinfo.value.problems), excinfo.value.problems


def test_all_problems_are_reported_at_once():
    # An operator should fix a broken bundle in one pass, not one restart per typo.
    with pytest.raises(BundleConfigError) as excinfo:
        load_bundle(BAD / "many_problems")
    assert len(excinfo.value.problems) == 3


def test_missing_bundle_directory():
    with pytest.raises(BundleConfigError, match="bundle directory not found"):
        load_bundle(BAD / "does-not-exist")


def test_missing_config_file(tmp_path: Path):
    with pytest.raises(BundleConfigError, match=r"templates\.yaml not found"):
        load_bundle(tmp_path)


def test_invalid_config_schema(tmp_path: Path):
    (tmp_path / "templates.yaml").write_text("version: 1\ntemplates: []\n")
    with pytest.raises(BundleConfigError, match="templates"):
        load_bundle(tmp_path)
