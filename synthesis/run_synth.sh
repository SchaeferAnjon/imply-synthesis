#!/usr/bin/env bash
# 流水线：Verilog --yosys--> BLIF --ABC(+abc_imply.genlib)--> 适配网表
# （思路来自 SIMPLER/Ben-Hur 2020 的图 5，这里用 IMPLY 替代 NOR）
#
# 这里保留三套 ABC 脚本，因为单一脚本并不能在所有小电路上都最优。
# 粗略成本记作 IMPLY + 2*INV，因为 INV 在后续原语依赖图中会展开为
# ZERO+IMPLY。
set -euo pipefail
cd "$(dirname "$0")"

ABC="$(command -v yosys-abc || command -v abc || command -v berkeley-abc)"
[ -n "$ABC" ] || { echo "ERROR: no ABC binary found (need yosys-abc)"; exit 1; }

SCRIPTS=(
  "strash; dc2; map -a"
  "strash; balance; rewrite; refactor; balance; rewrite; rewrite -z; balance; refactor -z; rewrite -z; balance; dch -f; map -a"
  "strash; dc2; dch -f; map -a"
)

cost_of() {  # 对单个映射后 BLIF 的粗略脉冲成本估算
  local ni nv
  ni=$(grep -c '^\.gate IMPLY' "$1" || true)
  nv=$(grep -c '^\.gate INV' "$1" || true)
  echo $((ni + 2 * nv))
}

mkdir -p pre out
for v in $(find circuits -name '*.v' -not -path 'circuits/ISCAS85/*' | sort); do
  name="$(basename "$v" .v)"

  # 阶段 1：用 yosys 将 Verilog 降解为通用 BLIF。
  yosys -q -p "read_verilog $v; hierarchy -auto-top; flatten; proc; opt; techmap; opt; write_blif pre/$name.blif"

  # 阶段 2：用 ABC 把该 BLIF 映射到适配库（IMPLY/INV）。
  best_cost=999999; best_idx=0
  for idx in "${!SCRIPTS[@]}"; do
    "$ABC" -c "read_blif pre/$name.blif; read_genlib abc_imply.genlib; ${SCRIPTS[$idx]}; write_blif out/.$name.$idx.blif" >/dev/null
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
echo "for a single-circuit sequence demo, run: python3 compile.py circuits/gates/not1.v"
