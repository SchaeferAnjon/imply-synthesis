"""Lower an IMPLY/INV netlist to an executable IMPLY/FALSE program.

Input : parsed BLIF netlist (IMPLY / INV / BUF / ZERO / ONE gates, from ABC)
Output: Program = ordered FALSE/IMPLY ops on crossbar-row cells

Hardware constraints handled here:
- IMPLY(src, dst) overwrites dst. A value still needed later must never sit
  in a dst cell (dependency-aware targeting).
- NOT x is not a primitive: INV lowers to FALSE(w); IMPLY(x, w) -> w = !x.
- BUF (ABC `.barbuf` passthrough, for example an output collapsed to an input) is a
  zero-cost cell alias, with no pulse emitted.

Optimizations (optimize=True):
- negation cache: !n computed once is remembered and reused (Fabian's
  "store the inverted value" advice); INV also registers the reverse alias
  (a == !z when z = !a), so a later !z is free too.
- dead-target reuse: IMPLY gate writes straight into its b-operand's cell
  when b is dead afterwards (1 step instead of up to 5).
- cell reclamation: cells whose values are dead return to a free list.
- parallel-FALSE merging: independent FALSE resets fuse into one pulse.
- portfolio scheduling: three gate orders (topological, greedy-by-step-cost,
  greedy-by-cell-pressure) are tried and the best program kept
  (objective="steps" -> min (steps, cells); "cells" flips the key, useful to
  squeeze a circuit into a fixed-size SPICE template).

naive mode (optimize=False) = plain topological order, none of the above;
this is the baseline for sub-task (iii).
"""
from collections import Counter
from dataclasses import dataclass, field

# Program operations stay as small tuples. It is less fancy than a class, but
# the printed sequence is exactly what I want to show in the presentation.
Op = tuple  # ("FALSE", [cells]) | ("IMPLY", src, dst)


@dataclass
class Program:
    ops: list[Op]
    n_cells: int
    in_cell: dict[str, int]
    out_cell: dict[str, int]

    @property
    def steps(self) -> int:
        """Pulse count for this program."""
        return len(self.ops)


def topo_order(inputs: list[str], gates: list[tuple]) -> list[tuple]:
    """Order gates so every gate's inputs are already computed."""
    known = set(inputs)
    pending, ordered = list(gates), []
    while pending:
        rest = []
        for g in pending:
            typ, pins = g
            ready = True
            for pin_name, net_name in pins.items():
                if pin_name == "O":
                    continue
                if net_name not in known:
                    ready = False
                    break
            if ready:
                ordered.append(g)
                known.add(pins["O"])
            else:
                rest.append(g)
        if len(rest) == len(pending):
            raise RuntimeError("netlist not acyclic / undriven net")
        pending = rest
    return ordered


