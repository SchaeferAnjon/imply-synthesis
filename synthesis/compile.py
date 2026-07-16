#!/usr/bin/env python3
"""把一个组合逻辑电路编译为 IMPLY/FALSE 序列。

用法:
    python3 compile.py <circuit.v | .blif | .bench> [-o out.seq.txt]

这是演示入口文件。它和 run_synth.sh 走同一套前端流程，
但只处理一个电路，并在关键阶段调用 ABC 的 cec 做等价检查，
避免把“穷举仿真”当成可无限扩展的验证方式。
Combinational Equivalence Checking (CEC) 是 ABC 的一个功能，能在不穷举输入向量的情况下判断两个组合逻辑网表是否等价。
    输入 --yosys--> pre.blif --ABC 脚本组合--> mapped.blif（适配库网表）
                        |                               |
                        +========= cec 形式验证 =========+
    mapped.blif --ZERO/IMPLY 依赖图--> primitive_logic.blif
                        |                               |
                        +========= cec 形式验证 =========+
    原语图 --Sequencer--> program --SSA 转 BLIF--> prog_{opt,naive}.blif
                        |                               |
                        +========= cec 形式验证 =========+

另外还有一个 CrossbarRow 仿真健全性检查：
小电路做穷举，大电路用固定随机种子抽样，保证结果可复现。

范围：仅组合逻辑（Project 9）。遇到时序电路会直接给出明确错误信息。
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
from render_schedule_svg import parse_sequence, render_svg
from sequencer import Program, Sequencer
from verify_netlist import eval_netlist, parse_blif

ABC_SCRIPTS = [
    "strash; dc2; map -a",
    "strash; balance; rewrite; refactor; balance; rewrite; rewrite -z; "
    "balance; refactor -z; rewrite -z; balance; dch -f; map -a",
    "strash; dc2; dch -f; map -a",
]
IMPLY_CUBES = ["0- 1", "-1 1"]          # O = !a + b


def _safe(name: str) -> str:
    out = []
    for ch in name:
        if ch.isalnum() or ch == "_":
            out.append(ch)
        else:
            out.append("_")
    return "".join(out)


def _zero_name(out: str, index: int) -> str:
    return f"__zero_{_safe(out)}_{index}"


def expand_to_primitives(gates: list[tuple[str, dict[str, str]]]
                         ) -> list[tuple[str, dict[str, str]]]:
    """Lower helper gates to the ZERO/IMPLY primitive set used by scheduler."""
    primitive: list[tuple[str, dict[str, str]]] = []
    zero_index = 0
    for typ, pins in gates:
        if typ in ("IMPLY", "ZERO", "BUF"):
            primitive.append((typ, dict(pins)))
        elif typ == "INV":
            z = _zero_name(pins["O"], zero_index)
            zero_index += 1
            primitive.append(("ZERO", {"O": z}))
            primitive.append(("IMPLY", {"a": pins["a"], "b": z,
                                         "O": pins["O"]}))
        elif typ == "ONE":
            z_src = _zero_name(pins["O"], zero_index)
            zero_index += 1
            z_dst = _zero_name(pins["O"], zero_index)
            zero_index += 1
            primitive.append(("ZERO", {"O": z_src}))
            primitive.append(("ZERO", {"O": z_dst}))
            primitive.append(("IMPLY", {"a": z_src, "b": z_dst,
                                         "O": pins["O"]}))
        else:
            raise ValueError(f"cannot lower helper gate {typ!r} to primitives")
    return primitive


def count_gates(gates: list[tuple], gate_type: str) -> int:
    """统计网表中某一类门的数量。"""
    count = 0
    for typ, _ in gates:
        if typ == gate_type:
            count += 1
    return count


def mapping_cost(gates: list[tuple]) -> int:
    # 这是编排前的估算成本。INV 记作 2，因为后续会降解成 FALSE + IMPLY。
    return count_gates(gates, "IMPLY") + 2 * count_gates(gates, "INV")


def run(cmd: list[str], cwd: Path) -> str:
    """执行外部命令；失败时抛出带输出信息的异常。"""
    r = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"{cmd[0]} failed:\n{r.stderr or r.stdout}")
    return r.stdout


def to_pre_blif(src: Path, work: Path) -> Path:
    """把输入文件统一转成 pre.blif（IMPLY 技术映射前）。"""
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
    """用 3 套 ABC 脚本做小型组合搜索，选出最优 mapped.blif。"""
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
    """把网表门列表写成普通 BLIF，供 ABC cec 做等价比较。"""
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
    """把 IMPLY/FALSE 程序转成 SSA 风格 BLIF。

    这里 SSA 很关键：同一个物理 cell 可能被多次覆盖写入。
    在逻辑网表里，每次新值都要用新名字，否则 cec 会比较错对象。
    """
    cur = {}
    ver = {}
    for net, cell in prog.in_cell.items():
        cur[cell] = net
        ver[cell] = 0
    L = [f".model {model}", ".inputs " + " ".join(inputs),
         ".outputs " + " ".join(outputs)]

    def bump(c: int) -> str:
        """给 cell c 生成新 SSA 版本名并更新当前绑定。"""
        ver[c] = ver.get(c, 0) + 1
        cur[c] = f"c{c}v{ver[c]}"
        return cur[c]

    for op in prog.ops:
        if op[0] == "FALSE":
            for c in op[1]:
                L.append(f".names {bump(c)}")        # 无 cube 表示常量 0
        else:
            _, s, d = op
            a, b = cur[s], cur[d]
            L += [f".names {a} {b} {bump(d)}"] + IMPLY_CUBES
    for o in outputs:
        L += [f".names {cur[prog.out_cell[o]]} {o}", "1 1"]
    return "\n".join(L) + "\n.end\n"


def cec(work: Path, f1: str, f2: str) -> bool:
    """调用 ABC cec 做等价检查，返回是否等价。"""
    out = run(["yosys-abc", "-c", f"cec {f1} {f2}"], cwd=work)
    if "Networks are equivalent" in out:
        return True
    if "NOT EQUIVALENT" in out.upper():
        return False
    raise RuntimeError(f"cec inconclusive:\n{out}")


def run_program(prog: Program, env: dict[str, int]) -> tuple[dict[str, int], int]:
    """在逻辑层模拟器上执行生成的 IMPLY/FALSE 程序。"""
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
    """用仿真交叉检查程序输出与网表输出是否一致。"""
    if len(inputs) <= 12:
        # 输入位数不大时直接穷举。
        vectors = list(product((0, 1), repeat=len(inputs)))
    else:
        # 输入位数大时固定种子随机采样，保证可复现。
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


def write_schedule_graphs(seq_path: Path) -> Path:
    """基于 .seq.txt 自动生成调度图（svg）。"""
    seq_name = seq_path.name
    if seq_name.endswith(".seq.txt"):
        base = seq_name[:-8]
    else:
        base = seq_path.stem
    svg_path = seq_path.parent / f"{base}_schedule.svg"

    inputs, outputs, ops, n_cells = parse_sequence(seq_path)
    title = f"{base} IMPLY/FALSE schedule"
    svg_path.write_text(render_svg(title, inputs, outputs, ops, n_cells))
    return svg_path


def main() -> None:
    """主流程：映射、展开、调度、验证、导出序列与中间产物。"""
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("circuit", type=Path)
    ap.add_argument("-o", "--out", type=Path, default=None,
                    help="sequence output file (default: <work>/<name>.seq.txt)")
    ap.add_argument("--preserve-inputs", action=argparse.BooleanOptionalAction,
                    default=True,
                    help="keep every input cell readable at the end of the "
                         "optimized sequence (default on; use "
                         "--no-preserve-inputs to allow overwriting inputs)")
    ap.add_argument("--max-cells", type=int, default=None,
                    help="row-width budget: allocate fresh cells up to this "
                         "many, then reuse freed cells (default: no budget = "
                         "fewest steps; 0 = reuse aggressively = fewest cells)")
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
        max_cells=args.max_cells).run(inputs, outputs, primitive_gates)

    (work / "mapped_logic.blif").write_text(
        gates_to_blif(name, inputs, outputs, gates))
    (work / "primitive_logic.blif").write_text(
        gates_to_blif(name, inputs, outputs, primitive_gates))
    for m, p in progs.items():
        (work / f"prog_{m}.blif").write_text(
            program_to_blif(name, p, inputs, outputs))

    # 多个验证关口：前端映射、原语展开、时序程序都分别做形式等价检查。
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
    svg_path = write_schedule_graphs(seq_path)

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
    print(f"schedule svg: {svg_path}")
    all_ok = True
    for ok in v.values():
        if not ok:
            all_ok = False
    if not all_ok:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
