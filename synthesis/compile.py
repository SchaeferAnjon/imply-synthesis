#!/usr/bin/env python3
"""Compile one combinational circuit to an IMPLY/FALSE sequence.

Usage:
    python3 compile.py <circuit.v | .blif | .bench> [-o out.seq.txt]

This is the file I use for demos. It runs the same front end as run_synth.sh,
but only for one input circuit, and then asks ABC `cec` to check equivalence at
two points. That avoids pretending that exhaustive simulation scales forever.

    input --yosys--> pre.blif --ABC portfolio--> mapped.blif (adapter netlist)
                        |                              |
                        +======== cec (formal) ========+
    mapped.blif --ZERO/IMPLY dependency graph--> primitive_logic.blif
                        |                              |
                        +======== cec (formal) ========+
    primitive graph --Sequencer--> program --SSA-to-BLIF--> prog_{opt,naive}.blif
                        |                              |
                        +======== cec (formal) ========+

There is also a small simulator sanity check on CrossbarRow. For small circuits
it is exhaustive; for wider inputs it uses a fixed random seed so the run is
repeatable.

Scope: combinational circuits (Project 9). Sequential input is rejected with
a clear message instead of a crash.
"""
import argparse
import random
import subprocess
import sys
from itertools import product
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))

from imply_sim import CrossbarRow
from dependency_graph import build_dependency_graph, expand_to_primitives
from sequencer import Program, Sequencer
from verify_netlist import eval_netlist, parse_blif

ABC_SCRIPTS = [
    "strash; dc2; map -a",
    "strash; balance; rewrite; refactor; balance; rewrite; rewrite -z; "
    "balance; refactor -z; rewrite -z; balance; dch -f; map -a",
    "strash; dc2; dch -f; map -a",
]
IMPLY_CUBES = ["0- 1", "-1 1"]          # O = !a + b


def count_gates(gates: list[tuple], gate_type: str) -> int:
    count = 0
    for typ, _ in gates:
        if typ == gate_type:
            count += 1
    return count


def mapping_cost(gates: list[tuple]) -> int:
    # This is only an estimate before sequencing. INV costs 2 because it later
    # becomes FALSE + IMPLY.
    return count_gates(gates, "IMPLY") + 2 * count_gates(gates, "INV")


def run(cmd: list[str], cwd: Path) -> str:
    r = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"{cmd[0]} failed:\n{r.stderr or r.stdout}")
    return r.stdout


def to_pre_blif(src: Path, work: Path) -> Path:
    """Convert the input file to pre.blif, before IMPLY technology mapping."""
    pre = work / "pre.blif"
    if src.suffix == ".v":
        run(["yosys", "-q", "-p",
             f"read_verilog {src.name}; hierarchy -auto-top; flatten; proc; "
             f"opt; techmap; opt; write_blif pre.blif"], cwd=work)
    elif src.suffix == ".bench":
        run(["yosys-abc", "-c",
             f"read_bench {src.name}; strash; write_blif pre.blif"], cwd=work)
    elif src.suffix == ".blif":
        pre.write_text((work / src.name).read_text())
    else:
        sys.exit(f"unsupported input format: {src.suffix} (.v/.blif/.bench)")
    text = pre.read_text()
    if ".latch" in text:
        sys.exit("ERROR: sequential circuit detected (.latch). Project 9 "
                 "scope is combinational logic only; remove clocked state "
                 "or extract the combinational core.")
    return pre


def abc_portfolio(work: Path) -> Path:
    """pre.blif -> mapped.blif using the best of 3 ABC scripts."""
    best_cost, best = None, None
    for i, script in enumerate(ABC_SCRIPTS):
        out = work / f"mapped_{i}.blif"
        run(["yosys-abc", "-c",
             f"read_blif pre.blif; read_genlib abc_imply.genlib; {script}; "
             f"write_blif {out.name}"], cwd=work)
        _, _, gates = parse_blif(out)
        cost = mapping_cost(gates)
        if best_cost is None or cost < best_cost:
            best_cost, best = cost, out
    mapped = work / "mapped.blif"
    mapped.write_text(best.read_text())
    return mapped