@dataclass
class _Core:
    """One emission pass over the netlist with a chosen gate-order strategy."""
    optimize: bool
    scheduler: str = "topo"            # "topo" | "greedy-steps" | "greedy-cells"
    ops: list[Op] = field(default_factory=list)
    val: dict[str, int] = field(default_factory=dict)   # net -> cell holding net
    neg: dict[str, int] = field(default_factory=dict)   # net -> cell holding !net
    claims: dict[int, set] = field(default_factory=dict)  # cell -> {(kind, net)}
    free: list[int] = field(default_factory=list)       # reusable cells, LIFO
    n_cells: int = 0                                   # next fresh cell id
    remaining: Counter = field(default_factory=Counter)
    protected: set = field(default_factory=set)

    # ------------------------------------------------------------- plumbing
    def alloc(self) -> int:
        # In optimized mode, prefer a dead cell over growing the row. Small
        # reminder to myself: pop() gives a cell id, not the old value in it.
        if self.optimize and self.free:
            return self.free.pop()
        c = self.n_cells
        self.n_cells += 1
        return c

    def fresh_false(self) -> int:
        """Allocate a cell and reset it to logic 0."""
        c = self.alloc()
        self.claims[c] = set()
        self.ops.append(("FALSE", [c]))
        return c

    def emit_imply(self, src: int, dst: int) -> None:
        if src == dst:
            # IMPLY(x, x) always gives 1, so it is almost certainly a bad alias
            # in my cell bookkeeping, not a useful pulse.
            raise ValueError(f"IMPLY src==dst cell {src} (cell alias bug?)")
        self.ops.append(("IMPLY", src, dst))

    def live_vals(self, cell: int, exclude: str | None = None) -> list[str]:
        """Return still-needed plain values stored in a cell."""
        result = []
        for k, n in self.claims.get(cell, ()):
            if k != "val":
                continue
            if n == exclude:
                continue
            if self.remaining[n] > 0 or n in self.protected:
                result.append(n)
        return result

    def dec(self, net: str) -> None:
        self.remaining[net] -= 1
        cell = self.val.get(net)
        if cell is not None:
            self.maybe_reclaim(cell)

    def maybe_reclaim(self, cell: int) -> None:
        # A cell can go back to the free list only after every useful plain
        # value in it has died. Cached negations die with the cell too.
        if not self.optimize or cell in self.free or self.live_vals(cell):
            return
        for k, n in list(self.claims.get(cell, ())):
            if k == "val" and self.val.get(n) == cell:
                del self.val[n]
            if k == "neg" and self.neg.get(n) == cell:
                del self.neg[n]
        self.claims[cell] = set()
        self.free.append(cell)

    def retarget(self, cell: int, out: str) -> None:
        """Record that cell now holds out after a destructive write."""
        for k, n in list(self.claims.get(cell, ())):
            if k == "val" and self.val.get(n) == cell:
                del self.val[n]
            if k == "neg" and self.neg.get(n) == cell:
                del self.neg[n]
        self.claims[cell] = {("val", out)}
        self.val[out] = cell

    def ensure_neg(self, net: str) -> int:
        """Return a cell holding !net, creating it if needed."""
        if self.optimize and net in self.neg:
            return self.neg[net]
        w = self.fresh_false()
        self.emit_imply(self.val[net], w)
        if self.optimize:
            self.neg[net] = w
            self.claims[w].add(("neg", net))
        return w

    # ---------------------------------------------------------------- gates
    def destructible(self, b: str) -> bool:
        # Safe in-place IMPLY case: b is not an output, this is its last use,
        # and no other still-live value is sharing that cell.
        if not self.optimize:
            return False
        if b in self.protected:
            return False
        if self.remaining[b] != 1:
            return False
        if self.live_vals(self.val[b], exclude=b):
            return False
        return True

    def do_inv(self, pins: dict) -> None:
        a, z = pins["a"], pins["O"]
        if self.optimize and a in self.neg:        # cached inverse: no pulse
            c = self.neg[a]
        else:                                      # FALSE + IMPLY: 2 steps
            c = self.fresh_false()
            self.emit_imply(self.val[a], c)
            if self.optimize:
                self.neg[a] = c
                self.claims[c].add(("neg", a))
        self.claims[c].add(("val", z))
        self.val[z] = c
        if self.optimize:                  # reverse alias: if z = !a, then a = !z
            ca = self.val.get(a)
            if ca is not None and z not in self.neg:
                self.neg[z] = ca
                self.claims[ca].add(("neg", z))
        self.dec(a)

    def do_imply(self, pins: dict) -> None:
        a, b, z = pins["a"], pins["b"], pins["O"]
        assert a != b, "degenerate IMPLY(x,x) not expected from ABC"
        if self.destructible(b):                   # 1 step, in-place
            cb = self.val[b]
            self.emit_imply(self.val[a], cb)
            self.retarget(cb, z)
        else:                                      # via !b -> !a (1-5 steps)
            nb = self.ensure_neg(b)
            t = None
            if self.optimize and a in self.neg and not self.live_vals(self.neg[a]):
                t = self.neg[a]                     # consume cached !a as target
                del self.neg[a]
            if t is None:
                t = self.fresh_false()
                self.emit_imply(self.val[a], t)     # t = !a
            self.emit_imply(nb, t)                  # t = b | !a = z
            self.retarget(t, z)
        self.dec(a)
        self.dec(b)

    def do_buf(self, pins: dict) -> None:
        """ABC passthrough: just give the same cell another net name."""
        a, z = pins["a"], pins["O"]
        c = self.val[a]
        self.claims[c].add(("val", z))
        self.val[z] = c
        self.dec(a)

    def do_const(self, typ: str, pins: dict) -> None:
        z = pins["O"]
        c = self.fresh_false()                     # ZERO is just a reset cell.
        if typ == "ONE":
            zc = self.fresh_false()
            self.emit_imply(zc, c)                  # c = !0 | 0 = 1
            if self.optimize:
                self.free.append(zc)
        self.claims[c].add(("val", z))
        self.val[z] = c

    def emit_gate(self, typ: str, pins: dict) -> None:
        if typ == "INV":
            self.do_inv(pins)
        elif typ == "IMPLY":
            self.do_imply(pins)
        elif typ == "BUF":
            self.do_buf(pins)
        elif typ in ("ZERO", "ONE"):
            self.do_const(typ, pins)
        else:
            raise ValueError(f"unexpected gate {typ}")

    # ------------------------------------------------------------ scheduling
    def score(self, typ: str, pins: dict) -> int:
        """Greedy score for the current machine state."""
        dying = 0
        for pin_name, net_name in pins.items():
            if pin_name != "O" and self.remaining[net_name] == 1:
                dying += 1
        if typ == "BUF":
            s = 95                                  # free alias
        elif typ == "INV":
            if pins["a"] in self.neg:
                s = 90
            else:
                s = 10
        elif typ == "IMPLY":
            a, b = pins["a"], pins["b"]
            if self.destructible(b):
                s = 60
            else:
                s = 0
                if b in self.neg:
                    s += 20
                if a in self.neg and not self.live_vals(self.neg[a]):
                    s += 20
        else:
            s = 0
        if self.scheduler == "greedy-cells":
            return 50 * dying + s
        return s + 5 * dying

    def run(self, inputs: list[str], outputs: list[str],
            gates: list[tuple]) -> Program:
        self.protected = set(outputs)
        # remaining tells us whether overwriting a net is safe. It is the small
        # bit of bookkeeping that keeps IMPLY's destructive target sane.
        for _, pins in gates:
            for k, v in pins.items():
                if k != "O":
                    self.remaining[v] += 1
        in_cell = {}
        for net in inputs:
            c = self.alloc()
            self.claims[c] = {("val", net)}
            self.val[net] = c
            in_cell[net] = c

        if self.scheduler == "topo" or not self.optimize:
            for typ, pins in topo_order(inputs, gates):
                self.emit_gate(typ, pins)
        else:
            computed = set(inputs)
            pending = list(gates)
            while pending:
                ready = []
                for gate in pending:
                    gate_ready = True
                    for pin_name, net_name in gate[1].items():
                        if pin_name == "O":
                            continue
                        if net_name not in computed:
                            gate_ready = False
                            break
                    if gate_ready:
                        ready.append(gate)

                best = ready[0]
                best_score = self.score(*best)
                for gate in ready[1:]:
                    gate_score = self.score(*gate)
                    if gate_score > best_score:
                        best = gate
                        best_score = gate_score
                self.emit_gate(*best)
                computed.add(best[1]["O"])
                pending.remove(best)

        if self.optimize:
            ops = merge_false(self.ops)
        else:
            ops = self.ops
        out_cell = {}
        for out_name in outputs:
            out_cell[out_name] = self.val[out_name]
        return Program(ops, self.n_cells, in_cell, out_cell)


