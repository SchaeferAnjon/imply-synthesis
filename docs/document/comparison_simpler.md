# Comparison: IMPLY flow vs SIMPLER MAGIC (state of the art)

Reference: R. Ben-Hur et al., "SIMPLER MAGIC: Synthesis and Mapping of
In-Memory Logic Executed in a Single Row to Improve Throughput,"
IEEE TCAD 39(10), 2020. DOI 10.1109/TCAD.2019.2931188.
SIMPLER numbers below are Table II of that paper (ISCAS'85, NOR2 netlists).

## Accounting rules (why the comparison is fair)

- Both flows compute one circuit inside a **single crossbar row**.
- SIMPLER `#Cyc` = executed MAGIC NOR gates + reinitialization cycles, where
  any set of cells can be reset in one cycle. Our `steps` = IMPLY pulses +
  FALSE pulses, where one FALSE pulse also resets any set of cells. Initial
  loading of the inputs is not counted by either side.
- SIMPLER `#Mem` = cells of the row used by one instance, inputs included.
  Our `cells` counts the same thing.
- Netlists differ by construction: SIMPLER maps to NOR2 gates, we map to
  IMPLY gates via ABC + custom genlib, so gate counts (and therefore cycle
  floors) are not identical per circuit.
- Our flow reports two corners, like SIMPLER's Table IV does for row size:
  - **min-cells** (default): dead cells are reused, fewest cells.
  - **min-steps** (`--unlimited-cells`): no cell reuse, so every reset packs
    into a single upfront FALSE pulse and steps = #IMPLY + 1.
- Every row below is formally verified (ABC `cec` at 4 pipeline points) plus
  a simulator sanity pass; SIMPLER numbers are as printed in the paper.

## ISCAS'85 (c17 is not reported by SIMPLER)

| circuit | SIMPLER #Cyc | SIMPLER #Mem | ours min-cells steps / cells | ours min-steps steps / cells | best cycle ratio (ours/SIMPLER) |
|---|---:|---:|---:|---:|---:|
| c432  | 237  | 62  | 243 / 72   | **218** / 132 | **0.92** |
| c499  | 620  | 110 | 885 / 228  | 761 / 414  | 1.23 |
| c880  | 512  | 142 | 631 / 160  | 543 / 296  | 1.06 |
| c1355 | 619  | 111 | 888 / 229  | 766 / 418  | 1.24 |
| c1908 | 588  | 122 | 807 / 208  | 684 / 361  | 1.16 |
| c2670 | 891  | 383 | 1235 / **367** | 1004 / 704 | 1.13 |
| c3540 | 1434 | 192 | 1981 / 323 | 1684 / 811 | 1.17 |
| c5315 | 2002 | 351 | 2867 / 640 | 2439 / 1301 | 1.22 |
| c6288 | 2938 | 149 | 4616 / 741 | 3731 / 1892 | 1.27 |
| c7552 | 2227 | 535 | 3190 / 717 | 2630 / 1450 | 1.18 |

Geomean of the cycle ratio: **1.15** in min-steps mode, 1.36 in min-cells
mode. Cell geomean (min-cells mode vs SIMPLER #Mem): 1.66.

## Small circuits (not in the SIMPLER paper)

| circuit | mode | steps | cells | note |
|---|---|---:|---:|---|
| c17 | min-cells | 15 | 8 | |
| c17 | min-steps | **13** | 11 | below the 14-step state-of-the-art reference |
| full adder | min-cells | 20 | 7 | outputs overwrite b/cin |
| full adder | `--preserve-inputs` | 20 | 10 | inputs still readable, same steps |
| full adder | `--unlimited-cells` | **17** | 11 | single upfront FALSE pulse |
| full adder | preserve + unlimited | **18** | 12 | inputs readable **and** 2 steps saved |

## Reading the numbers

- **c432 beats SIMPLER on latency** (218 vs 237 cycles, −8%) and c880 is
  within 6%. XOR-heavy circuits (c499/c1355, and the c6288 multiplier)
  cost more IMPLY gates than NOR2 gates, which is where the remaining
  latency gap comes from — it is a netlist-mapping effect, not a
  scheduling effect (our FALSE packing is provably minimal for a given
  IMPLY order, see `false_packing_report.md`).
- The two corners span the same latency/area trade-off SIMPLER's Table IV
  spans with row size: min-steps buys ~15% latency for ~2.5x cells.
- c2670 uses fewer cells than SIMPLER in min-cells mode (367 vs 383).
