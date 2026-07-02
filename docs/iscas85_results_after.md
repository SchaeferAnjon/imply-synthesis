# ISCAS'85 Compile Results

Source directory: `synthesis/circuits/ISCAS85`

| circuit | inputs | outputs | naive steps | opt steps | cells | status |
|---|---:|---:|---:|---:|---:|---|
| `c1355` | 41 | 32 | 2732 | 888 | 229 | PASS |
| `c17` | 5 | 2 | 54 | 15 | 8 | PASS |
| `c1908` | 33 | 25 | 2621 | 807 | 208 | PASS |
| `c2670` | 233 | 140 | 3914 | 1235 | 367 | PASS |
| `c3540` | 50 | 22 | 6188 | 1981 | 323 | PASS |
| `c432` | 36 | 7 | 971 | 243 | 72 | PASS |
| `c499` | 41 | 32 | 2901 | 885 | 228 | PASS |
| `c5315` | 178 | 123 | 9005 | 2867 | 640 | PASS |
| `c6288` | 32 | 32 | 12422 | 4616 | 741 | PASS |
| `c7552` | 207 | 108 | 10014 | 3190 | 717 | PASS |
| `c880` | 60 | 26 | 2100 | 631 | 160 | PASS |

- `naive steps` and `opt steps` are real generated pulse counts from `compile.py`.
- `status = PASS` means ABC mapping, primitive lowering, optimized sequence, naive sequence, and simulator sanity all passed inside `compile.py`.
