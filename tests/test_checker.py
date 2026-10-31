from pathlib import Path

import pytest

from src.checker import check, main
from src.formats import write_instance, write_solution
from src.model import ContainerType, Params
from tests.builders import BOX, PARAMS, at, instance, line, solution


def constraints(inst, sol, params=PARAMS) -> list[int]:
    return sorted({v.constraint for v in check(inst, sol, params).violations})


# --- a valid reference layout ------------------------------------------------------------------


def test_valid_layout_passes_and_reports_cost():
    inst = instance(line("A", qty=2), line("B"))
    sol = solution(at("A#1", 0.0), at("A#2", 1.1), at("B#1", 0.0, z=1.0))
    result = check(inst, sol, PARAMS)
    assert result.ok, result.violations
    assert result.cost == 1.0


# --- 1: orientation and container type ----------------------------------------------------------


def test_upright_item_may_turn_about_vertical_axis():
    inst = instance(line("A", L=2.0, W=1.0))
    assert constraints(inst, solution(at("A#1", 0.0, o="WLH"))) == []


def test_upright_item_may_not_tip_over():
    inst = instance(line("A", L=1.5, W=1.0, H=1.2))
    assert constraints(inst, solution(at("A#1", 0.0, o="LHW"))) == [1]


def test_tippable_item_may_tip_over():
    inst = instance(line("A", L=1.5, W=1.0, H=1.2, tippable=True))
    assert constraints(inst, solution(at("A#1", 0.0, o="LHW"))) == []


def test_unknown_container_type_is_violation_1():
    inst = instance(line("A"))
    assert 1 in constraints(inst, solution(at("A#1", 0.0), containers=((1, "NOPE"),)))


def test_container_listed_twice_is_violation_1():
    inst = instance(line("A"))
    sol = solution(at("A#1", 0.0), containers=((1, "BOX"), (1, "BOX")))
    assert constraints(inst, sol) == [1]


# --- 2: each item exactly once ------------------------------------------------------------------


def test_missing_item_is_violation_2():
    inst = instance(line("A", qty=2))
    assert constraints(inst, solution(at("A#1", 0.0))) == [2]


def test_item_placed_twice_is_violation_2():
    inst = instance(line("A"))
    assert constraints(inst, solution(at("A#1", 0.0), at("A#1", 5.0))) == [2]


def test_unknown_item_is_violation_2():
    inst = instance(line("A"))
    assert constraints(inst, solution(at("A#1", 0.0), at("A#2", 5.0))) == [2]


# --- 3: only open containers --------------------------------------------------------------------


def test_placement_in_container_not_open_is_violation_3():
    inst = instance(line("A", qty=2))
    assert constraints(inst, solution(at("A#1", 0.0), at("A#2", 0.0, k=2))) == [3]


def test_second_open_container_is_fine_and_costed():
    inst = instance(line("A", qty=2))
    sol = solution(at("A#1", 0.0), at("A#2", 0.0, k=2), containers=((1, "BOX"), (2, "BOX")))
    result = check(inst, sol, PARAMS)
    assert result.ok
    assert result.cost == 2.0


# --- 4: inside the container --------------------------------------------------------------------


def test_item_touching_walls_is_inside():
    inst = instance(line("A"))
    assert constraints(inst, solution(at("A#1", 9.0, y=1.0))) == []


@pytest.mark.parametrize("x, y, z", [(9.5, 0.0, 0.0), (0.0, 1.5, 0.0), (-0.1, 0.0, 0.0)])
def test_item_crossing_a_wall_is_violation_4(x, y, z):
    inst = instance(line("A"))
    assert 4 in constraints(inst, solution(at("A#1", x, y=y, z=z)))


def test_item_through_ceiling_is_violation_4():
    inst = instance(line("A", H=1.5, tiers=2), line("B", H=0.6))
    assert constraints(inst, solution(at("A#1", 0.0), at("B#1", 0.0, z=1.5))) == [4]


# --- 5: no overlap, horizontal gap >= delta -----------------------------------------------------


def test_overlap_is_violation_5():
    inst = instance(line("A", qty=2))
    assert constraints(inst, solution(at("A#1", 0.0), at("A#2", 0.5))) == [5]


