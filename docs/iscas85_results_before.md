# ISCAS'85 Baseline Before Sequencer Optimization

| circuit | inputs | outputs | naive steps | opt steps | cells | status |
|---|---:|---:|---:|---:|---:|---|
| `c1355` | 41 | 32 | 2732 | 960 | 119 | PASS |
| `c17` | 5 | 2 | 54 | 20 | 7 | PASS |
| `c1908` | 33 | 25 | 2621 | 958 | 152 | PASS |
| `c2670` | 233 | 140 | 3914 | 1358 | 282 | PASS |
| `c3540` | 50 | 22 | 6188 | 2174 | 236 | PASS |
| `c432` | 36 | 7 | 971 | 336 | 56 | PASS |
| `c499` | 41 | 32 | 2901 | 1013 | 133 | PASS |
| `c5315` | 178 | 123 | 9005 | 3142 | 483 | PASS |
| `c6288` | 32 | 32 | 12422 | 4930 | 724 | PASS |
| `c7552` | 207 | 108 | 10014 | 3583 | 564 | PASS |
| `c880` | 60 | 26 | 2100 | 716 | 131 | PASS |

- Captured from the current branch immediately before the sequencer alias-retention change.
- Same `compile.py` flow and same ISCAS'85 source directory as the after run.
