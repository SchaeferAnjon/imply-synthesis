#!/usr/bin/env python3
"""Run compile.py over an ISCAS'85 Verilog directory and write a report."""
import argparse
import csv
import re
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).parent


def parse_compile_output(text: str) -> dict[str, str]:
    """Extract the stable metrics printed by compile.py."""
    patterns = {
        "io": r"circuit : \S+  \((\d+) inputs, (\d+) outputs\)",
        "abc_map": r"abc map : (.*)",
        "primitive": r"primitive: (.*)",
        "steps": r"steps\s+: naive (\d+)\s+->\s+opt (\d+)\s+\(cells (\d+)\)",
    }
    result: dict[str, str] = {}
    m = re.search(patterns["io"], text)
    if m:
        result["inputs"], result["outputs"] = m.groups()
    m = re.search(patterns["abc_map"], text)
    if m:
        result["abc_map"] = m.group(1).strip()
    m = re.search(patterns["primitive"], text)
    if m:
        result["primitive"] = m.group(1).strip()
    m = re.search(patterns["steps"], text)
    if m:
        result["naive_steps"], result["opt_steps"], result["cells"] = m.groups()
    return result


def run_one(path: Path, timeout: int) -> dict[str, str]:
    started = time.time()
    cmd = [sys.executable, str(HERE / "compile.py"), str(path)]
    try:
        proc = subprocess.run(cmd, cwd=HERE.parent, capture_output=True, text=True,
                              timeout=timeout)
        elapsed = time.time() - started
        text = proc.stdout + proc.stderr
        row = parse_compile_output(text)
        row["circuit"] = path.stem
        row["status"] = "PASS" if proc.returncode == 0 and "FAIL" not in text else f"EXIT{proc.returncode}"
        row["seconds"] = f"{elapsed:.1f}"
        if row["status"] != "PASS":
            row["message"] = text[-800:].replace("\n", " ")
        return row
    except subprocess.TimeoutExpired:
        return {
            "circuit": path.stem,
            "inputs": "-",
            "outputs": "-",
            "abc_map": "-",
            "primitive": "-",
            "naive_steps": "-",
            "opt_steps": "-",
            "cells": "-",
            "status": "TIMEOUT",
            "seconds": str(timeout),
            "message": "compile.py timed out",
        }


def write_csv(rows: list[dict[str, str]], path: Path) -> None:
    fields = [
        "circuit", "inputs", "outputs", "abc_map", "primitive",
        "naive_steps", "opt_steps", "cells", "status", "seconds",
    ]
    with path.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "-") for field in fields})


def write_markdown(rows: list[dict[str, str]], path: Path, source: Path) -> None:
    lines = [
        "# ISCAS'85 Compile Results",
        "",
        f"Source directory: `{source}`",
        "",
        "| circuit | inputs | outputs | naive steps | opt steps | cells | status |",
        "|---|---:|---:|---:|---:|---:|---|",
    ]
    for row in rows:
        lines.append(
            f"| `{row.get('circuit', '-')}` | {row.get('inputs', '-')} | "
            f"{row.get('outputs', '-')} | {row.get('naive_steps', '-')} | "
            f"{row.get('opt_steps', '-')} | {row.get('cells', '-')} | "
            f"{row.get('status', '-')} |"
        )
    lines += [
        "",
        "- `naive steps` and `opt steps` are real generated pulse counts from `compile.py`.",
        "- `status = PASS` means ABC mapping, primitive lowering, optimized sequence, naive sequence, and simulator sanity all passed inside `compile.py`.",
    ]
    path.write_text("\n".join(lines) + "\n")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("iscas85_dir", type=Path,
                        help="directory containing ISCAS'85 .v files")
    parser.add_argument("--timeout", type=int, default=180,
                        help="seconds per circuit")
    parser.add_argument("--csv", type=Path, default=HERE / "iscas85_results.csv")
    parser.add_argument("--md", type=Path, default=HERE / "iscas85_results.md")
    args = parser.parse_args()

    files = sorted(args.iscas85_dir.glob("**/*.v"))
    if not files:
        raise SystemExit(f"no .v files found under {args.iscas85_dir}")

    rows = []
    for path in files:
        row = run_one(path, args.timeout)
        rows.append(row)
        print(
            f"{row.get('circuit', '-'):<8} "
            f"opt={row.get('opt_steps', '-'):>5} "
            f"cells={row.get('cells', '-'):>4} "
            f"{row.get('status', '-')}"
        )

    write_csv(rows, args.csv)
    write_markdown(rows, args.md, args.iscas85_dir)
    print(f"csv: {args.csv}")
    print(f"md : {args.md}")
    if any(row.get("status") != "PASS" for row in rows):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
