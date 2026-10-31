"""Tests for E1's column building: load, tiers, height,
container mass and footprint containment are enforced inside every column."""
from __future__ import annotations

from src.engines.base import expand_pieces
from src.engines.e1.columns import Column, build_columns
from src.engines.e1.orientation import base_orientation
from src.model import ContainerType
from tests.builders import BOX, instance, line


def _columns(*lines, ctype: ContainerType = BOX) -> list[Column]:
    pieces = expand_pieces(instance(*lines, types=(ctype,)))
    entries = [(p, base_orientation(p, ctype)) for p in pieces]
    return build_columns(entries, ctype)


def _sizes(columns: list[Column]) -> list[int]:
    return sorted((len(c.stack) for c in columns), reverse=True)


def test_load_stops_a_column_once_a_lower_piece_would_carry_more_than_its_load():
    # 100 kg on the bottom piece is within its 150 kg load; a third piece would put 200 kg on it.
    assert _sizes(_columns(line("A", qty=3, mass=100.0, load=150.0, H=0.5))) == [2, 1]


def test_load_zero_means_nothing_goes_on_top():
    assert _sizes(_columns(line("A", qty=3, load=0.0, H=0.5))) == [1, 1, 1]


def test_tiers_cap_the_number_of_pieces_in_a_column():
    assert _sizes(_columns(line("A", qty=5, tiers=3, H=0.3))) == [3, 2]


def test_the_smallest_tiers_in_the_column_governs():
    # A (tiers 5) at the bottom, B (tiers 2) on it: nothing further may go on, whatever A allows.
    cols = _columns(line("A", qty=1, L=1.5, W=1.5, H=0.3, tiers=5), line("B", qty=3, H=0.3, tiers=2))
    assert all(len(c.stack) <= 2 for c in cols)
    assert all(
        len(c.stack) <= min(p.tiers for p, _, _ in c.stack) for c in cols
    )


def test_column_height_stays_within_the_container():
    cols = _columns(line("A", qty=3, H=0.7))  # BOX.H = 2.0: two fit (1.4), three do not (2.1)
    assert _sizes(cols) == [2, 1]
    assert all(c.height <= BOX.H + 1e-9 for c in cols)


def test_column_mass_stays_within_the_container_mass_limit():
    light = ContainerType(id="LIGHT", L=10.0, W=2.0, H=2.0, door_w=2.0, door_h=1.9, max_mass=25.0, cost=1.0)
    cols = _columns(line("A", qty=5, mass=10.0, H=0.3), ctype=light)
    assert all(c.mass <= 25.0 for c in cols)
    assert _sizes(cols) == [2, 2, 1]


def test_a_piece_only_goes_on_a_top_face_that_contains_its_base():
    # 1.2 x 0.8 has less area than 1 x 1 but is longer, so it cannot sit inside it.
    cols = _columns(line("A", qty=1, L=1.0, W=1.0, H=0.5), line("B", qty=1, L=1.2, W=0.8, H=0.5))
    assert _sizes(cols) == [1, 1]


def test_a_piece_turns_90_degrees_to_fit_inside_the_top_face():
    # B is 0.8 x 1.4; turned, it lies inside A's 1.5 x 1.0 top face.
    cols = _columns(line("A", qty=1, L=1.5, W=1.0, H=0.5), line("B", qty=1, L=0.8, W=1.4, H=0.5))
    assert _sizes(cols) == [2]
    (col,) = cols
    (_, bottom_code, _), (_, top_code, _) = col.stack
    assert bottom_code == "LWH" and top_code == "WLH"


def test_every_piece_sits_inside_the_one_below_at_the_right_height():
    cols = _columns(
        line("A", qty=2, L=1.8, W=1.5, H=0.4),
        line("B", qty=3, L=1.2, W=1.0, H=0.3),
        line("C", qty=4, L=0.5, W=0.9, H=0.2),
    )
    for c in cols:
        z = 0.0
        prev = (c.fx, c.fy)
        for piece, code, pz in c.stack:
            l, w, h = piece.dims(code)
            assert abs(pz - z) < 1e-9
            assert l <= prev[0] + 1e-9 and w <= prev[1] + 1e-9
            prev, z = (l, w), z + h


def test_among_valid_columns_the_smallest_top_face_wins():
    # A (1.5 tall) and B (0.6) cannot stack (2.1 > 2.0), so both start columns; C fits on either
    # and must go on B, the smaller top face.
    cols = _columns(
        line("A", qty=1, L=1.5, W=1.5, H=1.5),
        line("B", qty=1, L=1.0, W=1.0, H=0.6),
        line("C", qty=1, L=0.4, W=0.4, H=0.3),
    )
    by_bottom = {c.stack[0][0].item: [p.item for p, _, _ in c.stack] for c in cols}
    assert by_bottom == {"A#1": ["A#1"], "B#1": ["B#1", "C#1"]}


def test_columns_come_out_largest_volume_first():
    cols = _columns(line("A", qty=1, L=0.5, W=0.5, H=0.5, tiers=1), line("B", qty=1, L=1.0, W=1.0, H=1.0, tiers=1))
    assert [c.stack[0][0].item for c in cols] == ["B#1", "A#1"]
