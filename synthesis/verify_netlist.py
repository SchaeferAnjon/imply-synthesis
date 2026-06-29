#!/usr/bin/env python3
"""Verify ABC adapter netlists against small Python golden models.

For every out/<name>.blif: parse the .gate netlist (IMPLY / INV / ZERO / ONE),
evaluate it exhaustively over all input combinations, and compare with the
golden model. Also report gate census and a serial step estimate
(IMPLY = 1 step, INV = 2 steps: ZERO + IMPLY). This is a front-end check;
the primitive dependency graph and exact pulse program come from compile.py.
"""
from itertools import product
from pathlib import Path

OUT_DIR = Path(__file__).parent / "out"


def _bits(env: dict[str, int], prefix: str, width: int) -> int:
    """Collect bus bits env['p[0]']..env['p[w-1]'] into an int."""
    value = 0
    for i in range(width):
        value += env[f"{prefix}[{i}]"] << i
    return value


def _unbits(value: int, prefix: str, width: int) -> dict[str, int]:
    out = {}
    for i in range(width):
        out[f"{prefix}[{i}]"] = (value >> i) & 1
    return out


def g_not1(env):
    return {"y": 1 - env["a"]}


def g_and2(env):
    return {"y": env["a"] & env["b"]}


def g_or2(env):
    return {"y": env["a"] | env["b"]}


def g_xor2(env):
    return {"y": env["a"] ^ env["b"]}


def g_full_adder(env):
    s = env["a"] + env["b"] + env["cin"]
    return {"sum": s & 1, "cout": s >> 1}


def g_ripple4(env):
    s = _bits(env, "a", 4) + _bits(env, "b", 4) + env["cin"]
    out = _unbits(s & 0xF, "s", 4)
    out["cout"] = (s >> 4) & 1
    return out


def g_sub4(env):
    a, b = _bits(env, "a", 4), _bits(env, "b", 4)
    out = _unbits((a - b) & 0xF, "d", 4)
    out["bout"] = int(a < b)
    return out


def g_mult2x2(env):
    return _unbits((_bits(env, "a", 2) * _bits(env, "b", 2)) & 0xF, "p", 4)


def g_mux4(env):
    return {"y": env[f"d[{_bits(env, 's', 2)}]"]}


def g_c17(env):
    n10 = 1 - (env["N1"] & env["N3"])
    n11 = 1 - (env["N3"] & env["N6"])
    n16 = 1 - (env["N2"] & n11)
    n19 = 1 - (n11 & env["N7"])
    return {"N22": 1 - (n10 & n16), "N23": 1 - (n16 & n19)}


def g_maj3(env):
    a, b, c = env["a"], env["b"], env["c"]
    return {"y": (a & b) | (a & c) | (b & c)}


def g_comp2(env):
    a, b = _bits(env, "a", 2), _bits(env, "b", 2)
    return {"eq": int(a == b), "lt": int(a < b)}


def g_ripple8(env):
    s = _bits(env, "a", 8) + _bits(env, "b", 8) + env["cin"]
    out = _unbits(s & 0xFF, "s", 8)
    out["cout"] = (s >> 8) & 1
    return out


GOLDEN = {
    "not1": g_not1, "and2": g_and2, "or2": g_or2, "xor2": g_xor2,
    "full_adder": g_full_adder, "ripple4": g_ripple4, "sub4": g_sub4,
    "mult2x2": g_mult2x2, "mux4": g_mux4,
    "c17": g_c17, "maj3": g_maj3, "comp2": g_comp2, "ripple8": g_ripple8,
}


def parse_blif(path: Path):
    """Return (inputs, outputs, gates). gates = list of (type, pin_map)."""
    text = path.read_text()
    # BLIF uses a backslash when one logical line continues on the next line.
    # Joining them here keeps the later parser boring.
    lines = []
    for raw in text.splitlines():
        if lines and lines[-1].endswith("\\"):
            lines[-1] = lines[-1][:-1] + " " + raw.strip()
        else:
            lines.append(raw.strip())

    inputs, outputs, gates = [], [], []
    names_pending = None  # handle constant .names blocks from yosys/abc
    for line in lines:
        if names_pending is not None:
            # A .names with no input is a constant driver. The next line tells
            # us whether it is const1; otherwise I treat it as const0.
            if line == "1":
                const_type = "ONE"
            else:
                const_type = "ZERO"
            gates.append((const_type, {"O": names_pending}))
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
            # ABC sometimes collapses a signal to a passthrough, for example
            # y = a & a. This is not a real pulse later; it is just an alias.
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
    """Iteratively evaluate gates until all nets resolve (order-independent)."""
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


def main():
    rows = []
    for name, golden in GOLDEN.items():
        blif = OUT_DIR / f"{name}.blif"
        if not blif.exists():
            rows.append((name, "-", "-", "-", "MISSING"))
            continue
        inputs, outputs, gates = parse_blif(blif)
        n_imply = 0
        n_inv = 0
        for typ, _pins in gates:
            if typ == "IMPLY":
                n_imply += 1
            elif typ == "INV":
                n_inv += 1
        ok = True
        for bits in product((0, 1), repeat=len(inputs)):
            env = {}
            for i, input_name in enumerate(inputs):
                env[input_name] = bits[i]
            net = eval_netlist(inputs, gates, env)
            want = golden(env)
            for out_name in outputs:
                if net[out_name] != want[out_name]:
                    ok = False
                    break
            if not ok:
                break
        est = n_imply + 2 * n_inv  # serial estimate, pre-sequencer
        if ok:
            mark = "OK"
        else:
            mark = "FAIL"
        rows.append((name, n_imply, n_inv, est, mark))

    print(f"{'circuit':<12}{'IMPLY':>6}{'INV':>5}{'~steps':>8}{'verify':>8}")
    print("-" * 39)
    for r in rows:
        print(f"{r[0]:<12}{r[1]:>6}{r[2]:>5}{r[3]:>8}{r[4]:>8}")
    print("\n~steps = IMPLY + 2*INV (INV lowers to ZERO+IMPLY; "
          "ZERO becomes FALSE in the pulse sequence); exact count comes "
          "from compile.py / sequencer.py.")
    failed = False
    for row in rows:
        if row[4] != "OK":
            failed = True
    if failed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
