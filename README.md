# IMPLY synthesis for Project 9

This is my current public code for Project 9 in Memory-Centric Computing
(SS 2026, Heidelberg University).

The goal is to take a small combinational circuit and turn it into a sequence
of memristive `FALSE` and `IMPLY` operations. The repository is intentionally
conservative: it contains the simulator, the ABC mapping setup, the sequencer,
and a single-circuit compile flow. Batch benchmarks, random fuzzing, ATOMIC
export, and robustness experiments are still local work and are not included in
this snapshot.

Supervisor: Fabian Seiler

## what currently works

```text
Verilog / BLIF / BENCH
  -> Yosys
  -> generic BLIF
  -> ABC with synthesis/imply.genlib
  -> IMPLY/INV netlist
  -> synthesis/sequencer.py
  -> IMPLY/FALSE sequence
  -> simulator sanity check
  -> ABC cec equivalence checks
```

The custom ABC library is very small:

```genlib
GATE IMPLY  1  O=!a+b;
GATE INV    2  O=!a;
GATE ZERO   0  O=CONST0;
GATE ONE    0  O=CONST1;
```

ABC is allowed to use `INV` during mapping because it helps produce cleaner
logic. The sequencer later lowers each `INV` to `FALSE + IMPLY`, so the public
program still uses only the two operations required by the project.

## files

| path | role |
|---|---|
| `imply_sim.py` | logic-level simulator for one crossbar row |
| `synthesis/imply.genlib` | ABC cell library for IMPLY mapping |
| `synthesis/run_synth.sh` | batch front end for the small Verilog examples |
| `synthesis/verify_netlist.py` | checks mapped netlists against Python golden models |
| `synthesis/sequencer.py` | lowers IMPLY/INV netlists to pulse programs |
| `synthesis/compile.py` | one-circuit demo flow with ABC `cec` checks |
| `synthesis/circuits/` | small Verilog inputs |
| `synthesis/demo/` | extra demo inputs for `compile.py` |
| `synthesis/tests/` | tests for the public pieces |

## quick run

```bash
# simulator self-test
python3.14 imply_sim.py

# compile the smallest example
cd synthesis
python3.14 compile.py circuits/not1.v
cat compiled/not1/not1.seq.txt

# a less trivial example
python3.14 compile.py circuits/full_adder.v
```

For `not1.v`, the final sequence should be:

```text
FALSE [1]
IMPLY 0 -> 1
```

If input `a` is in cell `0`, resetting cell `1` and then applying
`IMPLY 0 -> 1` stores `NOT a` in cell `1`.

## local toolchain

- Python 3.14
- Yosys
- ABC through `yosys-abc`

Generated directories such as `synthesis/pre/`, `synthesis/out/`, and
`synthesis/compiled/` are ignored. They can be regenerated from the source
files.
