#!/bin/bash
# =============================================================================
# rename_bandgap.sh —— 把 ke 带隙段的 4 个计算目录改名并嵌套进 step2_bandgap/
#
#   计算目录（超算 + 本地 result）改名：
#     step2_PBE_static   → step2_bandgap/step2.1_static
#     step3_PBE_WAVECAR  → step2_bandgap/step2.2_wave
#     step4_HSE_band     → step2_bandgap/step2.3_hse
#     step4_band_plot    → step2_bandgap/step2.4_gap
#
# 做法：只改 4 个 gen 脚本顶部的目录常量（它们互相引用全走这些常量）。
# 源目录结构（skill/ke/bandgap/*）不动 —— 那是 patch4 的 src，与计算目录无关。
#
# 幂等：改过的常量再改会被 grep 检查挡住。运行前 ke 不能有在跑的带隙作业。
#
# 用法：在 ~/software/taskflow 下  bash rename_bandgap.sh
# =============================================================================
set -euo pipefail
KE="$HOME/software/taskflow/skill/ke"
[ -d "$KE" ] || { echo "错误：找不到 $KE"; exit 1; }

S2="$KE/bandgap/step2_static/gen_step2_static.py"
S3="$KE/bandgap/step3_wavecar/gen_step3_WAVECAR.py"
S4="$KE/bandgap/step4_hse/gen_step4_HSE.py"
SP="$KE/bandgap/step4_plot/gen_step4.1_plot_band.py"
for f in "$S2" "$S3" "$S4" "$SP"; do
  [ -f "$f" ] || { echo "错误：找不到 $f（setup_ke.sh 跑过吗？）"; exit 1; }
done

# 新目录名（带点号，patch5 已支持）
D_STATIC="step2_bandgap/step2.1_static"
D_WAVE="step2_bandgap/step2.2_wave"
D_HSE="step2_bandgap/step2.3_hse"
D_GAP="step2_bandgap/step2.4_gap"

edit() {  # edit <文件> <旧常量行> <新常量行> <校验串>
  local f="$1" old="$2" new="$3" chk="$4"
  if grep -qF "$chk" "$f"; then echo "  跳过（已改）: $(basename "$f") → $chk"; return; fi
  grep -qF "$old" "$f" || { echo "错误：$(basename "$f") 里找不到:  $old"; exit 1; }
  sed -i "s|$old|$new|" "$f"
  grep -qF "$chk" "$f" || { echo "错误：$(basename "$f") 改写校验失败"; exit 1; }
  echo "  ok: $(basename "$f")  $chk"
}

echo "== gen_step2_static.py =="
edit "$S2" \
  'STEP2_DIR = "step2_PBE_static"' \
  "STEP2_DIR = \"$D_STATIC\"" \
  "STEP2_DIR = \"$D_STATIC\""

echo "== gen_step3_WAVECAR.py =="
edit "$S3" \
  'STEP2_DIR    = "step2_PBE_static"     # 源目录' \
  "STEP2_DIR    = \"$D_STATIC\"     # 源目录" \
  "STEP2_DIR    = \"$D_STATIC\""
edit "$S3" \
  'STEP3_DIR    = "step3_PBE_WAVECAR"    # 目标目录' \
  "STEP3_DIR    = \"$D_WAVE\"    # 目标目录" \
  "STEP3_DIR    = \"$D_WAVE\""

echo "== gen_step4_HSE.py =="
edit "$S4" \
  'STEP3_DIR  = "step3_PBE_WAVECAR"   # 源目录' \
  "STEP3_DIR  = \"$D_WAVE\"   # 源目录" \
  "STEP3_DIR  = \"$D_WAVE\""
edit "$S4" \
  'STEP4_DIR  = "step4_HSE_band"      # 目标目录（切片时自动加 _p{i}of{n}）' \
  "STEP4_DIR  = \"$D_HSE\"      # 目标目录（切片时自动加 _p{i}of{n}）" \
  "STEP4_DIR  = \"$D_HSE\""

echo "== gen_step4.1_plot_band.py =="
edit "$SP" \
  'STEP4_DIR = "step4_HSE_band"      # 源目录' \
  "STEP4_DIR = \"$D_HSE\"      # 源目录" \
  "STEP4_DIR = \"$D_HSE\""
edit "$SP" \
  'OUT_DIR   = "step4_band_plot"     # 目标目录（输入输出都在这里）' \
  "OUT_DIR   = \"$D_GAP\"     # 目标目录（输入输出都在这里）" \
  "OUT_DIR   = \"$D_GAP\""

echo
echo "完成。计算目录已改名为："
echo "  step2_bandgap/step2.1_static  step2.2_wave  step2.3_hse  step2.4_gap"
echo "接着用新 skill.yaml（步骤名/合并列已同步）。"
