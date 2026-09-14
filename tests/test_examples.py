"""Tests for the shipped example bundle.

The example templates import ``@preview`` packages, which Typst downloads on first
use. That makes these tests network-dependent, so they are opt-in: CI runs them in a
dedicated job, and the hermetic suite in ``test_renderer.py`` covers the renderer
itself offline.
"""

from __future__ import annotations

import io
import json
import os
from pathlib import Path

import pytest
from pypdf import PdfReader

from graphql_typst.bundle import load_bundle
from graphql_typst.renderer import TypstRenderer
from graphql_typst.settings import Settings
from graphql_typst.transform import build_document_data

EXAMPLES = Path(__file__).resolve().parent.parent / "examples" / "bundle"
RESPONSE = Path(__file__).parent / "fixtures" / "invoice_response.json"

needs_network = pytest.mark.skipif(
    not os.environ.get("GRAPHQL_TYPST_TEST_NETWORK"),
    reason="set GRAPHQL_TYPST_TEST_NETWORK=1 to download @preview packages",
)


def test_example_bundle_is_valid():
    bundle = load_bundle(EXAMPLES)
    assert bundle.names() == ["invoice", "letter"]
    assert set(bundle.get("invoice").args) == {"id"}
    assert bundle.global_defaults["sender"]["name"] == "Example AG"


def test_transform_produces_every_key_the_template_reads():
    bundle = load_bundle(EXAMPLES)
    document = build_document_data(bundle, bundle.get("invoice"), json.loads(RESPONSE.read_text()))
    assert document["invoice_number"] == "2026-000123"
    assert document["recipient"]["city"] == "Winterthur"
    assert document["qr"]["amount"] == 1081.0
    # The creditor half never comes from the query.
    assert document["qr"]["creditor_name"] == "Example AG"
    # A GraphQL position's own null survives: the template reads that key.
    assert document["positions"][1]["vatRate"] is None


@pytest.mark.slow
@needs_network
def test_example_invoice_renders():
    bundle = load_bundle(EXAMPLES)
    settings = Settings(
        bundle_dir=EXAMPLES,
        graphql_url="http://graphql.invalid/graphql",
    )
    renderer = TypstRenderer(bundle, settings)
    renderer.prepare()
    document = build_document_data(bundle, bundle.get("invoice"), json.loads(RESPONSE.read_text()))
    pdf = renderer.render_sync(bundle.get("invoice"), document)

    reader = PdfReader(io.BytesIO(pdf))
    assert len(reader.pages) == 2  # letter plus the Swiss QR bill
    text = reader.pages[0].extract_text()
    assert "Rechnung Q1 2026" in text
    assert "Erika Mustermann" in text
    assert "1081.00" in text
