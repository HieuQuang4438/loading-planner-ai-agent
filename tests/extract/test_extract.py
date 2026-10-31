"""Tests for reading a lot's documents (src.extract): units, spreadsheets as text, the fixed merge and the pipeline,
with a mocked model whose answers are the correct reading of data/probe (simulated)."""
from __future__ import annotations

from pathlib import Path

import pytest

from src.extract import units
from src.extract.documents import UnsupportedFile, load, sheet_text
from src.extract.merge import Doc, merge
from src.extract.pipeline import extract
from src.llm.client import LLMError
from src.lot.schema import Dims, Stacking
from tests.extract.probe_readings import BY_FILE, LABEL, PL, SPEC

PROBE = Path(__file__).resolve().parents[2] / "data" / "probe"


# --- units -------------------------------------------------------------------------------------------


@pytest.mark.parametrize(("text", "metres"), [
    ("60x40x50 cm", (0.6, 0.4, 0.5)), ("800 x 600 x 500 mm", (0.8, 0.6, 0.5)), ("1,2 × 1 × 1,5 m", (1.2, 1.0, 1.5)),
    ("50 x 50 x 60 CM", (0.5, 0.5, 0.6)), ("Size: 600x400x450mm", (0.6, 0.4, 0.45)),
])
def test_sizes_with_a_unit_become_metres(text, metres):
    assert units.dims_m(text) == metres


@pytest.mark.parametrize("text", ["50*50*60", "60 cm x 40 mm x 50 cm", "1200 x 1000 mm, loaded height 1.5 m", "", None])
def test_sizes_without_one_unit_are_not_guessed(text):
    assert units.dims_m(text) is None


def test_a_size_without_unit_agrees_only_when_some_unit_makes_it_equal():
    assert units.unitless_matches("50*50*60", (0.5, 0.5, 0.6))
    assert not units.unitless_matches("50*50*60", (0.5, 0.5, 0.7))
    assert not units.unitless_matches("50x50x60 cm", (0.5, 0.5, 0.6))  # it has a unit: read, not matched


@pytest.mark.parametrize(("text", "kg"), [("12 kg", 12.0), ("G.W. 18 KG", 18.0), ("12,5kg", 12.5), ("500 g", 0.5),
                                          ("160 kg", 160.0), ("25", None), (None, None)])
def test_masses(text, kg):
    assert units.mass_kg(text) == kg


def test_quantities_take_the_first_whole_number():
    assert units.first_int("200 thùng") == 200 and units.first_int("10 pallet x 24 thùng") == 10
    assert units.first_int("thùng") is None


# --- documents ----------------------------------------------------------------------------------------


def test_a_spreadsheet_becomes_rows_that_name_their_place():
    text = sheet_text(PL, (PROBE / PL).read_bytes())
    lines = text.splitlines()
    assert lines[0].startswith("[Packing List · dòng 1] A=CÔNG TY")
    assert "[Packing List · dòng 6] A=SKU-A | B=Quạt đứng FS-40 | C=200 thùng | D=60x40x50 cm | E=12 kg" in lines
    assert not any("dòng 4]" in line or "dòng 11]" in line for line in lines)  # empty rows are left out


def test_a_csv_reads_the_same_way():
    text = sheet_text("packing_list.csv", (PROBE / "packing_list.csv").read_bytes())
    assert "[CSV · dòng 2] A=SKU-A | B=Quạt đứng FS-40 | C=200 thùng | D=60x40x50 cm | E=12 kg" in text


def test_files_go_as_text_or_as_bytes_and_others_are_refused():
    assert load(PL, (PROBE / PL).read_bytes()).text
    pdf = load(SPEC, b"%PDF")
    assert (pdf.data, pdf.mime, pdf.text) == (b"%PDF", "application/pdf", None)
    assert load(LABEL, b"png").mime == "image/png"
    with pytest.raises(UnsupportedFile):
        load("notes.docx", b"")


# --- merge -------------------------------------------------------------------------------------------


@pytest.fixture(scope="module")
def lot():
    return merge("Lô xuất T11", [Doc(name, reading) for name, reading in BY_FILE.items()])


def line(lot, line_id):
    return next(x for x in lot.lines if x.id == line_id)


def test_each_packing_list_row_is_a_line_with_the_code_kept(lot):
    assert [(x.id, x.sku) for x in lot.lines] == [
        ("SKU-A", "SKU-A"), ("SKU-B", "SKU-B"), ("SKU-C", "SKU-C"), ("SKU-D", "SKU-D"), ("SKU-A-2", "SKU-A")]
    qty = line(lot, "SKU-A").qty  # the code is on two rows: whether both are shipped is asked (src.lot.review)
    assert (qty.value, qty.status) == (200, "needs_review") and line(lot, "SKU-B").qty.status == "extracted"


def test_sources_that_disagree_leave_the_value_empty_for_the_user(lot):
    dims = line(lot, "SKU-A").dims  # 60x40x50 cm against 600x400x450 mm
    assert (dims.value, dims.status) == (None, "needs_review")
    assert [s.raw for s in dims.sources] == ["60x40x50 cm", "600x400x450 mm"]
    assert line(lot, "SKU-A-2").dims.value == Dims(L=0.6, W=0.4, H=0.45)  # the extra row agrees with the spec


def test_sources_that_agree_are_extracted_whatever_their_units(lot):
    dims = line(lot, "SKU-B").dims  # 800 x 600 x 500 mm and 80x60x50 cm
    assert (dims.value, dims.status) == (Dims(L=0.8, W=0.6, H=0.5), "extracted")
    assert line(lot, "SKU-B").posture.value == "upright" and line(lot, "SKU-B").posture.status == "extracted"


