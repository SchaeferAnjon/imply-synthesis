# synthesis directory

This folder contains the current Boolean-to-IMPLY flow. The public version is
kept narrow on purpose: it shows the mapping setup, the netlist checker, the
sequencer, and the one-circuit `compile.py` demo. The larger evaluation scripts
are still local until I have discussed them.

## files

| file | purpose |
|---|---|
| `imply.genlib` | project primitive library: `ZERO` + `IMPLY` |
| `abc_imply.genlib` | ABC adapter library: `IMPLY` plus temporary mapping helpers |
| `dependency_graph.py` | expands helpers into a primitive dependency graph and exports tree/DOT views |
| `run_synth.sh` | runs Yosys and ABC for every circuit in `circuits/` |
| `verify_netlist.py` | checks ABC output against small Python golden models |
| `sequencer.py` | turns primitive dependency graphs into `FALSE` and `IMPLY` pulses |
| `compile.py` | one-circuit flow, including ABC `cec` equivalence checks |
| `circuits/` | small Verilog inputs used while developing |
| `demo/` | extra inputs for manual demos |
| `tests/` | unit tests for the public code |

## the primitive library

```genlib
GATE IMPLY  1  O=!a+b;
GATE ZERO   0  O=CONST0;
```

`imply.genlib` is the project-facing target: only the CONST0 source and the
IMPLY compute primitive. In the pulse sequence, every `ZERO` node becomes a
`FALSE` reset.

ABC's mapper currently needs helper cells such as an inverter, so the actual
ABC call uses `abc_imply.genlib` as an adapter:

```genlib
GATE IMPLY  1  O=!a+b;
GATE INV    2  O=!a;
GATE ZERO   0  O=CONST0;
GATE ONE    0  O=CONST1;
```

Immediately after ABC mapping, `dependency_graph.py` rewrites helpers back into
the primitive graph. For example, one `INV x` becomes:

```text
ZERO z
IMPLY x z
```

During sequencing, `ZERO z` becomes `FALSE work_cell`. After the reset, the
target cell is `0`, so:

```text
x -> 0 = NOT x OR 0 = NOT x
```

That is why `INV` has area 2 in `abc_imply.genlib`.

## one-circuit demo

```bash
python3.14 compile.py circuits/not1.v
cat compiled/not1/not1.seq.txt
```

Expected shape:

```text
# not1: IMPLY/FALSE sequence, 2 steps, 2 cells
# inputs:  {'a': 0}
# outputs: {'y': 1}
   1  FALSE [1]
   2  IMPLY 0 -> 1
```

`compile.py` writes a few intermediate files under `compiled/<circuit>/`. The
final sequence is the `.seq.txt` file.

For a nontrivial circuit such as `full_adder.v`, it also writes:

```text
compiled/full_adder/dependency_tree.txt
compiled/full_adder/dependency_graph.dot
```

These files make the scheduling input explicit. The current full-adder shape is
an ABC adapter netlist of `8 IMPLY + 4 INV`, expanded to a primitive graph of
`12 IMPLY + 4 ZERO` before sequencing.

## batch front end

```bash
bash run_synth.sh
python3.14 verify_netlist.py
```

This regenerates `pre/*.blif` and `out/*.blif`, then checks that the ABC adapter
netlists compute the same functions as the Python golden models. For the
primitive dependency graph and actual pulse sequence, use `compile.py`.

## benchmark direction

The small local benchmark set is still useful for fast iteration. The next
external benchmark target is the ISCAS'85 set Fabian pointed to:

https://github.com/santoshsmalagi/Benchmarks/tree/main/ISCAS85

The intended order is to keep `full_adder` as the explanatory case, use local
`c17.v` as the first ISCAS'85 sanity check, and then add larger circuits such as
`c432` once the graph-based scheduler is stable.

Current smoke results through `compile.py`:

| circuit | adapter map | primitive graph | optimized sequence |
|---|---:|---:|---:|
| `full_adder` | 8 IMPLY + 4 INV | 12 IMPLY + 4 ZERO | 26 steps / 7 cells |
| `c17` | 6 IMPLY + 4 INV | 10 IMPLY + 4 ZERO | 20 steps / 7 cells |

## current limits

- The flow is for combinational circuits.
- Sequential circuits with `.latch` are rejected instead of silently handled.
- The public repository does not include the later benchmark, fuzzing, ATOMIC,
  or robustness scripts yet.
