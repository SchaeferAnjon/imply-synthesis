# docs — worked examples and reports

Index for the project's documentation. See the top-level
[../README.md](../README.md) for the project overview and pipeline; this page
is only about what lives under `docs/`.

## Worked examples

Each example circuit gets its own directory with one `README.md` that walks
the circuit through every pipeline stage using its real compiled artifacts.

| directory | circuit | result |
|---|---|---|
| [full_adder/](full_adder/README.md) | 1-bit full adder (main explanatory case) | 20 steps / 7 cells |
| [c17/](c17/README.md) | first ISCAS'85 benchmark (6 NAND gates) | 15 steps / 8 cells |

**Adding a new worked example:** create `docs/<circuit>/`, write a
`README.md` there (use `full_adder/README.md` or `c17/README.md` as a
template), and put its figures in `docs/assets/<circuit>/`. Generate the
figures into `output/` first (see below), and only copy the ones you want to
keep into `docs/assets/<circuit>/` as a deliberate publishing step.

## Reports

| report | what it covers |
|---|---|
| [sequencing_optimization_report.md](sequencing_optimization_report.md) | the 26 → 20 step full_adder scheduling improvement |
| [document/false_packing_report.md](document/false_packing_report.md) | optimal FALSE packing (`pack_false`) and the `--preserve-inputs` / `--unlimited-cells` scheduling corners |
| [document/comparison_simpler.md](document/comparison_simpler.md) | comparison against SIMPLER MAGIC (TCAD'20) on ISCAS'85 |
| [iscas85_schedules/](iscas85_schedules/README.md) | operation schedule diagrams for all 11 checked-in ISCAS'85 circuits |

The full ISCAS'85 result tables (before/after the sequencing optimization,
and the `--unlimited-cells` corner) and the one-page supervisor dashboard
were dropped to keep `docs/` lean. The tables regenerate in one command:

```bash
python3 synthesis/run_iscas85.py synthesis/circuits/ISCAS85              # after / default
python3 synthesis/run_iscas85.py synthesis/circuits/ISCAS85 --unlimited-cells
# both write to output/iscas85/iscas85_results.{csv,md}
```

## Where generated figures go

`render_schedule_svg.py`, `run_iscas85.py`, and friends never write into
`docs/` by default — their output goes to `output/` (gitignored, safe to
delete, organized by kind: `output/iscas85/`, `output/benchmark/`, or
whatever you point a one-off render at). `docs/assets/` only holds figures
that have been deliberately promoted there because a README embeds them.
This keeps `docs/` a curated, stable set of narrative pages instead of a
dumping ground for every regeneration.

## Directory tree

```text
docs/
├── README.md                  ← this index
├── full_adder/README.md       worked example: full adder, stage by stage
├── c17/README.md              worked example: ISCAS'85 c17
├── assets/
│   ├── full_adder/            figures embedded by full_adder/README.md
│   └── c17/                   figures embedded by c17/README.md
├── iscas85_schedules/         schedule diagrams for all 11 ISCAS'85 circuits (+ own README)
├── sequencing_optimization_report.md
└── document/
    ├── false_packing_report.md
    └── comparison_simpler.md
```
