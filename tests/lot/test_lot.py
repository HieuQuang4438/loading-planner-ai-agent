"""Tests for the product's lot (src.lot; ADR-0001): validation, JSON round trip, the gate to the engine and the mapping
of posture and stacking onto the engine's item lines."""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from src.checker import check
from src.engines import e1
from src.lot.engine import LotNotReady, confirm, confirm_rest, default_for, to_instance
from src.lot.schema import Dims, Lot, LotField, Stacking, line_ids
from src.model import ContainerType, Params
from tests.lot.probe import probe_lot

CONTAINERS = (ContainerType("20GP", 5.898, 2.352, 2.393, 2.34, 2.28, 28000, 1500),
              ContainerType("40HC", 12.032, 2.352, 2.698, 2.34, 2.58, 26500, 2500))
PARAMS = Params(delta=0.05, alpha=0.8)


def confirmed_lot() -> Lot:
    """The probe lot as the user leaves it: every field without a value takes its default, the rest is confirmed."""
    lot = probe_lot()
    for line in lot.lines:
        for name, f in line.fields().items():
            if f.value is None:
                confirm(f, "alice", default_for(name))
            elif f.status == "needs_review":
                confirm(f, "alice")
    confirm_rest(lot, "alice")
    return lot


# --- validation ------------------------------------------------------------------------------------


def test_the_probe_lot_is_valid_and_round_trips_through_json():
    lot = probe_lot()
    again = Lot.model_validate_json(lot.model_dump_json())
    assert again == lot and again.schema_version == 1
    assert [line.sku for line in again.lines] == ["SKU-A", "SKU-A", "SKU-B", "SKU-C", "SKU-D"]  # the codes as written


def test_a_field_without_a_value_must_need_review():
    with pytest.raises(ValidationError, match="needs_review"):
        LotField[float](value=None, status="extracted")
    with pytest.raises(ValidationError, match="needs_review"):
        LotField[float](value=None, status="confirmed")


@pytest.mark.parametrize("dims", [dict(L=0, W=1, H=1), dict(L=1, W=-1, H=1), dict(L=1, W=1, H=25)])
def test_sizes_are_positive_metres_below_any_reading_error(dims):
    with pytest.raises(ValidationError):
        Dims(**dims)


def test_qty_and_mass_must_be_positive():
    data = probe_lot().model_dump()
    data["lines"][0]["qty"]["value"] = 0
    with pytest.raises(ValidationError, match="qty must be > 0"):
        Lot.model_validate(data)
    data = probe_lot().model_dump()
    data["lines"][0]["mass"]["value"] = -1.0
    with pytest.raises(ValidationError, match="mass must be > 0"):
        Lot.model_validate(data)


def test_tiers_go_with_a_limited_stacking_only():
    assert Stacking(kind="limited", tiers=2).tiers == 2
    for bad in (dict(kind="limited"), dict(kind="free", tiers=3), dict(kind="none", tiers=1)):
        with pytest.raises(ValidationError):
            Stacking(**bad)


def test_unknown_fields_and_duplicate_line_ids_are_refused():
    data = probe_lot().model_dump()
    data["lines"][0]["colour"] = "red"
    with pytest.raises(ValidationError):
        Lot.model_validate(data)
    data = probe_lot().model_dump()
    data["lines"][1]["id"] = "SKU-A"
    with pytest.raises(ValidationError, match="unique"):
        Lot.model_validate(data)


def test_line_ids_keep_the_code_and_number_the_repeats():
    assert line_ids(["SKU-A", "SKU-B", "SKU-A", "SKU-A"]) == ["SKU-A", "SKU-B", "SKU-A-2", "SKU-A-3"]
    assert line_ids(["A 1", "A#1", "X-2", "X", "X"]) == ["A-1", "A-1-2", "X-2", "X", "X-3"]


def test_the_schema_can_be_given_to_a_model_as_json_schema():
    schema = Lot.model_json_schema()
    assert "lines" in schema["properties"] and "$defs" in schema


# --- the gate to the engine -------------------------------------------------------------------------


def test_a_lot_with_fields_not_confirmed_never_reaches_the_engine():
    lot = probe_lot()
    with pytest.raises(LotNotReady) as refused:
        to_instance(lot, CONTAINERS)
    assert "SKU-C.mass" in refused.value.fields and "SKU-A.posture" in refused.value.fields
    assert "SKU-B.qty" in refused.value.fields  # extracted is not confirmed either (brief §2.3)


def test_confirming_the_rest_is_refused_while_a_field_needs_review():
    lot = probe_lot()
    with pytest.raises(LotNotReady):
        confirm_rest(lot, "alice")
    assert lot.lines[2].qty.status == "extracted"  # nothing changed


def test_a_field_without_a_value_takes_a_confirmation_only_with_one():
    f = LotField[float](value=None, status="needs_review")
    with pytest.raises(ValueError):
        confirm(f, "alice")
    confirm(f, "alice", 18.0, at="2026-10-24T14:32:00+00:00")
    assert (f.value, f.status, f.confirmed_by, f.confirmed_at) == (18.0, "confirmed", "alice", "2026-10-24T14:32:00+00:00")


def test_the_confirmed_probe_lot_maps_onto_the_engine_and_packs_valid():
    instance = to_instance(confirmed_lot(), CONTAINERS)
    by_id = {line.id: line for line in instance.items}
    assert list(by_id) == ["SKU-A", "SKU-A-2", "SKU-B", "SKU-C", "SKU-D"]
    assert (by_id["SKU-A-2"].H, by_id["SKU-A"].mass, by_id["SKU-D"].qty) == (0.45, 12.5, 10)
    assert by_id["SKU-A"].tiers_unlimited and by_id["SKU-A"].load is None and not by_id["SKU-A"].tippable
    assert (by_id["SKU-C"].tiers, by_id["SKU-C"].load, by_id["SKU-C"].tiers_unlimited) == (2, None, False)
    assert (by_id["SKU-D"].tiers, by_id["SKU-D"].load) == (1, 0.0)
    assert instance.container_types == CONTAINERS and instance.n_items == 380
    assert instance.name == "Lo-xuat-T11-dien-gia-dung" and instance.meta["lot"] == "Lô xuất T11 — điện gia dụng"

    solution, _ = e1.solve(instance, PARAMS, 5.0, 1)
    assert check(instance, solution, PARAMS).ok


def test_a_tippable_posture_lets_the_engine_tip():
    lot = confirmed_lot()
    lot.lines[0].posture.value = "tippable"
    assert to_instance(lot, CONTAINERS).items[0].tippable is True
