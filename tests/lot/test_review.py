"""Tests for the points the user must confirm (src.lot.review; docs/product/ux.md §4): found by fixed rules from the
probe's merged lot (data/probe, simulated), answered, and kept when a document is added."""
from __future__ import annotations

import pytest

from src.checker import check
from src.engines import e1
from src.extract.merge import Doc, merge
from src.lot.engine import LotNotReady, confirm_rest, to_instance
from src.lot.review import AnswerError, answer, carry, find_points, forget, refresh
from src.lot.schema import Dims, Stacking
from src.model import ContainerType, Params
from tests.extract.probe_readings import BY_FILE, PL, SPEC

CONTAINERS = (ContainerType("20GP", 5.898, 2.352, 2.393, 2.34, 2.28, 28000, 1500),
              ContainerType("40HC", 12.032, 2.352, 2.698, 2.34, 2.58, 26500, 2500))
AT = "2026-10-24T15:00:00+00:00"


def probe(readings=BY_FILE):
    return refresh(merge("Lô xuất T11", [Doc(name, reading) for name, reading in readings.items()]))


def line(lot, line_id):
    return next(x for x in lot.lines if x.id == line_id)


def point(lot, title_start):
    return next(p for p in lot.points if p.title.startswith(title_start))


def answer_all_first(lot):
    while lot.open_points():
        lot = answer(lot, lot.open_points()[0].id, "alice", choice=0, at=AT)
    return lot


# --- finding -------------------------------------------------------------------------------------------------------


def test_the_probe_gives_its_points_in_page_order():
    lot = probe()
    assert [(p.id, p.title, p.fields) for p in lot.points] == [
        (1, "SKU-A: 2 dòng cùng mã", ["SKU-A.qty", "SKU-A-2.qty"]),
        (2, "SKU-A: kích thước khác nhau giữa các tài liệu", ["SKU-A.dims"]),
        (3, "SKU-A: khối lượng tịnh hay cả bì", ["SKU-A.mass", "SKU-A-2.mass"]),
        (4, "SKU-B: khối lượng tịnh hay cả bì", ["SKU-B.mass"]),
        (5, "SKU-C: ràng buộc xếp từ nhãn", ["SKU-C.posture", "SKU-C.stacking", "SKU-C.fragile"]),
        (6, "SKU-D: kiện là pallet", ["SKU-D.qty", "SKU-D.dims", "SKU-D.mass"]),
        (7, "Tư thế, chồng, dễ vỡ chưa có trong tài liệu",
         ["SKU-A.posture", "SKU-A.fragile", "SKU-B.stacking", "SKU-B.fragile", "SKU-D.posture", "SKU-D.fragile",
          "SKU-A-2.posture", "SKU-A-2.fragile"]),
    ]


def test_every_field_needing_review_is_in_exactly_one_point():
    lot = probe()
    review = [f"{x.id}.{n}" for x in lot.lines for n, f in x.fields().items() if f.status == "needs_review"]
    settled = [f for p in lot.points for f in p.fields]
    assert sorted(settled) == sorted(review)


def test_the_same_lot_always_gives_the_same_points():
    assert probe().points == probe().points
    lot = probe()
    assert find_points(lot) == lot.points  # finding again changes nothing


def test_sources_that_disagree_are_one_option_each_with_their_source():
    dims = point(probe(), "SKU-A: kích thước")
    assert [(o.label, o.sets, [s.raw for s in o.sources]) for o in dims.options] == [
        ("0,60 × 0,40 × 0,50 m", {"SKU-A.dims": {"L": 0.6, "W": 0.4, "H": 0.5}}, ["60x40x50 cm"]),
        ("0,60 × 0,40 × 0,45 m", {"SKU-A.dims": {"L": 0.6, "W": 0.4, "H": 0.45}}, ["600x400x450 mm"]),
    ]


def test_a_net_mass_is_offered_last_and_named_net():
    mass = point(probe(), "SKU-B: khối lượng")
    assert [o.label for o in mass.options] == ["26 kg", "25 kg (khối lượng tịnh, N.W.)"]


def test_a_size_without_a_unit_is_offered_in_each_unit_that_fits():
    readings = {name: r.model_copy(deep=True) for name, r in BY_FILE.items()}
    readings[PL].items[2].dims_text = "50*50*60"  # SKU-C, as written; the spec and the label are left out
    lot = probe({PL: readings[PL]})
    p = point(lot, "SKU-C: kích thước")
    assert p.title == "SKU-C: kích thước không có đơn vị"
    assert [o.label for o in p.options] == ["0,50 × 0,50 × 0,60 m (không ghi đơn vị, hiểu là cm)",
                                            "0,05 × 0,05 × 0,06 m (không ghi đơn vị, hiểu là mm)"]