class Sequencer:
    """Public API wrapper around the scheduling portfolio."""

    def __init__(self, optimize: bool, objective: str = "steps"):
        self.optimize = optimize
        self.objective = objective

    def run(self, inputs: list[str], outputs: list[str],
            gates: list[tuple]) -> Program:
        if not self.optimize:
            return _Core(False).run(inputs, outputs, gates)
        candidates = []
        for sched in ("topo", "greedy-steps", "greedy-cells"):
            program = _Core(True, sched).run(inputs, outputs, gates)
            candidates.append(program)
        if self.objective == "cells":
            best = candidates[0]
            for program in candidates[1:]:
                if (program.n_cells, program.steps) < (best.n_cells, best.steps):
                    best = program
            return best
        best = candidates[0]
        for program in candidates[1:]:
            if (program.steps, program.n_cells) < (best.steps, best.n_cells):
                best = program
        return best


def merge_false(ops: list[Op]) -> list[Op]:
    """Fuse independent FALSE resets into one parallel pulse."""
    out: list[Op] = []
    for op in ops:
        if op[0] != "FALSE":
            out.append(op)
            continue
        cells = op[1]
        j = len(out) - 1
        merged = False
        while j >= 0:
            o = out[j]
            if o[0] == "FALSE":
                overlap = False
                for c in cells:
                    if c in o[1]:
                        overlap = True
                        break
                if not overlap:
                    out[j] = ("FALSE", o[1] + cells)
                    merged = True
                break
            touched = False
            for c in cells:
                if c == o[1] or c == o[2]:
                    touched = True
                    break
            if touched:
                break
            j -= 1
        if not merged:
            out.append(op)
    return out