def test_gap_below_delta_is_violation_5():
    inst = instance(line("A", qty=2))
    assert constraints(inst, solution(at("A#1", 0.0), at("A#2", 1.05))) == [5]


def test_gap_exactly_delta_is_fine():
    inst = instance(line("A", qty=2))
    assert constraints(inst, solution(at("A#1", 0.0), at("A#2", 1.1))) == []


def test_gap_below_delta_across_width_is_violation_5():
    inst = instance(line("A", qty=2, W=0.9))
    assert constraints(inst, solution(at("A#1", 0.0), at("A#2", 0.0, y=0.95))) == [5]


def test_stacked_items_touch_without_gap():
    inst = instance(line("A", qty=2))
    assert constraints(inst, solution(at("A#1", 0.0), at("A#2", 0.0, z=1.0))) == []


def test_items_at_different_heights_need_no_horizontal_gap():
    # C rests on A and overhangs B; B's top is below C's base, so C and B need no gap.
    inst = instance(line("A", H=1.0), line("B", H=0.5), line("C", L=1.2, H=0.5))
    sol = solution(at("A#1", 0.0), at("B#1", 1.1), at("C#1", 0.0, z=1.0))
    assert constraints(inst, sol) == []


# --- 6: container mass --------------------------------------------------------------------------


def test_mass_at_limit_is_fine():
    inst = instance(line("A", qty=2, mass=500.0))
    assert constraints(inst, solution(at("A#1", 0.0), at("A#2", 2.0))) == []


def test_mass_over_limit_is_violation_6():
    inst = instance(line("A", qty=2, mass=501.0))
    assert constraints(inst, solution(at("A#1", 0.0), at("A#2", 2.0))) == [6]


# --- 7: support ---------------------------------------------------------------------------------


def test_floating_item_is_violation_7():
    inst = instance(line("A"))
    assert constraints(inst, solution(at("A#1", 0.0, z=0.5))) == [7]


def test_overhang_within_alpha_is_fine():
    inst = instance(line("A", qty=2))
    assert constraints(inst, solution(at("A#1", 0.0), at("A#2", 0.2, z=1.0))) == []


def test_overhang_beyond_alpha_is_violation_7():
    inst = instance(line("A", qty=2))
    assert constraints(inst, solution(at("A#1", 0.0), at("A#2", 0.3, z=1.0))) == [7]


def test_support_adds_up_over_several_items():
    # C (1.0 wide) bridges A and B, 0.45 on each: 0.9 of its base supported.
    inst = instance(line("A", qty=2, L=0.5), line("C"))
    sol = solution(at("A#1", 0.0), at("A#2", 0.6), at("C#1", 0.05, z=1.0))
    assert constraints(inst, sol) == []


def test_lower_top_does_not_support():
    # B's top is below C's base, so only A supports C: 0.5 < alpha.
    inst = instance(line("A", L=0.5), line("B", L=0.4, H=0.9), line("C"))
    sol = solution(at("A#1", 0.0), at("B#1", 0.6), at("C#1", 0.0, z=1.0))
    assert constraints(inst, sol) == [7]


def test_alpha_one_requires_full_support():
    inst = instance(line("A", qty=2))
    sol = solution(at("A#1", 0.0), at("A#2", 0.1, z=1.0))
    assert constraints(inst, sol, Params(delta=0.1, alpha=1.0)) == [7]


# --- 8: stacking --------------------------------------------------------------------------------


def test_load_counts_full_mass_of_the_upward_closure():
    # C bridges A and B; D sits on C. A carries all of C and D even though it holds half of C.
    tall = ContainerType("BOX", L=10.0, W=2.0, H=3.0, door_w=2.0, door_h=2.9, max_mass=1000.0, cost=1.0)
    inst = instance(
        line("A", L=0.5, load=29.0),
        line("B", L=0.5),
        line("C", mass=20.0),
        line("D", mass=10.0),
        types=(tall,),
    )
    sol = solution(at("A#1", 0.0), at("B#1", 0.6), at("C#1", 0.05, z=1.0), at("D#1", 0.05, z=2.0))
    result = check(inst, sol, PARAMS)
    assert [(v.constraint, v.items) for v in result.violations] == [(8, ("A#1",))]


