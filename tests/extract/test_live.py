"""A real model on data/probe (simulated). Needs GOOGLE_API_KEY; run with `pytest -m live`. Not a quality
measure (that is the eval): it checks the call works end to end and the traps come out as needs_review."""
from __future__ import annotations

from pathlib import Path

import pytest

from src.extract.documents import load
from src.extract.pipeline import extract
from src.llm.client import Gemini, api_keys, load_env

PROBE = Path(__file__).resolve().parents[2] / "data" / "probe"
load_env(Path(__file__).resolve().parents[2] / ".env")
pytestmark = [pytest.mark.live, pytest.mark.skipif(not api_keys(), reason="needs GOOGLE_API_KEY")]


def test_the_probe_documents_read_into_a_lot_with_their_traps_open():
    files = ("packing_list.xlsx", "product_spec.pdf", "handling_label_sku_c.png")
    result = extract(Gemini(), "probe", [load(f, (PROBE / f).read_bytes()) for f in files])
    assert result.failed == {}
    lines = {line.id: line for line in result.lot.lines}
    assert {line.sku for line in lines.values()} == {"SKU-A", "SKU-B", "SKU-C", "SKU-D"}
    assert sum(1 for line in lines.values() if line.sku == "SKU-A") == 2  # two rows, never merged
    assert lines["SKU-C"].fragile.value is True
    assert lines["SKU-B"].mass.status == "needs_review"  # "25" without unit, net
    assert [e.sku for e in result.lot.excluded] == ["SKU-E"]
