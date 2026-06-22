#!/usr/bin/env bash
# Pipeline: Verilog --yosys--> BLIF --ABC(+imply.genlib)--> IMPLY-only netlist
# (the SIMPLER/Ben-Hur 2020 Fig.5 idea, but with NOR replaced by IMPLY)
#
# I keep three ABC scripts here because one script does not win on every small
# circuit. The rough cost is IMPLY + 2*INV, since an INV later becomes
# FALSE+IMPLY in the sequencer.
set -euo pipefail
cd "$(dirname "$0")"

ABC="$(command -v yosys-abc || command -v abc || command -v berkeley-abc)"
[ -n "$ABC" ] || { echo "ERROR: no ABC binary found (need yosys-abc)"; exit 1; }

SCRIPTS=(
  "strash; dc2; map -a"
  "strash; balance; rewrite; refactor; balance; rewrite; rewrite -z; balance; refactor -z; rewrite -z; balance; dch -f; map -a"
  "strash; dc2; dch -f; map -a"
)

cost_of() {  # rough pulse estimate for one mapped BLIF file
  local ni nv
  ni=$(grep -c '^\.gate IMPLY' "$1" || true)
  nv=$(grep -c '^\.gate INV' "$1" || true)
  echo $((ni + 2 * nv))
}

mkdir -p pre out
for v in circuits/*.v; do
  name="$(basename "$v" .v)"

  # Stage 1: yosys lowers Verilog to a generic BLIF file.
  yosys -q -p "read_verilog $v; hierarchy -auto-top; flatten; proc; opt; techmap; opt; write_blif pre/$name.blif"

  # Stage 2: ABC maps that BLIF into the custom IMPLY/INV library.
  best_cost=999999; best_idx=0
  for idx in "${!SCRIPTS[@]}"; do
    "$ABC" -c "read_blif pre/$name.blif; read_genlib imply.genlib; ${SCRIPTS[$idx]}; write_blif out/.$name.$idx.blif" >/dev/null
    c=$(cost_of "out/.$name.$idx.blif")
    if [ "$c" -lt "$best_cost" ]; then best_cost=$c; best_idx=$idx; fi
  done
  mv "out/.$name.$best_idx.blif" "out/$name.blif"
  rm -f out/."$name".*.blif

  printf "%-12s IMPLY=%-3d INV=%-3d cost=%-3d (script #%d)\n" "$name" \
    "$(grep -c '^\.gate IMPLY' "out/$name.blif" || true)" \
    "$(grep -c '^\.gate INV'   "out/$name.blif" || true)" \
    "$best_cost" "$((best_idx + 1))"
done

echo "---"
echo "netlists in out/*.blif; next: python3 verify_netlist.py"
echo "for a single-circuit sequence demo, run: python3 compile.py circuits/not1.v"