def test_a_size_without_unit_is_settled_only_by_an_equal_size(lot):
    dims = line(lot, "SKU-C").dims  # 50*50*60 with 50x50x60 cm (spec) and 50 x 50 x 60 CM (label)
    assert (dims.value, dims.status) == (Dims(L=0.5, W=0.5, H=0.6), "extracted")
    alone = merge("x", [Doc(PL, BY_FILE[PL])])
    assert next(x for x in alone.lines if x.id == "SKU-C").dims.status == "needs_review"  # nothing settles it


def test_a_net_mass_is_not_the_packing_mass(lot):
    mass = line(lot, "SKU-A").mass  # N.W. 12 kg, G.W. 12.5 kg
    assert (mass.value, mass.status) == (12.5, "needs_review")
    assert mass.sources[0].raw == "N.W. 12 kg"
    mass = line(lot, "SKU-B").mass  # "25" without unit, net column; G.W. 26 kg
    assert (mass.value, mass.status) == (26.0, "needs_review")


def test_a_missing_mass_is_never_filled_from_nothing():
    only_pl = merge("x", [Doc(PL, BY_FILE[PL])])
    mass = next(x for x in only_pl.lines if x.id == "SKU-C").mass
    assert (mass.value, mass.status, mass.sources) == (None, "needs_review", [])


def test_label_marks_are_proposals_that_need_confirming(lot):
    c = line(lot, "SKU-C")
    assert (c.posture.value, c.posture.status) == ("upright", "needs_review")
    assert (c.stacking.value, c.stacking.status) == (Stacking(kind="limited", tiers=2), "needs_review")
    assert (c.fragile.value, c.fragile.status) == (True, "needs_review")
    assert (c.mass.value, c.mass.status) == (18.0, "extracted")  # a mass on the label agreeing with the spec is no mark


def test_a_spec_constraint_without_conflict_is_extracted(lot):
    a = line(lot, "SKU-A")
    assert (a.stacking.value, a.stacking.status) == (Stacking(kind="limited", tiers=5), "extracted")
    assert (a.posture.value, a.posture.status) == (None, "needs_review")  # no document says


def test_a_pallet_line_takes_pallet_values_and_its_count_needs_confirming(lot):
    d = line(lot, "SKU-D")
    assert d.unit == "pallet" and (d.qty.value, d.qty.status) == (10, "needs_review")
    assert d.dims.value == Dims(L=1.2, W=1.0, H=1.5) and d.dims.status == "needs_review"  # the spec's size is in words
    assert all("40x30x35" not in (s.raw or "") for s in d.dims.sources)  # the carton size is not a pallet's
    assert (d.stacking.value, d.stacking.status) == (Stacking(kind="none"), "extracted")
    assert d.mass.value == 160.0


def test_a_code_only_the_spec_names_is_left_out_with_its_reason(lot):
    (e,) = lot.excluded
    assert e.sku == "SKU-E" and "không có trong lô" in e.reason and e.sources[0].file == SPEC


def test_a_packing_list_row_the_spec_calls_not_shipped_needs_review():
    spec = BY_FILE[SPEC].model_copy(deep=True)
    spec.items[1].in_shipment = False  # SKU-B
    lot = merge("x", [Doc(PL, BY_FILE[PL]), Doc(SPEC, spec)])
    qty = next(x for x in lot.lines if x.id == "SKU-B").qty
    assert (qty.value, qty.status) == (80, "needs_review")
    assert [s.raw for s in qty.sources] == ["80 thùng", "not in shipment"]


# --- pipeline -----------------------------------------------------------------------------------------


class FakeLLM:
    """Answers each document with its correct reading; `fail` names files whose call fails."""

    def __init__(self, fail: tuple[str, ...] = ()) -> None:
        self.fail, self.calls = fail, []

    def generate(self, name, parts, schema):
        file = parts[0].text.removeprefix("Tên tệp: ")
        self.calls.append((name, file, parts[1]))
        if file in self.fail:
            raise LLMError("boom")
        return BY_FILE[file]


def uploads():
    return [load(name, (PROBE / name).read_bytes()) for name in (PL, SPEC, LABEL)]


def test_each_document_is_one_call_with_text_or_bytes():
    llm = FakeLLM()
    result = extract(llm, "Lô xuất T11", uploads())
    assert sorted(f for _, f, _ in llm.calls) == sorted([PL, SPEC, LABEL])
    sent = {f: p for _, f, p in llm.calls}
    assert "Packing List · dòng 6" in sent[PL].text and sent[SPEC].mime == "application/pdf" and sent[LABEL].data
    assert all(name == "extract_document" for name, _, _ in llm.calls)
    assert [x.id for x in result.lot.lines][:2] == ["SKU-A", "SKU-B"] and result.failed == {}


def test_a_failed_document_is_reported_and_the_others_still_count():
    result = extract(FakeLLM(fail=(LABEL,)), "x", uploads())
    assert list(result.failed) == [LABEL]
    c = next(x for x in result.lot.lines if x.id == "SKU-C")
    assert c.posture.value is None and c.stacking.value == Stacking(kind="limited", tiers=2)  # the spec still counts


def test_the_prompt_file_exists_and_says_never_to_fill():
    from src.llm.client import prompt

    assert "Never fill a value the document does not give" in prompt("extract_document")
