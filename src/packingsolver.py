"""PackingSolver (`packingsolver3d`) <-> repo conversion, shared by `scripts.packingsolver_*` and
E5's PackingSolver variants (`src.engines.e5.ps`).

PackingSolver works in integers: lengths here are metres times `unit` (100 for cm, 1000 for mm), rounded to the nearest
integer. Importing this module never imports `packingsolver3d`; callers load it with `import_packingsolver` and pass
the module in. The wheel is not in `requirements.txt` (install it in a separate venv).
"""
from __future__ import annotations

from typing import Any

from src.model import ALL_ORIENTATIONS, Instance, Params, Placement, Solution, UsedContainer, item_id

# PackingSolver's rotation names list which item axis lies along the bin's x, y, z, as the repo's orientation
# codes do (item x, y, z = L, W, H); checked on packingsolver3d 0.0.5 by placing a 2 x 3 x 5 item alone.
ROTATION_OF_CODE: dict[str, str] = {code: code.translate(str.maketrans("LWH", "XYZ")) for code in ALL_ORIENTATIONS}
CODE_OF_ROTATION: dict[str, str] = {rotation: code for code, rotation in ROTATION_OF_CODE.items()}


class PackingSolverMissing(ImportError):
    """`packingsolver3d` is not installed."""


def to_int(metres: float, unit: int) -> int:
    """`metres` in integer units of 1/`unit` m, rounded to the nearest."""
    return round(metres * unit)


def import_packingsolver() -> Any:
    """The `packingsolver3d` module, or `PackingSolverMissing` saying how to install it."""
    try:
        import packingsolver3d
    except ImportError as error:
        raise PackingSolverMissing(
            f"packingsolver3d is not installed ({error}); install it in a separate venv: "
            "pip install -r requirements.txt packingsolver3d==0.0.5"
        ) from error
    return packingsolver3d


def code_of(line_dims: dict[str, int], placed: tuple[int, int, int], allowed: tuple[str, ...],
            rotation: str | None) -> str:
    """The orientation code giving `placed` extents: the solver's own rotation when it does, else the first allowed
    code that does, else any code that does (the checker then rejects it as not allowed)."""
    def fits(code: str) -> bool:
        return tuple(line_dims[d] for d in code) == placed

    codes = [c for c in ALL_ORIENTATIONS if fits(c)]
    if not codes:
        raise ValueError(f"placed extents {placed} match no orientation of {line_dims}")
    if rotation in CODE_OF_ROTATION and CODE_OF_ROTATION[rotation] in codes:
        return CODE_OF_ROTATION[rotation]
    return next((c for c in codes if c in allowed), codes[0])


def solution_from_bins(instance: Instance, bins: list[dict[str, Any]], params: Params, unit: int = 100) -> Solution:
    """A repo solution from PackingSolver bins as `Result.to_json()` writes them: per bin `bin_type_id` (index into
    `instance.container_types`, 0 when absent), `copies` and `placements` of `item_type_id` (index into
    `instance.items`), integer `x y z` (inner-left-bottom corner) and `lx ly lz` (extents after rotation) in
    1/`unit` m, `rotation` name. A bin with `copies = n` opens n containers with the same layout; item copies get
    ids `<line>#1..qty` in placement order."""
    dims = [{"L": to_int(line.L, unit), "W": to_int(line.W, unit), "H": to_int(line.H, unit)}
            for line in instance.items]
    counters = [0] * len(instance.items)
    containers: list[UsedContainer] = []
    placements: list[Placement] = []
    for packed in bins:
        ctype = instance.container_types[packed.get("bin_type_id", 0)]
        layout = []
        for p in packed["placements"]:
            t = p["item_type_id"]
            code = code_of(dims[t], (p["lx"], p["ly"], p["lz"]), instance.items[t].allowed, p.get("rotation"))
            layout.append((t, p["x"] / unit, p["y"] / unit, p["z"] / unit, code))
        for _ in range(packed.get("copies", 1)):
            k = len(containers) + 1
            containers.append(UsedContainer(k=k, type=ctype.id))
            for t, x, y, z, code in layout:
                counters[t] += 1
                placements.append(Placement(item=item_id(instance.items[t].id, counters[t]), k=k, x=x, y=y, z=z,
                                            o=code))
    return Solution(instance=instance.name, params=params, containers=containers, placements=placements)
