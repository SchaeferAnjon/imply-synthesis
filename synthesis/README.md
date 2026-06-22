# synthesis directory

This folder contains the current Boolean-to-IMPLY flow. The public version is
kept narrow on purpose: it shows the mapping setup, the netlist checker, the
sequencer, and the one-circuit `compile.py` demo. The larger evaluation scripts
are still local until I have discussed them.

## files

| file | purpose |
|---|---|
| `imply.genlib` | ABC library: real `IMPLY` gate plus a temporary `INV` pseudo-gate |
| `run_synth.sh` | runs Yosys and ABC for every circuit in `circuits/` |
| `verify_netlist.py` | checks ABC output against small Python golden models |
| `sequencer.py` | turns IMPLY/INV gates into `FALSE` and `IMPLY` pulses |
| `compile.py` | one-circuit flow, including ABC `cec` equivalence checks |
| `circuits/` | small Verilog inputs used while developing |
| `demo/` | extra inputs for manual demos |
| `tests/` | unit tests for the public code |

## the ABC library

```genlib
GATE IMPLY  1  O=!a+b;
GATE INV    2  O=!a;
GATE ZERO   0  O=CONST0;
GATE ONE    0  O=CONST1;
```

`IMPLY` is the operation I ultimately want. `INV` is only a helper that ABC can
use while it is simplifying the Boolean circuit. Later, the sequencer rewrites
one `INV x` as:

```text
FALSE work_cell
IMPLY x -> work_cell
```

After the reset, the target cell is `0`, so:

```text
x -> 0 = NOT x OR 0 = NOT x
```

That is why `INV` has area 2 in `imply.genlib`.

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

## batch front end

```bash
bash run_synth.sh
python3.14 verify_netlist.py
```

This regenerates `pre/*.blif` and `out/*.blif`, then checks that the mapped
IMPLY/INV netlists compute the same functions as the Python golden models. This
step checks the ABC output. For the actual pulse sequence, use `compile.py`.

## current limits

- The flow is for combinational circuits.
- Sequential circuits with `.latch` are rejected instead of silently handled.
- The public repository does not include the later benchmark, fuzzing, ATOMIC,
  or robustness scripts yet.