def test_a_row_another_document_calls_not_shipped_is_asked_keep_or_drop():
    spec = BY_FILE[SPEC].model_copy(deep=True)
    spec.items[1].in_shipment = False  # SKU-B
    lot = probe({PL: BY_FILE[PL], SPEC: spec})
    p = point(lot, "SKU-B: có trong lô")
    assert [(o.label, o.sets) for o in p.options] == [("Giữ trong lô: 80 thùng", {"SKU-B.qty": 80}),
                                                      ("Loại khỏi lô", {"SKU-B.line": "drop"})]
    dropped = answer(lot, p.id, "alice", choice=1, at=AT)
    assert "SKU-B" not in [x.id for x in dropped.lines] and dropped.excluded[-1].sku == "SKU-B"


# --- answering -----------------------------------------------------------------------------------------------------


def test_answering_every_point_lets_the_lot_run_and_pack_valid():
    lot = answer_all_first(probe())
    with pytest.raises(LotNotReady):
        to_instance(lot, CONTAINERS)  # the extracted fields are confirmed by the user too, in one step
    confirm_rest(lot, "alice", at=AT)
    instance = to_instance(lot, CONTAINERS)
    assert {x.id: (x.qty, x.mass) for x in instance.items}["SKU-A"] == (200, 12.5)
    params = Params(delta=0.05, alpha=0.8)
    solution, _ = e1.solve(instance, params, 5.0, 1)
    assert check(instance, solution, params).ok


def test_an_answer_confirms_its_fields_and_records_who_and_when():
    lot = probe()
    lot = answer(lot, 3, "alice", choice=0, at=AT)
    for line_id in ("SKU-A", "SKU-A-2"):
        f = line(lot, line_id).mass
        assert (f.value, f.status, f.confirmed_by, f.confirmed_at) == (12.5, "confirmed", "alice", AT)
    p = lot.points[2]
    assert (p.id, p.chosen, p.resolved_by, p.resolved_at) == (3, 0, "alice", AT)
    assert [q.id for q in lot.open_points()] == [1, 2, 4, 5, 6, 7]  # the numbers do not move


def test_a_value_of_the_users_own_is_checked_like_any_other():
    lot = probe()
    done = answer(lot, 2, "alice", values={"SKU-A.dims": {"L": 0.6, "W": 0.4, "H": 0.48}}, at=AT)
    assert line(done, "SKU-A").dims.value == Dims(L=0.6, W=0.4, H=0.48) and done.points[1].chosen is None
    with pytest.raises(AnswerError, match="không hợp lệ"):
        answer(lot, 2, "alice", values={"SKU-A.dims": {"L": 60, "W": 40, "H": 48}})  # cm read as m: over 20 m
    with pytest.raises(AnswerError, match="không hợp lệ"):
        answer(lot, 4, "alice", values={"SKU-B.mass": -1})
    assert line(lot, "SKU-A").dims.status == "needs_review"  # a refused answer leaves the lot as it was


def test_an_answer_must_settle_every_field_of_its_point_and_only_those():
    lot = probe()
    with pytest.raises(AnswerError, match="khối lượng của SKU-A-2"):
        answer(lot, 3, "alice", values={"SKU-A.mass": 12.5})
    with pytest.raises(AnswerError, match="không xác nhận"):
        answer(lot, 4, "alice", values={"SKU-A.mass": 12.5})
    with pytest.raises(AnswerError, match="Chưa chọn"):
        answer(lot, 4, "alice")
    with pytest.raises(AnswerError, match="Không có câu hỏi H99"):
        answer(lot, 99, "alice", choice=0)

def test_an_option_that_leaves_a_field_to_enter_takes_it_with_the_choice():
    # the pallet point: the documents give the count and size, no gross mass of a pallet
    lot = probe()
    line(lot, "SKU-D").mass.value, line(lot, "SKU-D").mass.sources = None, []
    lot = refresh(lot)
    p = point(lot, "SKU-D: kiện là pallet")
    assert "SKU-D.mass" not in p.options[0].sets and "nhập thêm khối lượng" in p.options[0].label
    with pytest.raises(AnswerError, match="Còn thiếu khối lượng của SKU-D"):
        answer(lot, p.id, "alice", choice=0)
    done = answer(lot, p.id, "alice", choice=0, values={"SKU-D.mass": 160})
    assert line(done, "SKU-D").mass.value == 160 and line(done, "SKU-D").mass.status == "confirmed"


