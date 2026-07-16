# IMPLY Synthesis — Project 9, Memory-Centric Computing (SS 2026)

Supervisor: Fabian Seiler · Heidelberg University

## 1. What this project is

Memristive crossbars can compute directly inside the memory array using two
physical operations: a parallel **FALSE** reset pulse and stateful material
implication, **IMPLY**(a, b) = ¬a ∨ b. This project is a compiler that takes
any small combinational circuit (Verilog / BLIF / BENCH) and turns it into a
verified sequence of FALSE and IMPLY pulses for one crossbar row.

The repository is intentionally conservative: it contains the logic-level
simulator, the ABC mapping setup, the sequencer, the single-circuit compile
flow, and the ISCAS'85 runner used for the latest supervisor discussion.
Random fuzzing, ATOMIC export, and robustness experiments are still local
work and are not included in this snapshot.

## 2. Summary of results

| Result | Where it is shown |
|---|---|
| `full_adder`: 8 IMPLY + 4 INV after ABC → 12 IMPLY + 4 ZERO primitives → **20 steps / 7 cells** | [docs/full_adder/README.md](docs/full_adder/README.md) |
| `c17` (first ISCAS'85 circuit): 6 IMPLY + 4 INV → 10 IMPLY + 4 ZERO → **15 steps / 8 cells** | [docs/c17/README.md](docs/c17/README.md) |
| All 11 ISCAS'85 circuits compile and verify end-to-end (largest: `c6288`, 12422 naive → **4616** optimized steps) | [docs/document/sequencing_optimization_report.md](docs/document/sequencing_optimization_report.md) §5 |
| FALSE packing is provably minimal for the emitted IMPLY order (minimum interval piercing) | [docs/document/false_packing_report.md](docs/document/false_packing_report.md) |
| Two scheduling corners expose the latency/area trade-off: `--unlimited-cells` (min steps) and `--preserve-inputs` (operands stay readable) | [docs/full_adder/README.md](docs/full_adder/README.md) §8 |
| Comparison against SIMPLER MAGIC (TCAD'20) | [docs/document/comparison_simpler.md](docs/document/comparison_simpler.md) |

Every compiled circuit passes the same four checks: three formal ABC `cec`
equivalences (source == mapping == primitive graph == sequence) plus a
truth-table / sampled simulation of the emitted pulse program.

## 3. Pipeline

```text
circuit.v ──Yosys──▶ pre.blif ──ABC──▶ mapped.blif ──lower INV──▶ ZERO/IMPLY ──Sequencer──▶ .seq.txt
            (§5)      generic   (§5)    IMPLY + INV                dependency      pulse
                      gates             adapter netlist            graph           program
                │              │                    │                        │
                └─── cec ──────┴──────── cec ───────┴────────── cec ─────────┘  + simulator check
```

| stage | tool | input → output | what happens |
|---|---|---|---|
| frontend | Yosys | `.v` → `pre.blif` | parse, flatten, lower to generic single-bit gates |
| mapping | ABC (`yosys-abc`) | `pre.blif` → `mapped.blif` | map onto `abc_imply.genlib` (IMPLY + INV helper); 3 scripts race, lowest cost wins |
| lowering | `compile.py` | `mapped.blif` → primitive graph | every `INV x` becomes `ZERO z; IMPLY x z` — only project primitives remain |
| scheduling | `sequencer.py` | primitive graph → `.seq.txt` | linear pulse program with cell reuse and optimal FALSE packing |
| verification | ABC `cec` + `imply_sim.py` | every arrow above | formal equivalence at each stage + pulse-level simulation |

The single-circuit driver is `synthesis/compile.py`; it runs all stages and
prints the PASS/FAIL summary. `synthesis/run_iscas85.py` batches it over the
checked-in ISCAS'85 set.

## 4. Directory tree

```text
src/
├── README.md                  ← you are here
├── imply_sim.py               logic-level simulator for one crossbar row (IMPLY + FALSE)
├── synthesis/
│   ├── compile.py             one-circuit flow: Yosys → ABC → graph → sequence (+ cec checks)
│   ├── sequencer.py           primitive graph → pulse program (cell reuse, pack_false)
│   ├── utils/
│   │   └── render_schedule_svg.py  .seq.txt → C64-style operation schedule diagram (SVG)
│   ├── verify/
│   │   ├── verify_netlist.py  mapped netlists vs Python golden models
│   │   └── sim_sanity.py      pulse-program simulation cross-check (exhaustive / sampled)
│   ├── run_iscas85.py         batch compile.py over circuits/ISCAS85, writes results tables
│   ├── imply.genlib           project primitive library: IMPLY + ZERO (2 gates, nothing else)
│   ├── abc_imply.genlib       ABC adapter library: + INV (cost 2) + ONE, expanded after mapping
│   ├── circuits/
│   │   ├── gates/             single-gate smoke tests (and2, or2, xor2, not1)
│   │   ├── arithmetic/        full_adder (main example), ripple4/8, sub4, mult2x2
│   │   ├── combinational/     maj3, comp2, mux4, c17 (readable ISCAS'85 c17 rewrite)
│   │   └── ISCAS85/           checked-in c17 … c7552 benchmark sources (literal, run_iscas85.py)
│   ├── tests/                 pytest suite for sequencer, graphs, renderer, ISCAS runner
│   └── compiled/              generated artifacts (gitignored — safe to delete)
├── output/                    gitignored scratch space for anything a script generates
│   └── iscas85/                 default target of run_iscas85.py (results csv/md)
└── docs/
    ├── README.md              index: worked examples, reports, docs conventions
    ├── full_adder/README.md   worked example: full adder, stage by stage, with figures
    ├── c17/README.md          second worked example: ISCAS'85 c17
    ├── assets/                figures embedded by the worked-example READMEs (full_adder/ c17/)
    ├── iscas85_schedules/     schedule diagrams for all 11 ISCAS'85 circuits (+ README)
    └── document/
        ├── sequencing_optimization_report.md   26 → 20 step sequencing improvement (incl. ISCAS'85 before/after table)
        ├── false_packing_report.md   optimal FALSE packing + scheduling corners
        └── comparison_simpler.md     comparison with SIMPLER MAGIC (TCAD'20)
```

The ISCAS'85 result tables (before/after, `--unlimited-cells`) and the
supervisor dashboard are not checked in — regenerate the tables anytime with
`python3 synthesis/run_iscas85.py synthesis/circuits/ISCAS85` (writes to
`output/iscas85/`).

Generated artifacts never land in `docs/` by default: `compile.py` writes to
`synthesis/compiled/`, and `run_iscas85.py` writes to `output/` — both
gitignored and safe to delete. A file only reaches `docs/assets/` when it is
deliberately copied there because a README embeds it (see
[docs/README.md](docs/README.md)).

## 5. External tools and environment

Two external tools do the heavy lifting; everything else is plain Python.

**Yosys** (frontend) — reads Verilog into its RTLIL netlist form and lowers it
to generic single-bit gates: `read_verilog; hierarchy -auto-top; flatten;
proc; opt; techmap; opt; write_blif`. The result (`pre.blif`) is
technology-independent truth-table logic.

**ABC** (mapper + prover, invoked as `yosys-abc`) — maps `pre.blif` onto the
adapter cell library `abc_imply.genlib`. ABC's mapper needs helper cells such
as an inverter, so the adapter adds `INV` with cost 2 (an INV later lowers to
exactly two primitive operations); the compile flow expands all helpers back
to IMPLY/ZERO right after mapping. ABC is also the formal-verification
workhorse: every stage transition is checked with `cec`.

To reproduce the environment:

| requirement | version used here | install (macOS) |
|---|---|---|
| Python | ≥ 3.12 (3.14.6 here) | `brew install python` |
| Yosys | 0.66 | `brew install yosys` |
| ABC | bundled with Yosys as `yosys-abc` | comes with the above |
| pytest | any recent | `pip install pytest` (tests only) |

No other Python dependencies are needed. Sanity-check your setup with:

```bash
python3 imply_sim.py                       # simulator self-test → ALL PASS
cd synthesis
python3 -m pytest tests                    # unit tests
python3 compile.py circuits/gates/not1.v          # smallest example: FALSE [1]; IMPLY 0 -> 1
python3 compile.py circuits/arithmetic/full_adder.v   # main example: 20 steps / 7 cells, all checks PASS
```

## 6. Worked examples and reports (docs/)

Start with **[docs/README.md](docs/README.md)**, the index for everything
below. It links to:

- **[docs/full_adder/README.md](docs/full_adder/README.md)** — walks the
  `full_adder` through every stage of the pipeline with the actual artifacts:
  the ABC netlist, the primitive dependency graph, the annotated 20-step
  pulse schedule (including what every cell holds after every step), the
  operation schedule diagram, and the scheduling-corner variants;
- **[docs/c17/README.md](docs/c17/README.md)** — repeats the exercise on the
  first ISCAS'85 circuit to show the flow is not full-adder-specific.

Each worked example lives in its own `docs/<circuit>/` directory with one
`README.md`; adding a new example follows the same pattern (see
[docs/README.md](docs/README.md) for the convention).

The deeper reports live next to them: sequencing optimization
([26 → 20 steps, incl. the ISCAS'85 before/after table](docs/document/sequencing_optimization_report.md)),
optimal FALSE packing ([report](docs/document/false_packing_report.md)), and the
[SIMPLER MAGIC comparison](docs/document/comparison_simpler.md). The full
ISCAS'85 result tables regenerate with
`python3 synthesis/run_iscas85.py synthesis/circuits/ISCAS85`.

## 7. Scheduling-mode quick reference (`full_adder` and `c17`)

`compile.py` takes two independent flags that trade cell count for step
count (see [docs/full_adder/README.md](docs/full_adder/README.md) §8 for
what each one means). All four combinations, run from `synthesis/`:

| circuit | mode | command | steps | cells |
|---|---|---|---:|---:|
| `full_adder` | default (min-cells) | `python3 compile.py circuits/arithmetic/full_adder.v` | 20 | 7 |
| `full_adder` | `--preserve-inputs` | `python3 compile.py circuits/arithmetic/full_adder.v --preserve-inputs` | 20 | 10 |
| `full_adder` | `--unlimited-cells` | `python3 compile.py circuits/arithmetic/full_adder.v --unlimited-cells` | 17 | 11 |
| `full_adder` | both flags | `python3 compile.py circuits/arithmetic/full_adder.v --preserve-inputs --unlimited-cells` | 18 | 12 |
| `c17` | default (min-cells) | `python3 compile.py circuits/combinational/c17.v` | 15 | 8 |
| `c17` | `--preserve-inputs` | `python3 compile.py circuits/combinational/c17.v --preserve-inputs` | 14 | 10 |
| `c17` | `--unlimited-cells` | `python3 compile.py circuits/combinational/c17.v --unlimited-cells` | 13 | 11 |
| `c17` | both flags | `python3 compile.py circuits/combinational/c17.v --preserve-inputs --unlimited-cells` | 13 | 11 |

If plain `python3` does not resolve on your machine, run the same commands
from the repo root with the full interpreter path instead (adjust the path
to wherever your Python actually lives):

```bash
cd "$(git rev-parse --show-toplevel)"

# 1. default / min-cells
/opt/homebrew/bin/python3.14 synthesis/compile.py synthesis/circuits/arithmetic/full_adder.v

# 2. preserve-inputs
/opt/homebrew/bin/python3.14 synthesis/compile.py synthesis/circuits/arithmetic/full_adder.v --preserve-inputs

# 3. unlimited-cells / min-steps
/opt/homebrew/bin/python3.14 synthesis/compile.py synthesis/circuits/arithmetic/full_adder.v --unlimited-cells

# 4. preserve-inputs + unlimited-cells
/opt/homebrew/bin/python3.14 synthesis/compile.py synthesis/circuits/arithmetic/full_adder.v --preserve-inputs --unlimited-cells
```

Swap `full_adder.v` for `synthesis/circuits/combinational/c17.v` to run the
same four modes on `c17`.

Each run writes its own `<name>.seq.txt` and schedule diagram to
`compiled/<name>/`; pass `-o some/path.seq.txt` to keep multiple modes side
by side instead of overwriting the same output directory. Every row above
was run fresh and passes all four `compile.py` checks (`cec` ×3 + simulator
sanity).
