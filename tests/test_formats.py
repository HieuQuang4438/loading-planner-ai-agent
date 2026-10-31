from pathlib import Path

import pytest

from src.formats import (
    dumps,
    instance_from_dict,
    instance_to_dict,
    read_instance,
    read_solution,
    solution_to_dict,
    instance_issues,
    validate_instance,
    write_instance,
    write_solution,
)
from src.model import ContainerType
from tests.builders import BOX, at, instance, line, solution


def test_instance_round_trips(tmp_path: Path):
    inst = instance(line("A", qty=3, load=12.5), line("B", tippable=True, load=None))
    write_instance(tmp_path / "i.json", inst)
    assert read_instance(tmp_path / "i.json") == inst


def test_solution_round_trips(tmp_path: Path):
    sol = solution(at("A#1", 0.0), at("A#2", 1.1, z=0.25, o="WLH"))
    write_solution(tmp_path / "s.json", sol)
    assert read_solution(tmp_path / "s.json") == sol


def test_written_file_is_lf_utf8_and_deterministic(tmp_path: Path):
    inst = instance(line("Kiện-Á", qty=2))
    write_instance(tmp_path / "a.json", inst)
    write_instance(tmp_path / "b.json", inst)
    raw = (tmp_path / "a.json").read_bytes()
    assert b"\r\n" not in raw
    assert raw == (tmp_path / "b.json").read_bytes()
    assert raw.decode("utf-8") == dumps(instance_to_dict(inst))


def test_solution_dict_keeps_placement_order():
    sol = solution(at("B#1", 0.0), at("A#1", 2.0))
    assert [p["item"] for p in solution_to_dict(sol)["placements"]] == ["B#1", "A#1"]


def test_valid_instance_has_no_issues():
    assert validate_instance(instance(line("A", qty=2))) == []


def test_bad_fields_are_reported():
    issues = validate_instance(instance(
        line("A", qty=0),
        line("B", tiers=0),
        line("C", load=-1.0),
        line("D", mass=0.0),
        line("E#1"),
    ))
    assert len(issues) == 5


def test_duplicate_line_ids_are_reported():
    assert "duplicate item line ids" in validate_instance(instance(line("A"), line("A")))


def test_door_larger_than_interior_is_reported():
    bad = ContainerType("BAD", L=10.0, W=2.0, H=2.0, door_w=2.1, door_h=1.9, max_mass=1000.0, cost=1.0)
    assert validate_instance(instance(line("A"), types=(bad,))) == ["container type BAD: door larger than interior"]


def test_item_that_fits_no_container_is_reported():
    # Inside the container but taller than the door, and not allowed to tip over.
    [issue] = instance_issues(instance(line("A", H=1.95)))
    assert issue.message == "item line A: fits no container type (through no door)"
    assert (issue.line, issue.code, issue.params["door_h"]) == ("A", "fit_door", 1.9)


def test_item_larger_than_every_container_says_so():
    [issue] = instance_issues(instance(line("A", L=14.0)))
    assert (issue.code, issue.params["L"], issue.params["max_L"]) == ("fit_size", 14.0, 10.0)


def test_item_too_large_and_too_heavy_gets_both_reasons():
    codes = [i.code for i in instance_issues(instance(line("A", L=14.0, mass=BOX.max_mass + 1)))]
    assert codes == ["fit_size", "fit_mass"]


def test_every_problem_is_reported_at_once():
    # A bad qty on one line does not hide that another line fits no container (C4).
    issues = instance_issues(instance(line("C", qty=0), line("B", L=14.0), line("D", mass=40000.0)))
    assert [(i.line, i.code) for i in issues] == [("C", "qty_invalid"), ("B", "fit_size"), ("D", "fit_mass")]


def test_a_bad_container_type_is_left_out_of_the_fit_check():
    bad = ContainerType("BAD", L=20.0, W=3.0, H=3.0, door_w=3.0, door_h=3.0, max_mass=0.0, cost=1.0)
    issues = instance_issues(instance(line("A", L=14.0), types=(BOX, bad)))
    assert [(i.container, i.line, i.code) for i in issues] == [
        ("BAD", None, "container_non_positive"), (None, "A", "fit_size")]


def test_tippable_item_that_fits_on_its_side_is_valid():
    assert validate_instance(instance(line("A", L=1.5, W=1.0, H=1.95, tippable=True))) == []


def test_item_heavier_than_every_container_is_reported():
    [issue] = instance_issues(instance(line("A", mass=BOX.max_mass + 1)))
    assert issue.message == "item line A: fits no container type (too heavy)"
    assert (issue.field, issue.code, issue.params) == ("mass", "fit_mass", {"mass": 1001.0, "max_mass": 1000.0, "size_fits": True})


def test_writer_writes_only_the_new_key(tmp_path: Path):
    write_instance(tmp_path / "i.json", instance(line("A", tippable=True)))
    text = (tmp_path / "i.json").read_text(encoding="utf-8")
    assert '"tippable": true' in text and "tiltable" not in text


def test_old_key_writer_writes_tiltable_and_both_read_back_equal(tmp_path: Path):
    inst = instance(line("A", tippable=True), line("B"))
    write_instance(tmp_path / "old.json", inst, old_key=True)
    text = (tmp_path / "old.json").read_text(encoding="utf-8")
    assert '"tiltable": true' in text and "tippable" not in text
    assert read_instance(tmp_path / "old.json") == inst


def test_reader_takes_the_old_key():
    data = instance_to_dict(instance(line("A", tippable=True)))
    row = data["items"][0]
    row["tiltable"] = row.pop("tippable")
    assert instance_from_dict(data).items[0].tippable is True


def test_reader_takes_the_new_key():
    data = instance_to_dict(instance(line("A", tippable=True)))
    assert instance_from_dict(data).items[0].tippable is True


def test_reader_takes_both_keys_when_they_agree_and_rejects_a_conflict():
    data = instance_to_dict(instance(line("A", tippable=True)))
    data["items"][0]["tiltable"] = True
    assert instance_from_dict(data).items[0].tippable is True
    data["items"][0]["tiltable"] = False
    with pytest.raises(ValueError, match="differ"):
        instance_from_dict(data)