def gates_to_blif(model: str, inputs: list[str], outputs: list[str],
                  gates: list[tuple]) -> str:
    """Mapped netlist -> plain BLIF, so ABC can compare it with `cec`."""
    L = [f".model {model}", ".inputs " + " ".join(inputs),
         ".outputs " + " ".join(outputs)]
    for typ, p in gates:
        if typ == "IMPLY":
            L += [f".names {p['a']} {p['b']} {p['O']}"] + IMPLY_CUBES
        elif typ == "INV":
            L += [f".names {p['a']} {p['O']}", "0 1"]
        elif typ == "BUF":
            L += [f".names {p['a']} {p['O']}", "1 1"]
        elif typ == "ZERO":
            L += [f".names {p['O']}"]
        elif typ == "ONE":
            L += [f".names {p['O']}", "1"]
        else:
            raise ValueError(typ)
    return "\n".join(L) + "\n.end\n"


def program_to_blif(model: str, prog: Program, inputs: list[str],
                    outputs: list[str]) -> str:
    """IMPLY/FALSE program -> SSA-style BLIF.

    The SSA part matters: one physical cell can be written many times, but in a
    logic netlist every version needs a fresh name. Otherwise `cec` would compare
    the wrong circuit.
    """
    cur = {}
    ver = {}
    for net, cell in prog.in_cell.items():
        cur[cell] = net
        ver[cell] = 0
    L = [f".model {model}", ".inputs " + " ".join(inputs),
         ".outputs " + " ".join(outputs)]

    def bump(c: int) -> str:
        ver[c] = ver.get(c, 0) + 1
        cur[c] = f"c{c}v{ver[c]}"
        return cur[c]

    for op in prog.ops:
        if op[0] == "FALSE":
            for c in op[1]:
                L.append(f".names {bump(c)}")        # no cubes means const 0
        else:
            _, s, d = op
            a, b = cur[s], cur[d]
            L += [f".names {a} {b} {bump(d)}"] + IMPLY_CUBES
    for o in outputs:
        L += [f".names {cur[prog.out_cell[o]]} {o}", "1 1"]
    return "\n".join(L) + "\n.end\n"


def cec(work: Path, f1: str, f2: str) -> bool:
    out = run(["yosys-abc", "-c", f"cec {f1} {f2}"], cwd=work)
    if "Networks are equivalent" in out:
        return True
    if "NOT EQUIVALENT" in out.upper():
        return False
    raise RuntimeError(f"cec inconclusive:\n{out}")


def run_program(prog: Program, env: dict[str, int]) -> tuple[dict[str, int], int]:
    """Execute a generated IMPLY/FALSE program on the logic-level simulator."""
    cells = [0] * prog.n_cells
    for net, c in prog.in_cell.items():
        cells[c] = env[net]
    row = CrossbarRow(cells=cells)
    for op in prog.ops:
        if op[0] == "FALSE":
            row.false_reset(op[1])
        else:
            row.imply(op[1], op[2])
    result = {}
    for out_name, cell in prog.out_cell.items():
        result[out_name] = row.cells[cell]
    return result, row.steps


