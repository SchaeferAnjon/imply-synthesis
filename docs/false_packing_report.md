# FALSE Packing Report — grouping independent resets

Follow-up to the 2026-07-02 meeting. Fabian's request: FALSE operations
with no prior dependency should be grouped and moved earlier, ideally one
big parallel reset at the start; every merged group saves one step.

## 1. What changed in the sequencer

The old `merge_false` post-pass walked each FALSE pulse backwards and fused
it into the nearest earlier pulse, stopping at the first IMPLY that touched
*any* cell of the moving pulse. That is a per-pulse, backward-only rule.

The new `pack_false` treats every requested reset independently. A reset of
cell `c` may fire anywhere between the previous op touching `c` and the
next one, so each reset is an **interval** of legal positions between
IMPLYs. Choosing pulse times that cover all intervals with the fewest
pulses is the classic *minimum piercing points* problem, and the greedy
sweep over earliest right endpoints solves it **optimally**. Two upgrades
over `merge_false` fall out for free:

- per-cell granularity: a pulse can split if only part of it is blocked;
- resets can also move **later** to share a pulse with resets that come
  after them (backward-only merging can never see these).

Each chosen pulse is finally placed at the earliest position all its
members allow, so resets happen as early as possible — the schedule
diagrams now show one wide reset pulse up front instead of scattered
single-cell resets.

## 2. An honest negative result (worth stating in the report)

On all 11 ISCAS'85 circuits and all three portfolio schedulers, optimal
packing produces **exactly the same pulse count** as the old greedy merge.
Since `pack_false` is provably minimal for a fixed IMPLY order, this shows
the previous numbers were already optimal in this dimension: with cell
reuse on, a reused cell is reset in the gap right after its previous value
dies, and no earlier or later pulse can absorb it. Further step savings
must therefore come from a different degree of freedom — which is the next
section.

## 3. The real lever: cell reuse vs one upfront reset

If a cell is **never reused**, its reset interval starts at position 0, so
*every* reset packs into a single FALSE pulse before the first IMPLY:

    steps = #IMPLY + 1

`--unlimited-cells` (compile.py) / `Sequencer(unlimited_cells=True)` turns
this on. It is exactly the latency/area corner SIMPLER's Table IV calls
"UnlimitCells". The default mode remains the min-cells corner.

`--preserve-inputs` is independent: input nets join the protected set, so
their cells are never overwritten by a destructive IMPLY and never
reclaimed — the original operands stay readable after the computation
(Fabian's "save the input as well" request).

## 4. Results (all formally verified with ABC cec + simulator sanity)

Full adder:

| mode | steps | cells |
|---|---:|---:|
| min-cells (default) | 20 | 7 |
| `--preserve-inputs` | 20 | 10 |
| `--unlimited-cells` | **17** | 11 |
| preserve + unlimited | **18** | 12 |

The last row answers the meeting's full-adder question directly: inputs
a/b/cin stay readable **and** the sequence got 2 steps shorter than the
previous 20-step result.

c17: 15 steps / 8 cells (min-cells), **13 steps** / 11 cells (min-steps).

ISCAS'85 min-steps mode saves 8–19% latency over min-cells for ~2–2.6x
cells; c432 drops to 218 steps, below SIMPLER's 237 cycles. Full tables:
`iscas85_results_after.{csv,md}` (min-cells),
`iscas85_results_unlimited.{csv,md}` (min-steps), and the side-by-side
against the state of the art in `comparison_simpler.md`.

## 5. Reproduce

```bash
python3.14 -m pytest synthesis/tests -q
python3.14 synthesis/compile.py synthesis/circuits/full_adder.v --preserve-inputs --unlimited-cells
python3.14 synthesis/run_iscas85.py synthesis/circuits/ISCAS85 \
  --csv docs/iscas85_results_after.csv --md docs/iscas85_results_after.md
python3.14 synthesis/run_iscas85.py synthesis/circuits/ISCAS85 --unlimited-cells \
  --csv docs/iscas85_results_unlimited.csv --md docs/iscas85_results_unlimited.md
```
