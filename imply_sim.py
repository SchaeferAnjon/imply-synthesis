"""Small logic-level simulator for IMPLY and FALSE pulses.

This is intentionally not a SPICE model. It only keeps the Boolean state of one
crossbar row, which is enough to check whether a generated pulse sequence
computes the right truth table.

Models a single row of a memristor crossbar at the logic level:
    cells[i] ∈ {0, 1}    # 0 = R_off, 1 = R_on
    imply(a, b)          # cells[b] := (¬cells[a]) ∨ cells[b]
    false_reset([...])   # parallel reset, counts as ONE step
"""

from dataclasses import dataclass, field


@dataclass
class CrossbarRow:
    cells: list[int] = field(default_factory=list)
    steps: int = 0
    trace: list[str] = field(default_factory=list)

    def imply(self, i_a: int, i_b: int) -> None:
        """In-place stateful IMPLY: cells[i_b] = (¬cells[i_a]) ∨ cells[i_b]."""
        a = self.cells[i_a]
        b = self.cells[i_b]
        if a == 0:
            self.cells[i_b] = 1
        else:
            self.cells[i_b] = b
        self.steps += 1
        self.trace.append(f"IMPLY {i_a}->{i_b}")

    def false_reset(self, indices: list[int]) -> None:
        """Parallel FALSE pulse: set listed cells to 0. One pulse = one step."""
        for i in indices:
            self.cells[i] = 0
        self.steps += 1
        self.trace.append(f"FALSE {indices}")

    def reset_counters(self) -> None:
        self.steps = 0
        self.trace.clear()


def imply_truth(a: int, b: int) -> int:
    """Reference: a -> b  ≡  (¬a) ∨ b."""
    return (1 - a) | b


def verify_imply() -> None:
    """Run a single IMPLY for all 4 input combinations of (a, b)."""
    print("=" * 50)
    print("[1]  Verifying IMPLY truth table")
    print("=" * 50)
    print(f"{'a':>2} {'b':>2} | {'expected':>8} {'got':>4}  step  trace")
    print("-" * 50)

    all_ok = True
    for a in (0, 1):
        for b in (0, 1):
            row = CrossbarRow(cells=[a, b])
            row.imply(0, 1)                # dst cell becomes (not a) or b
            got = row.cells[1]
            expected = imply_truth(a, b)
            ok = got == expected
            all_ok &= ok
            if ok:
                mark = "OK"
            else:
                mark = "FAIL"
            print(f"{a:>2} {b:>2} | {expected:>8} {got:>4}  "
                  f"{row.steps:>3}   {row.trace}  [{mark}]")

    print("-" * 50)
    if all_ok:
        print("ALL PASS")
    else:
        print("SOME FAILED")
    assert all_ok, "IMPLY truth table verification failed"


def verify_false_reset() -> None:
    """FALSE must zero the listed cells AND count as exactly ONE step."""
    print()
    print("=" * 50)
    print("[2]  Verifying parallel FALSE reset")
    print("=" * 50)

    row = CrossbarRow(cells=[1, 1, 1, 1])
    row.false_reset([0, 2, 3])              # reset 3 cells in one pulse

    print(f"  cells before reset:  [1, 1, 1, 1]")
    print(f"  cells after  reset:  {row.cells}")
    print(f"  step count:          {row.steps}    (must be 1, not 3)")
    print(f"  trace:               {row.trace}")

    assert row.cells == [0, 1, 0, 0], "FALSE reset wrong target cells"
    assert row.steps == 1,            "FALSE must count as one step"
    print("  [OK] one pulse, one step")


# Tiny composite demo: build OR(a, b) using IMPLY + FALSE.
#   OR(a, b) = (¬a) → b = imply(a_idx, b_idx) when b_idx already holds b
#   But IMPLY overwrites b, so we use a work cell w:
#       w := 0                # FALSE
#       w := a -> w  = ¬a     # IMPLY (because IMPLY into 0 gives ¬a)
#       b := w -> b  = a ∨ b  # IMPLY
#   Layout: cells = [a, b, w] at indices [0, 1, 2]

def build_or(a: int, b: int) -> tuple[int, int, list[str]]:
    """Return (or_value, step_count, trace) for a 3-step OR built from IMPLY+FALSE."""
    row = CrossbarRow(cells=[a, b, 0])
    row.false_reset([2])                    # step 1: w := 0
    row.imply(0, 2)                         # step 2: w := a -> w = ¬a
    row.imply(2, 1)                         # step 3: b := w -> b = a ∨ b
    return row.cells[1], row.steps, row.trace


def verify_or() -> None:
    print()
    print("=" * 50)
    print("[3]  Composite demo: OR(a, b) in 3 IMPLY/FALSE steps")
    print("=" * 50)
    print(f"{'a':>2} {'b':>2} | {'expected':>8} {'got':>4}  steps")
    print("-" * 40)
    all_ok = True
    for a in (0, 1):
        for b in (0, 1):
            got, steps, _ = build_or(a, b)
            expected = a | b
            ok = got == expected
            all_ok &= ok
            if ok:
                mark = "OK"
            else:
                mark = "FAIL"
            print(f"{a:>2} {b:>2} | {expected:>8} {got:>4}  {steps:>4}  [{mark}]")
    print("-" * 40)
    if all_ok:
        print("ALL PASS")
    else:
        print("SOME FAILED")
    assert all_ok


if __name__ == "__main__":
    verify_imply()
    verify_false_reset()
    verify_or()
    print("\nDemo complete.")
