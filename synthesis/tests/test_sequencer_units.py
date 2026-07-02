"""Unit tests for the sequencer pieces that are easiest to break."""
import pytest

from sequencer import Program, Sequencer, merge_false, topo_order


# ------------------------------------------------------------- merge_false
def test_merge_false_fuses_independent_resets() -> None:
    # Two independent resets can share one physical FALSE pulse.
    assert merge_false([("FALSE", [0]), ("FALSE", [1])]) == [("FALSE", [0, 1])]
    # This also works across an IMPLY that touches unrelated cells.
    ops = [("FALSE", [0]), ("IMPLY", 2, 3), ("FALSE", [1])]
    assert merge_false(ops) == [("FALSE", [0, 1]), ("IMPLY", 2, 3)]


def test_merge_false_blocked_by_intervening_op() -> None:
    # FALSE(1) must stay after the IMPLY that writes cell 1. Moving it earlier
    # would erase the value we just computed.
    blocked_dst = [("FALSE", [0]), ("IMPLY", 0, 1), ("FALSE", [1])]
    assert merge_false(blocked_dst) == blocked_dst
    # Same idea when the IMPLY only reads that cell as its source operand.
    blocked_src = [("FALSE", [2]), ("IMPLY", 1, 3), ("FALSE", [1])]
    assert merge_false(blocked_src) == blocked_src


def test_merge_false_never_duplicates_cells_in_one_pulse() -> None:
    ops = [("FALSE", [0, 1]), ("FALSE", [1, 2]), ("FALSE", [3])]
    out = merge_false(ops)
    for op in out:
        if op[0] == "FALSE":
            assert len(op[1]) == len(set(op[1])), f"duplicate cells in {op}"
    # The merge may move pulses around, but it must not lose a reset request.
    flat = []
    for op in out:
        if op[0] == "FALSE":
            for cell in op[1]:
                flat.append(cell)
    assert sorted(flat) == [0, 1, 1, 2, 3]


# -------------------------------------------------------------- topo_order
def test_topo_order_raises_on_cycle() -> None:
    gates = [("INV", {"a": "n2", "O": "n1"}),
             ("INV", {"a": "n1", "O": "n2"})]
    with pytest.raises(RuntimeError):
        topo_order(["a"], gates)


def test_topo_order_diamond() -> None:
    top = ("INV", {"a": "a", "O": "n1"})
    left = ("INV", {"a": "n1", "O": "n2"})
    right = ("INV", {"a": "n1", "O": "n3"})
    bottom = ("IMPLY", {"a": "n2", "b": "n3", "O": "z"})
    ordered = topo_order(["a"], [bottom, right, left, top])
    assert len(ordered) == 4
    known = {"a"}
    for typ, pins in ordered:
        for pin, net in pins.items():
            if pin != "O":
                assert net in known, f"{typ} consumes {net} before it exists"
        known.add(pins["O"])
    assert ordered[0] is top and ordered[-1] is bottom


# --------------------------------------------------------- negation cache
def test_negation_cache_second_inv_is_free() -> None:
    single = Sequencer(optimize=True).run(
        ["a"], ["n1"], [("INV", {"a": "a", "O": "n1"})])
    double = Sequencer(optimize=True).run(
        ["a"], ["n1", "n2"],
        [("INV", {"a": "a", "O": "n1"}), ("INV", {"a": "a", "O": "n2"})])
    assert single.steps == 2                      # FALSE + IMPLY baseline
    assert double.steps == single.steps           # second INV reuses the cache
    assert double.out_cell["n1"] == double.out_cell["n2"]  # same cell alias


def test_primitive_zero_imply_inverse_uses_reverse_alias() -> None:
    gates = [
        ("ZERO", {"O": "z0"}),
        ("IMPLY", {"a": "a", "b": "z0", "O": "not_a"}),
        ("ZERO", {"O": "z1"}),
        ("IMPLY", {"a": "not_a", "b": "z1", "O": "a_again"}),
    ]

    prog: Program = Sequencer(optimize=True).run(["a"], ["a_again"], gates)

    assert prog.steps == 2
    assert prog.out_cell["a_again"] == prog.in_cell["a"]


# ------------------------------------------------------ destructive target
def test_destructive_target_single_imply_in_place() -> None:
    prog: Program = Sequencer(optimize=True).run(
        ["a", "b"], ["z"], [("IMPLY", {"a": "a", "b": "b", "O": "z"})])
    assert prog.steps == 1                        # exactly one pulse
    assert prog.ops == [("IMPLY", prog.in_cell["a"], prog.in_cell["b"])]
    assert prog.out_cell["z"] == prog.in_cell["b"]  # z lands in b's cell