def test_load_at_limit_is_fine():
    inst = instance(line("A", load=10.0), line("B", mass=10.0))
    assert constraints(inst, solution(at("A#1", 0.0), at("B#1", 0.0, z=1.0))) == []


def test_zero_load_forbids_anything_on_top():
    inst = instance(line("A", load=0.0), line("B"))
    assert constraints(inst, solution(at("A#1", 0.0), at("B#1", 0.0, z=1.0))) == [8]


def test_no_load_limit_when_load_is_none():
    inst = instance(line("A", load=None), line("B", mass=900.0))
    assert constraints(inst, solution(at("A#1", 0.0), at("B#1", 0.0, z=1.0))) == []


def test_stack_taller_than_tiers_is_violation_8():
    # The top item allows 2 tiers but sits in a stack of 3.
    inst = instance(line("A", qty=2, H=0.6), line("B", H=0.6, tiers=2))
    sol = solution(at("A#1", 0.0), at("A#2", 0.0, z=0.6), at("B#1", 0.0, z=1.2))
    result = check(inst, sol, PARAMS)
    assert [(v.constraint, v.items) for v in result.violations] == [(8, ("B#1",))]


def test_tiers_counts_the_longest_stack_through_the_item():
    # A (tiers 2) under C; C bridges A and B, and B has a second item under it: longest stack
    # through A is A, C = 2 tiers, which is fine; through C it is B1, B2, C = 3.
    inst = instance(
        line("A", L=0.5, H=1.0, tiers=2),
        line("B", qty=2, L=0.5, H=0.5),
        line("C", tiers=3),
    )
    sol = solution(at("A#1", 0.0), at("B#1", 0.6), at("B#2", 0.6, z=0.5), at("C#1", 0.05, z=1.0))
    assert constraints(inst, sol) == []
    tight = instance(inst.items[0], inst.items[1], line("C", tiers=2))
    result = check(tight, sol, PARAMS)
    assert [(v.constraint, v.items) for v in result.violations] == [(8, ("C#1",))]


# --- 9: door ------------------------------------------------------------------------------------


def test_item_taller_than_door_is_violation_9():
    inst = instance(line("A", H=1.95))
    assert constraints(inst, solution(at("A#1", 0.0))) == [9]


def test_item_turned_to_fit_door_is_fine():
    tall = ContainerType("TALL", L=10.0, W=2.0, H=2.5, door_w=1.5, door_h=2.4, max_mass=1000.0, cost=1.0)
    inst = instance(line("A", L=1.8, W=1.0), types=(tall,))
    assert constraints(inst, solution(at("A#1", 0.0, o="LWH"), containers=((1, "TALL"),))) == []
    assert constraints(inst, solution(at("A#1", 0.0, o="WLH"), containers=((1, "TALL"),))) == [9]


# --- CLI ----------------------------------------------------------------------------------------


def test_cli_exit_code_follows_the_verdict(tmp_path: Path, capsys):
    inst = instance(line("A", qty=2))
    write_instance(tmp_path / "i.json", inst)
    write_solution(tmp_path / "ok.json", solution(at("A#1", 0.0), at("A#2", 1.1)))
    write_solution(tmp_path / "bad.json", solution(at("A#1", 0.0), at("A#2", 1.0)))
    args = ["--delta", "0.1", "--alpha", "0.8"]
    assert main([str(tmp_path / "i.json"), str(tmp_path / "ok.json"), *args]) == 0
    assert main([str(tmp_path / "i.json"), str(tmp_path / "bad.json"), *args]) == 1


def test_cli_checks_with_the_given_params_not_the_stated_ones(tmp_path: Path):
    inst = instance(line("A", qty=2))
    write_instance(tmp_path / "i.json", inst)
    write_solution(tmp_path / "s.json", solution(at("A#1", 0.0), at("A#2", 1.1)))
    assert main([str(tmp_path / "i.json"), str(tmp_path / "s.json"), "--delta", "0.2", "--alpha", "0.8"]) == 1