def sim_sanity(prog: Program, inputs: list[str], outputs: list[str],
               gates: list[tuple]) -> tuple[bool, int]:
    if len(inputs) <= 12:
        vectors = list(product((0, 1), repeat=len(inputs)))
    else:
        rng = random.Random(20260611)
        vectors = []
        for _ in range(1000):
            bits = []
            for _name in inputs:
                bits.append(rng.randint(0, 1))
            vectors.append(tuple(bits))
    for bits in vectors:
        env = {}
        for i, name in enumerate(inputs):
            env[name] = bits[i]
        got, _ = run_program(prog, env)
        want = eval_netlist(inputs, gates, env)
        for out_name in outputs:
            if got[out_name] != want[out_name]:
                return False, len(vectors)
    return True, len(vectors)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("circuit", type=Path)
    ap.add_argument("-o", "--out", type=Path, default=None,
                    help="sequence output file (default: <work>/<name>.seq.txt)")
    ap.add_argument("--preserve-inputs", action="store_true",
                    help="keep every input cell readable at the end of the "
                         "optimized sequence (inputs are never overwritten)")
    ap.add_argument("--unlimited-cells", action="store_true",
                    help="never reuse a cell: all resets pack into a single "
                         "upfront FALSE pulse (fewest steps, widest row)")
    args = ap.parse_args()
    src = args.circuit.resolve()
    if not src.exists():
        sys.exit(f"no such file: {src}")
    name = src.stem
    work = HERE / "compiled" / name
    work.mkdir(parents=True, exist_ok=True)
    (work / src.name).write_text(src.read_text())
    (work / "imply.genlib").write_text((HERE / "imply.genlib").read_text())
    (work / "abc_imply.genlib").write_text((HERE / "abc_imply.genlib").read_text())

    pre = to_pre_blif(src, work)
    mapped = abc_portfolio(work)
    inputs, outputs, gates = parse_blif(mapped)
    primitive_gates = expand_to_primitives(gates)
    adapter_graph = build_dependency_graph(inputs, outputs, gates)
    primitive_graph = build_dependency_graph(inputs, outputs, primitive_gates)
    census = {}
    for gate_type in ("IMPLY", "INV", "BUF", "ZERO", "ONE"):
        census[gate_type] = count_gates(gates, gate_type)
    primitive_census = {}
    for gate_type in ("IMPLY", "BUF", "ZERO"):
        primitive_census[gate_type] = count_gates(primitive_gates, gate_type)

    progs = {}
    progs["naive"] = Sequencer(optimize=False).run(inputs, outputs, primitive_gates)
    progs["opt"] = Sequencer(
        optimize=True,
        preserve_inputs=args.preserve_inputs,
        unlimited_cells=args.unlimited_cells).run(inputs, outputs,
                                                  primitive_gates)

    (work / "mapped_logic.blif").write_text(
        gates_to_blif(name, inputs, outputs, gates))
    (work / "primitive_logic.blif").write_text(
        gates_to_blif(name, inputs, outputs, primitive_gates))
    (work / "dependency_graph.dot").write_text(adapter_graph.to_dot())
    (work / "dependency_tree.txt").write_text(adapter_graph.to_tree_text() + "\n")
    (work / "primitive_dependency_graph.dot").write_text(primitive_graph.to_dot())
    (work / "primitive_dependency_tree.txt").write_text(
        primitive_graph.to_tree_text() + "\n")
    for m, p in progs.items():
        (work / f"prog_{m}.blif").write_text(
            program_to_blif(name, p, inputs, outputs))

    v = {
        "abc-mapping == source (formal cec)":
            cec(work, "pre.blif", "mapped_logic.blif"),
        "primitive graph == mapped netlist (formal cec)":
            cec(work, "mapped_logic.blif", "primitive_logic.blif"),
        "opt sequence == primitive graph (formal cec)":
            cec(work, "primitive_logic.blif", "prog_opt.blif"),
        "naive sequence == primitive graph (formal cec)":
            cec(work, "primitive_logic.blif", "prog_naive.blif"),
    }
    sim_ok, n_vec = sim_sanity(progs["opt"], inputs, outputs, primitive_gates)
    v[f"simulator sanity ({n_vec} vectors)"] = sim_ok

    opt = progs["opt"]
    seq_path = args.out or (work / f"{name}.seq.txt")
    lines = [f"# {name}: IMPLY/FALSE sequence, {opt.steps} steps, "
             f"{opt.n_cells} cells",
             f"# inputs:  {opt.in_cell}", f"# outputs: {opt.out_cell}"]
    step_no = 1
    for op in opt.ops:
        if op[0] == "FALSE":
            line = f"{step_no:>4}  FALSE {op[1]}"
        else:
            line = f"{step_no:>4}  IMPLY {op[1]} -> {op[2]}"
        lines.append(line)
        step_no += 1
    seq_path.write_text("\n".join(lines) + "\n")

    print(f"circuit : {name}  ({len(inputs)} inputs, {len(outputs)} outputs)")
    netlist_line = f"abc map : {census['IMPLY']} IMPLY + {census['INV']} INV"
    if census["BUF"]:
        netlist_line += f" + {census['BUF']} BUF"
    if census["ZERO"] + census["ONE"]:
        netlist_line += " + consts"
    print(netlist_line)
    graph_line = (f"primitive: {primitive_census['IMPLY']} IMPLY + "
                  f"{primitive_census['ZERO']} ZERO")
    if primitive_census["BUF"]:
        graph_line += f" + {primitive_census['BUF']} BUF"
    print(graph_line)
    print(f"steps   : naive {progs['naive'].steps}  ->  opt {opt.steps}"
          f"   (cells {opt.n_cells})")
    for k, ok in v.items():
        if ok:
            mark = "  PASS"
        else:
            mark = "  FAIL"
        print(f"{mark}  {k}")
    print(f"sequence: {seq_path}")
    all_ok = True
    for ok in v.values():
        if not ok:
            all_ok = False
    if not all_ok:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
