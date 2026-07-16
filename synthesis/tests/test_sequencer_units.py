"""Unit tests for the sequencer pieces that are easiest to break."""
import pytest

from imply_sim import CrossbarRow
from sequencer import Program, Sequencer, pack_false, topo_order


# -------------------------------------------------------------- pack_false
def test_pack_false_fuses_independent_resets() -> None:
    # Two independent resets can share one physical FALSE pulse.
    assert pack_false([("FALSE", [0]), ("FALSE", [1])]) == [("FALSE", [0, 1])]
    # This also works across an IMPLY that touches unrelated cells.
    ops = [("FALSE", [0]), ("IMPLY", 2, 3), ("FALSE", [1])]
    assert pack_false(ops) == [("FALSE", [0, 1]), ("IMPLY", 2, 3)]


def test_pack_false_blocked_by_intervening_op() -> None:
    # FALSE(1) must stay after the IMPLY that writes cell 1, and FALSE(0)
    # before the IMPLY that reads cell 0: the windows cannot overlap.
    blocked_dst = [("FALSE", [0]), ("IMPLY", 0, 1), ("FALSE", [1])]
    assert pack_false(blocked_dst) == blocked_dst
    # Same when the blocking read is the src operand of the IMPLY.
    blocked_src = [("FALSE", [2]), ("IMPLY", 2, 3), ("FALSE", [3])]
    assert pack_false(blocked_src) == blocked_src
    # But an untouched cell's reset may legally move later to share a pulse.
    movable = [("FALSE", [2]), ("IMPLY", 1, 3), ("FALSE", [1])]
    assert pack_false(movable) == [("IMPLY", 1, 3), ("FALSE", [1, 2])]


def test_pack_false_moves_reset_later_to_share_a_pulse() -> None:
    # Cell 5's reset may fire any time before IMPLY 5->3, and cell 7's reset
    # any time after IMPLY 1->7: the windows overlap between the two IMPLYs,
    # so one shared pulse suffices. A backward-only merge cannot see this.
    ops = [("FALSE", [5]), ("IMPLY", 1, 7), ("FALSE", [7]), ("IMPLY", 5, 3)]
    assert pack_false(ops) == [
        ("IMPLY", 1, 7), ("FALSE", [5, 7]), ("IMPLY", 5, 3)]


def test_pack_false_splits_pulse_per_cell() -> None:
    # Cell 5 can move to the front while cell 1 stays blocked: the pulse
    # splits and no reset request is lost.
    ops = [("FALSE", [0]), ("IMPLY", 0, 1), ("FALSE", [1, 5])]
    out = pack_false(ops)
    assert out == [("FALSE", [0, 5]), ("IMPLY", 0, 1), ("FALSE", [1])]


def test_pack_false_coincident_resets_of_same_cell_collapse() -> None:
    # Nothing touches cell 1 between its two reset requests, so a single
    # reset is equivalent; cells never repeat inside one pulse.
    ops = [("FALSE", [0, 1]), ("FALSE", [1, 2]), ("FALSE", [3])]
    assert pack_false(ops) == [("FALSE", [0, 1, 2, 3])]


def test_pack_false_separated_resets_of_same_cell_stay_ordered() -> None:
    ops = [("FALSE", [0]), ("IMPLY", 0, 2), ("FALSE", [0])]
    assert pack_false(ops) == ops


# --------------------------------------------------------- preserve inputs
def _run_program(prog: Program, values: dict[str, int]) -> CrossbarRow:
    row = CrossbarRow(cells=[0] * prog.n_cells)
    for net, cell in prog.in_cell.items():
        row.cells[cell] = values[net]
    for op in prog.ops:
        if op[0] == "FALSE":
            row.false_reset(op[1])
        else:
            row.imply(op[1], op[2])
    return row


def test_preserve_inputs_keeps_operands_readable() -> None:
    gates = [("IMPLY", {"a": "a", "b": "b", "O": "z"})]
    prog = Sequencer(optimize=True, preserve_inputs=True).run(
        ["a", "b"], ["z"], gates)
    for a in (0, 1):
        for b in (0, 1):
            row = _run_program(prog, {"a": a, "b": b})
            assert row.cells[prog.out_cell["z"]] == (1 - a) | b
            assert row.cells[prog.in_cell["a"]] == a
            assert row.cells[prog.in_cell["b"]] == b
    # The output must not have landed on an input cell.
    assert prog.out_cell["z"] not in prog.in_cell.values()


# ------------------------------------------------------ no cell budget
def test_no_budget_single_upfront_false_pulse() -> None:
    # Without a cell budget every reset targets a fresh cell, so all resets
    # pack into one FALSE pulse before the first IMPLY.
    gates = [
        ("INV", {"a": "a", "O": "na"}),
        ("INV", {"a": "b", "O": "nb"}),
        ("IMPLY", {"a": "na", "b": "nb", "O": "z"}),
    ]
    prog = Sequencer(optimize=True, preserve_inputs=False).run(
        ["a", "b"], ["z"], gates)
    falses = [op for op in prog.ops if op[0] == "FALSE"]
    assert len(falses) == 1
    assert prog.ops[0] is falses[0]
    for x in (0, 1):
        for y in (0, 1):
            row = _run_program(prog, {"a": x, "b": y})
            # z = IMPLY(!a, !b) = a | !b
            assert row.cells[prog.out_cell["z"]] == x | (1 - y)


# --------------------------------------------------------- max_cells budget
def test_max_cells_budget_caps_row_width() -> None:
    # A tight budget forces cell reuse (fewer cells); the result must still
    # be correct on every input combination.
    gates = [
        ("INV", {"a": "a", "O": "na"}),
        ("INV", {"a": "b", "O": "nb"}),
        ("IMPLY", {"a": "na", "b": "nb", "O": "z"}),
    ]
    wide = Sequencer(optimize=True, preserve_inputs=False).run(
        ["a", "b"], ["z"], gates)
    tight = Sequencer(optimize=True, preserve_inputs=False, max_cells=0).run(
        ["a", "b"], ["z"], gates)
    assert tight.n_cells <= wide.n_cells
    for x in (0, 1):
        for y in (0, 1):
            row = _run_program(tight, {"a": x, "b": y})
            assert row.cells[tight.out_cell["z"]] == x | (1 - y)


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
    # In-place overwrite of input b requires preservation to be off.
    prog: Program = Sequencer(optimize=True, preserve_inputs=False).run(
        ["a", "b"], ["z"], [("IMPLY", {"a": "a", "b": "b", "O": "z"})])
    assert prog.steps == 1                        # exactly one pulse
    assert prog.ops == [("IMPLY", prog.in_cell["a"], prog.in_cell["b"])]
    assert prog.out_cell["z"] == prog.in_cell["b"]  # z lands in b's cell
