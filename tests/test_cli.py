from __future__ import annotations

from pathlib import Path

import pytest

from graphql_typst import __version__
from graphql_typst.cli import main
from graphql_typst.service import sanitise_filename

FIXTURES = Path(__file__).parent / "fixtures"


def test_version(capsys):
    assert main(["version"]) == 0
    assert capsys.readouterr().out.strip() == __version__


def test_check_accepts_a_valid_bundle(capsys):
    assert main(["check", "--bundle-dir", str(FIXTURES / "bundle")]) == 0
    out = capsys.readouterr().out
    assert "2 template(s)" in out
    assert "hello(id: ID!, loud: Boolean)" in out


def test_check_rejects_a_broken_bundle_and_lists_every_problem(capsys):
    assert main(["check", "--bundle-dir", str(FIXTURES / "bad_bundles" / "many_problems")]) == 1
    err = capsys.readouterr().err
    assert "3 problem(s)" in err
    assert err.count("file not found") == 3


def test_render_writes_a_pdf(tmp_path, monkeypatch, settings):
    monkeypatch.setenv("GRAPHQL_TYPST_BUNDLE_DIR", str(FIXTURES / "bundle"))
    monkeypatch.setenv("GRAPHQL_TYPST_GRAPHQL_URL", str(settings.graphql_url))
    out = tmp_path / "out.pdf"
    # No server is running, so this exercises the CLI's upstream error path.
    assert main(["render", "hello", "--arg", "id=10", "-o", str(out)]) == 1
    assert not out.exists()


def test_arg_pairs_must_be_key_value(monkeypatch, settings):
    monkeypatch.setenv("GRAPHQL_TYPST_BUNDLE_DIR", str(FIXTURES / "bundle"))
    monkeypatch.setenv("GRAPHQL_TYPST_GRAPHQL_URL", str(settings.graphql_url))
    with pytest.raises(SystemExit, match="key=value"):
        main(["render", "hello", "--arg", "id"])


def test_warm_cache_reports_progress(capsys, monkeypatch, settings, tmp_path):
    monkeypatch.setenv("GRAPHQL_TYPST_BUNDLE_DIR", str(FIXTURES / "bundle"))
    monkeypatch.setenv("GRAPHQL_TYPST_GRAPHQL_URL", str(settings.graphql_url))
    monkeypatch.setenv("GRAPHQL_TYPST_IGNORE_SYSTEM_FONTS", "true")
    monkeypatch.setenv("GRAPHQL_TYPST_TYPST_PACKAGE_CACHE_PATH", str(tmp_path / "pkgs"))
    assert main(["warm-cache"]) == 0
    assert "warmed 2 template(s)" in capsys.readouterr().out


@pytest.mark.parametrize(
    ("candidate", "expected"),
    [
        ("../../etc/passwd", "passwd.pdf"),
        ("invoice.pdf", "invoice.pdf"),
        ("Rechnung Öl.pdf", "Rechnung Öl.pdf"),
        ("", "fallback.pdf"),
        ("...", "fallback.pdf"),
        ("a" * 200, "a" * 96 + ".pdf"),
    ],
)
def test_sanitise_filename(candidate: str, expected: str):
    assert sanitise_filename(candidate, "fallback.pdf") == expected


def test_offline_commands_do_not_need_an_upstream_url(monkeypatch, capsys, tmp_path):
    # A container build runs `warm-cache` with no GraphQL endpoint configured.
    monkeypatch.delenv("GRAPHQL_TYPST_GRAPHQL_URL", raising=False)
    monkeypatch.setenv("GRAPHQL_TYPST_IGNORE_SYSTEM_FONTS", "true")
    monkeypatch.setenv("GRAPHQL_TYPST_TYPST_PACKAGE_CACHE_PATH", str(tmp_path / "pkgs"))
    assert main(["check", "--bundle-dir", str(FIXTURES / "bundle")]) == 0
    assert main(["warm-cache", "--bundle-dir", str(FIXTURES / "bundle")]) == 0
    assert "warmed 2 template(s)" in capsys.readouterr().out


def test_serve_reports_a_missing_upstream_url(monkeypatch):
    monkeypatch.delenv("GRAPHQL_TYPST_GRAPHQL_URL", raising=False)
    monkeypatch.setenv("GRAPHQL_TYPST_BUNDLE_DIR", str(FIXTURES / "bundle"))
    assert main(["serve"]) == 1