def test_a_point_answered_may_be_answered_again_and_the_new_answer_wins():
    done = answer(probe(), 4, "alice", choice=0, at=AT)
    again = answer(done, 4, "bob", choice=1, at=AT)
    f = line(again, "SKU-B").mass
    assert (f.value, f.status, f.confirmed_by) == (25.0, "confirmed", "bob")
    assert (again.points[3].chosen, again.points[3].resolved_by) == (1, "bob")


def test_the_label_point_sets_every_mark_at_once():
    lot = answer(probe(), 5, "alice", choice=0, at=AT)
    c = line(lot, "SKU-C")
    assert (c.posture.value, c.stacking.value, c.fragile.value) == ("upright", Stacking(kind="limited", tiers=2), True)
    assert {c.posture.status, c.stacking.status, c.fragile.status} == {"confirmed"}


def test_dropping_a_repeated_row_moves_it_out_of_the_lot_with_its_reason():
    lot = probe()
    lot = answer(lot, 1, "alice", choice=2, at=AT)  # "Bỏ dòng Packing List · dòng 10"
    assert [x.id for x in lot.lines] == ["SKU-A", "SKU-B", "SKU-C", "SKU-D"]
    assert lot.excluded[-1].reason == "Người dùng bỏ dòng SKU-A-2 khỏi lô"
    assert point(lot, "SKU-A: khối lượng").fields == ["SKU-A.mass"]  # the dropped row's fields are no longer asked


def test_answering_a_drop_again_brings_the_row_back_from_the_documents():
    read = probe()
    restore = {x.id: x for x in read.lines}
    lot = answer(answer(read, 3, "alice", choice=0, at=AT), 1, "alice", choice=2, at=AT)  # mass, then drop SKU-A-2
    with pytest.raises(AnswerError, match="SKU-A-2"):
        answer(lot, 1, "alice", choice=0)  # nothing to bring it back from
    kept = answer(lot, 1, "alice", choice=0, at=AT, restore=restore)  # "Giữ cả 2 dòng"
    assert [x.id for x in kept.lines] == [x.id for x in read.lines] and kept.excluded == read.excluded
    assert line(kept, "SKU-A-2").qty.status == "confirmed"
    assert line(kept, "SKU-A").mass.status == "confirmed"
    assert point(kept, "SKU-A: khối lượng").fields == ["SKU-A-2.mass"]  # the row's other fields are asked again


# --- a document added later -----------------------------------------------------------------------------------------


def test_adding_a_document_keeps_what_was_confirmed_unless_a_new_source_disagrees():
    two = {PL: BY_FILE[PL], SPEC: BY_FILE[SPEC]}
    old = answer_all_first(probe(two))
    confirm_rest(old, "alice", at=AT)

    again = carry(old, probe())  # the label photo added: it agrees with what was confirmed for SKU-C
    assert line(again, "SKU-A").mass.status == "confirmed" and line(again, "SKU-C").mass.status == "confirmed"
    assert len(line(again, "SKU-C").mass.sources) == 2  # spec and label

    readings = {name: r.model_copy(deep=True) for name, r in BY_FILE.items()}  # the label says 20 kg, not 18
    readings["handling_label_sku_c.png"].items[0].mass_text = "G.W. 20 KG"
    changed = carry(old, probe(readings))
    assert line(changed, "SKU-C").mass.status == "needs_review"
    assert point(changed, "SKU-C: khối lượng").options[0].label == "18 kg"
    assert line(changed, "SKU-A").mass.status == "confirmed"


# --- a document removed ---------------------------------------------------------------------------------------------


def test_removing_a_document_asks_again_what_was_confirmed_on_it_and_keeps_the_rest():
    old = answer_all_first(probe())
    confirm_rest(old, "alice", at=AT)
    after = carry(forget(old, SPEC), probe({k: v for k, v in BY_FILE.items() if k != SPEC}))
    assert not any(s.file == SPEC for x in after.lines for f in x.fields().values() for s in f.sources)
    b_mass = line(after, "SKU-B").mass  # 26 kg came from the spec: the packing list alone gives no gross mass
    assert b_mass.status != "confirmed" and b_mass.confirmed_by is None
    qty = line(after, "SKU-B").qty  # confirmed on the packing list only: kept
    assert (qty.status, qty.confirmed_by) == ("confirmed", "alice")
