# ISCAS'85 Compile Results

Source directory: `synthesis/circuits/ISCAS85`

| circuit | inputs | outputs | naive steps | opt steps | cells | status |
|---|---:|---:|---:|---:|---:|---|
| `c1355` | 41 | 32 | 2732 | 766 | 418 | PASS |
| `c17` | 5 | 2 | 54 | 13 | 11 | PASS |
| `c1908` | 33 | 25 | 2621 | 684 | 361 | PASS |
| `c2670` | 233 | 140 | 3914 | 1004 | 704 | PASS |
| `c3540` | 50 | 22 | 6188 | 1684 | 811 | PASS |
| `c432` | 36 | 7 | 971 | 218 | 132 | PASS |
| `c499` | 41 | 32 | 2901 | 761 | 414 | PASS |
| `c5315` | 178 | 123 | 9005 | 2439 | 1301 | PASS |
| `c6288` | 32 | 32 | 12422 | 3731 | 1892 | PASS |
| `c7552` | 207 | 108 | 10014 | 2630 | 1450 | PASS |
| `c880` | 60 | 26 | 2100 | 543 | 296 | PASS |

- `naive steps` and `opt steps` are real generated pulse counts from `compile.py`.
- `status = PASS` means ABC mapping, primitive lowering, optimized sequence, naive sequence, and simulator sanity all passed inside `compile.py`.
