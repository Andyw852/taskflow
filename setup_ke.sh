#!/bin/bash
# =============================================================================
# setup_ke.sh —— 从 band / elastic 装配 ke 技能（分组源目录布局 v1.5）
#
# 磁盘结构（大步骤套小步骤）：
#   skill/ke/
#   ├── step1_opt/                  ← elastic 结构优化原样
#   ├── bandgap/                    ← band 技能全套
#   │   ├── step2_static/  step3_wavecar/  step4_hse/  step4_plot/
#   ├── step5_uniform/  step6_wave/  step7_elastic/  step8_dielect/
#   ├── deform/  ├── step9_deform/  └── step9b_read/
#   └── step10_amset/
#
# 材料计算目录仍是平的（step1_std_opt/、step2_PBE_static/…），不受影响。
#
# 用法：在 ~/software/taskflow 下  bash setup_ke.sh
# =============================================================================
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
SK="$ROOT/skill"; KE="$SK/ke"
[ -d "$SK/band" ] && [ -d "$SK/elastic" ] || { echo "错误：缺 band 或 elastic 技能目录"; exit 1; }

EL_T1="$SK/elastic/templates/step1_std_opt"
EL_T2="$SK/elastic/templates/step2_elastic"
BD_T="$SK/band/templates"
for d in "$EL_T1" "$EL_T2" "$BD_T"; do
  [ -d "$d" ] || { echo "错误：找不到 $d（band/elastic 还没重组成 templates 布局？）"; exit 1; }
done
mk(){ mkdir -p "$KE/$1"; }

echo "== step1_opt（结构优化，复用 elastic）=="
mk step1_opt
cp "$SK/elastic/gen_step1_std_opt.py" "$SK/elastic/dim_common.py" \
   "$SK/elastic/check_common.py" "$SK/elastic/step1_check_and_resubmit.py" "$KE/step1_opt/"
cp "$EL_T1"/*.tpl "$KE/step1_opt/"

echo "== bandgap/（带隙，复用 band 全套）=="
mk bandgap/step2_static; mk bandgap/step3_wavecar; mk bandgap/step4_hse; mk bandgap/step4_plot
cp "$SK/band/gen_step2_static.py"  "$KE/bandgap/step2_static/"
cp "$SK/band/gen_step3_WAVECAR.py" "$KE/bandgap/step3_wavecar/"
cp "$SK/band/gen_step4_HSE.py"     "$KE/bandgap/step4_hse/"
cp "$SK/band/gen_step4.1_plot_band.py" "$KE/bandgap/step4_plot/"
cp "$SK/band/step2_check_and_resubmit.py" "$KE/bandgap/step2_static/"
cp "$SK/band/step3_check_and_resubmit.py" "$KE/bandgap/step3_wavecar/"
cp "$SK/band/step4_check_and_resubmit.py" "$KE/bandgap/step4_hse/"
for s in step2_static step3_wavecar step4_hse; do
  cp "$SK/band/dim_common.py" "$SK/band/check_common.py" "$KE/bandgap/$s/"
  cp "$BD_T"/*.tpl "$KE/bandgap/$s/"
done
# ★必改：ke 弛豫目录叫 step1_std_opt（不是 band 的 step1c_PBE_opt）
sed -i 's/^STEP1_DIR = "auto"/STEP1_DIR = "step1_std_opt"   # ke：弛豫复用 elastic 目录名/' \
    "$KE/bandgap/step2_static/gen_step2_static.py"
grep -q 'STEP1_DIR = "step1_std_opt"' "$KE/bandgap/step2_static/gen_step2_static.py" \
  || { echo "错误：STEP1_DIR 改写失败"; exit 1; }

echo "== step7_elastic（弹性常数，复用 elastic 的 IBRION=6）=="
mk step7_elastic
cp "$SK/elastic/gen_step2_elastic.py" "$SK/elastic/dim_common.py" \
   "$SK/elastic/check_common.py" "$SK/elastic/step2_check_and_resubmit.py" "$KE/step7_elastic/"
cp "$EL_T2"/*.tpl "$KE/step7_elastic/"
sed -i 's/^STEP2_DIR = "step2_elastic"/STEP2_DIR = "step7_elastic"   # ke：改名避免和带隙段 step2_* 混淆/' \
    "$KE/step7_elastic/gen_step2_elastic.py"
grep -q 'STEP2_DIR = "step7_elastic"' "$KE/step7_elastic/gen_step2_elastic.py" \
  || { echo "错误：STEP2_DIR 改写失败"; exit 1; }

echo "== 新步骤目录（gen 脚本 + 模板待补）=="
mk step5_uniform; mk step6_wave; mk step8_dielect
mk deform/step9_deform; mk deform/step9b_read; mk step10_amset
# 共享一份弛豫的 dim_common/check_common 给新的 VASP 步（各自独立副本）
for s in step5_uniform step8_dielect deform/step9_deform; do
  cp "$SK/elastic/dim_common.py" "$SK/elastic/check_common.py" "$KE/$s/"
done
# amset 步的提交模板
cp "$ROOT/submit_amset.tpl" "$KE/step6_wave/"  2>/dev/null || true
cp "$ROOT/submit_amset.tpl" "$KE/step10_amset/" 2>/dev/null || true

echo
echo "装配完成。源目录结构："
( cd "$KE" && find . -maxdepth 2 -type d | sort | sed 's/^/  /' )
echo
echo "还缺（下一步补）："
echo "  step5_uniform/gen_step5_uniform.py + incar_uniform_{2d,3d}.tpl"
echo "  step6_wave/gen_step6_wave.py"
echo "  step8_dielect/gen_step8_dielect.py + incar_dfpt_{2d,3d}.tpl"
echo "  deform/step9_deform/gen_step9_deform.py + incar_deform_{2d,3d}.tpl"
echo "  deform/step9b_read/gen_step9b_deform_read.py"
echo "  step10_amset/gen_step10_amset.py"
echo
echo "放 skill.yaml 到 $KE/，enabled 仍为 false，补齐后改 true。"
