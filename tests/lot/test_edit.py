"""Tests for the user's own changes to a lot's rows (src.lot.edit), on the probe's merged lot (simulated):
edited, added, taken out and put back, and kept when the lot is merged again."""
from __future__ import annotations

import pytest

from src.lot.edit import add_line, drop_line, edit_line, restore_line
from src.lot.engine import confirm_rest, to_instance
from src.lot.review import AnswerError, answer, carry, is_manual
from src.lot.schema import Dims
from tests.lot.test_review import AT, CONTAINERS, answer_all_first, line, probe

NEW = {"qty": 10, "dims": {"L": 1.0, "W": 0.8, "H": 0.6}, "mass": 40, "posture": "upright",
       "stacking": {"kind": "free"}, "fragile": False}


def test_every_row_read_from_the_documents_has_a_source():
    assert not any(is_manual(x) for x in probe().lines)


def test_an_edit_confirms_its_values_but_not_a_field_an_open_point_settles():
    lot = probe()
    done = edit_line(lot, "SKU-B", "alice", {"qty": 90}, at=AT)
    q = line(done, "SKU-B").qty
    assert (q.value, q.status, q.confirmed_by) == (90, "confirmed", "alice") and q.sources  # sources kept to see
    with pytest.raises(AnswerError, match="H4"):
        edit_line(lot, "SKU-B", "alice", {"mass": 30})
    with pytest.raises(AnswerError, match="không sửa được"):
        edit_line(lot, "SKU-B", "alice", {}, sku="SKU-X")
    with pytest.raises(AnswerError, match="không hợp lệ"):
        edit_line(lot, "SKU-B", "alice", {"qty": -1})


def test_a_row_added_is_confirmed_runs_and_may_be_renamed():
    lot = answer_all_first(probe())
    confirm_rest(lot, "alice", at=AT)
    added = add_line(lot, "alice", "SKU-A", NEW, description="thêm tay", at=AT)
    new = added.lines[-1]
    assert (new.id, new.sku, is_manual(new)) == ("SKU-A-3", "SKU-A", True)  # SKU-A and SKU-A-2 are taken
    assert {x.id: x.qty for x in to_instance(added, CONTAINERS).items}["SKU-A-3"] == 10
    renamed = edit_line(added, "SKU-A-3", "alice", {"dims": {"L": 1.2, "W": 0.8, "H": 0.6}}, sku="SKU-Z", at=AT)
    assert (renamed.lines[-1].sku, renamed.lines[-1].dims.value) == ("SKU-Z", Dims(L=1.2, W=0.8, H=0.6))
    with pytest.raises(AnswerError, match="Thiếu mass"):
        add_line(lot, "alice", "SKU-Y", {**NEW, "mass": None})


def test_a_row_taken_out_stays_out_when_merged_again_until_put_back():
    read = probe()
    restore = {x.id: x for x in read.lines}
    out = drop_line(read, "SKU-B")
    assert "SKU-B" not in [x.id for x in out.lines] and out.excluded[-1].reason == "Người dùng bỏ dòng SKU-B khỏi lô"
    again = carry(out, probe())
    assert "SKU-B" not in [x.id for x in again.lines] and again.excluded[-1].sku == "SKU-B"
    back = restore_line(again, "SKU-B", restore)
    assert [x.id for x in back.lines] == [x.id for x in read.lines] and back.excluded == read.excluded
    with pytest.raises(AnswerError, match="không bị bỏ"):
        restore_line(back, "SKU-B", restore)


def test_a_row_dropped_at_a_point_is_put_back_and_its_point_asked_again():
    read = probe()
    out = answer(read, 1, "alice", choice=2, at=AT)  # drop SKU-A-2
    back = restore_line(out, "SKU-A-2", {x.id: x for x in read.lines})
    assert [x.id for x in back.lines] == [x.id for x in read.lines]
    assert back.points[0].title == "SKU-A: 2 dòng cùng mã" and back.points[0].resolved_at is None


def test_a_row_added_is_kept_when_merged_again_and_a_row_added_taken_out_is_gone():
    lot = add_line(probe(), "alice", "SKU-Z", NEW, at=AT)
    again = carry(lot, probe())
    assert again.lines[-1].sku == "SKU-Z" and again.lines[-1].qty.status == "confirmed"
    gone = drop_line(again, again.lines[-1].id)
    assert "SKU-Z" not in [x.sku for x in gone.lines + gone.excluded]
