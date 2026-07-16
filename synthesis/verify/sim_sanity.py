"""仿真健全性检查：在逻辑层模拟器上执行脉冲程序并与网表输出对拍。

小电路（≤12 输入）穷举全部输入组合；大电路用固定随机种子抽样
1000 组，保证结果可复现。形式等价由 compile.py 的 ABC cec 负责，
这里只做仿真层面的交叉验证。
"""
import random
from itertools import product

from imply_sim import CrossbarRow
from sequencer import Program
from verify.verify_netlist import eval_netlist


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
