#!/usr/bin/env python3
"""BLIF 网表解析与逻辑求值。

``parse_blif`` 读取 ABC 输出的 .gate 风格 BLIF（IMPLY / INV / ZERO /
ONE / BUF）；``eval_netlist`` 对网表按需迭代求值。二者供
``compile.py`` 与 ``verify/sim_sanity.py`` 使用。
"""
from pathlib import Path


def parse_blif(path: Path):
    """读取 BLIF 文件，返回 ``(inputs, outputs, gates)``。

    ``inputs`` 和 ``outputs`` 是网络名列表；``gates`` 中每一项都是
    ``(门类型, 引脚映射)``，例如 ``("IMPLY", {"a": "x", "b": "y", "O": "z"})``。
    """
    text = path.read_text()
    # BLIF 用反斜杠表示逻辑行延续到下一物理行；先合并以简化后续解析。
    lines = []
    for raw in text.splitlines():
        if lines and lines[-1].endswith("\\"):
            lines[-1] = lines[-1][:-1] + " " + raw.strip()
        else:
            lines.append(raw.strip())

    inputs, outputs, gates = [], [], []
    names_pending = None  # 暂存 Yosys/ABC 输出的常量 .names 块。
    for line in lines:
        if names_pending is not None:
            # 没有输入的 .names 是常量驱动器；下一行若为 1 则是常量 1，
            # 其他情况按常量 0 处理。
            if line == "1":
                const_type = "ONE"
            else:
                const_type = "ZERO"
            gates.append((const_type, {"O": names_pending}))
                # 这个门的输出常量是1 or 0. 
            names_pending = None
            if line in ("1", "0", ""):
                continue
        tok = line.split()
        if not tok:
            continue
        if tok[0] == ".inputs":
            inputs += tok[1:]
        elif tok[0] == ".outputs":
            outputs += tok[1:]
        elif tok[0] == ".gate":
            pins = {}
            for item in tok[2:]:
                name, value = item.split("=", 1)
                pins[name] = value
            gates.append((tok[1], pins))
        elif tok[0] == ".barbuf":
            # ABC 有时会把信号折叠为透传，例如 y = a & a。
            # 它不是后续要执行的真实脉冲，只是同一值的别名。
            gates.append(("BUF", {"a": tok[1], "O": tok[2]}))
        elif tok[0] == ".latch":
            raise ValueError(f"{path.name}: sequential circuit (.latch), "
                             "Project 9 scope is combinational only")
        elif tok[0] == ".names" and len(tok) == 2:
            names_pending = tok[1]  # constant driver
        elif tok[0] == ".names":
            raise ValueError(f"{path.name}: unexpected logic .names {tok[1:]}")
    return inputs, outputs, gates


def eval_netlist(inputs, gates, env):
    """迭代计算网表，直到所有门的输出都可解析。

    门列表不要求已经按拓扑顺序排列；每轮只计算输入值已就绪的门。
    """
    net = dict(env)
    pending = list(gates)
    while pending:
        progressed = False
        rest = []
        for typ, pins in pending:
            inputs_ready = True
            for pin_name, net_name in pins.items():
                if pin_name == "O":
                    continue
                if net_name not in net:
                    inputs_ready = False
                    break
            if inputs_ready:
                if typ == "IMPLY":
                    net[pins["O"]] = (1 - net[pins["a"]]) | net[pins["b"]]
                elif typ == "INV":
                    net[pins["O"]] = 1 - net[pins["a"]]
                elif typ == "BUF":
                    net[pins["O"]] = net[pins["a"]]
                elif typ == "ZERO":
                    net[pins["O"]] = 0
                elif typ == "ONE":
                    net[pins["O"]] = 1
                else:
                    raise ValueError(f"non-IMPLY gate in netlist: {typ}")
                progressed = True
            else:
                rest.append((typ, pins))
        if not progressed:
            raise RuntimeError("combinational loop or undriven net")
        pending = rest
    return net
