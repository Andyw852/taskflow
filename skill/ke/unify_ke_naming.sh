#!/usr/bin/env bash
# unify_ke_naming.sh —— 把 ke 技能命名统一到 seq 号（就地改，幂等）
# 用法（taskflow 仓库根目录）: bash skill/ke/unify_ke_naming.sh
#   预览: DRY=1 bash skill/ke/unify_ke_naming.sh
set -euo pipefail
KE="skill/ke"; DRY="${DRY:-0}"
have_git(){ git rev-parse --is-inside-work-tree >/dev/null 2>&1; }
mv_(){ local s="$1" d="$2"; [ -e "$s" ] || { echo "  [skip] $s"; return 0; }
  if [ "$DRY" = 1 ]; then echo "  [dry] mv $s -> $d"; return 0; fi
  if have_git && git ls-files --error-unmatch "$s" >/dev/null 2>&1; then git mv "$s" "$d"; else mv "$s" "$d"; fi; }
sed_(){ local f="$1" e="$2"; [ -f "$f" ] || { echo "  [skip-sed] $f"; return 0; }
  if [ "$DRY" = 1 ]; then echo "  [dry] sed '$e'  $f"; return 0; fi; sed -i "$e" "$f"; }

echo "== 1) 源目录改名 =="
mv_ "$KE/step5_uniform" "$KE/step3_uniform"
mv_ "$KE/step6_wave"    "$KE/step4_wave"
mv_ "$KE/step8_dielect" "$KE/step5_dielect"
mv_ "$KE/step7_elastic" "$KE/step6_elastic"
mv_ "$KE/deform/step9_deform" "$KE/deform/step7_deform"
mv_ "$KE/deform/step9b_read"  "$KE/deform/step7b_read"
mv_ "$KE/step10_amset"  "$KE/step8_amset"
mv_ "$KE/bandgap/step2_static"  "$KE/bandgap/step2.1_static"
mv_ "$KE/bandgap/step3_wavecar" "$KE/bandgap/step2.2_wave"
mv_ "$KE/bandgap/step4_hse"     "$KE/bandgap/step2.3_hse"
mv_ "$KE/bandgap/step4_plot"    "$KE/bandgap/step2.4_gap"

echo "== 2) 计算目录常量：产出方 OUTDIR + 消费方 *_DIR（按内层 token 替换）=="
sed_ "$KE/step1_opt/gen_step1_std_opt.py"     's/OUTDIR_SINGLE="step1_std_opt"/OUTDIR_SINGLE="step1_opt"/'
sed_ "$KE/step3_uniform/gen_step5_uniform.py" 's/step5_uniform/step3_uniform/g'
sed_ "$KE/step4_wave/gen_step6_wave.py"       's/step6_wave/step4_wave/g; s/step5_uniform/step3_uniform/g'
sed_ "$KE/step5_dielect/gen_step8_dielect.py" 's/step8_dielect/step5_dielect/g'
sed_ "$KE/step6_elastic/gen_step2_elastic.py" 's/step7_elastic/step6_elastic/g'
sed_ "$KE/deform/step7_deform/gen_step9_deform.py"      's/step9_deform/step7_deform/g'
sed_ "$KE/deform/step7b_read/gen_step9b_deform_read.py" 's/step9b_deform_read/step7b_deform_read/g; s/step9_deform/step7_deform/g'
sed_ "$KE/step8_amset/gen_step10_amset.py"    's/step10_amset/step8_amset/g; s/step6_wave/step4_wave/g; s/step8_dielect/step5_dielect/g; s/step7_elastic/step6_elastic/g; s/step9b_deform_read/step7b_deform_read/g'

echo "== 3) step1 双名兜底（新名 step1_opt，旧作业目录 step1_std_opt 仍认）=="
for f in "$KE/step3_uniform/gen_step5_uniform.py" "$KE/deform/step7_deform/gen_step9_deform.py" "$KE/step5_dielect/gen_step8_dielect.py"; do
  sed_ "$f" 's/PREV_CANDS *= *\["step1_std_opt"\]/PREV_CANDS   = ["step1_opt", "step1_std_opt"]/'
  sed_ "$f" 's/, "step1_std_opt")/, "step1_opt")/'
done
sed_ "$KE/bandgap/step2.1_static/gen_step2_static.py" 's/^STEP1_DIR = "step1_std_opt".*/STEP1_DIR = "auto"/'
sed_ "$KE/bandgap/step2.1_static/gen_step2_static.py" 's/for name in ("step1c_PBE_opt"/for name in ("step1_opt", "step1_std_opt", "step1c_PBE_opt"/'
sed_ "$KE/step6_elastic/gen_step2_elastic.py" 's|^STEP1_DIR = "step1_std_opt"|import os as _os\nSTEP1_DIR = "step1_opt" if _os.path.isdir("step1_opt") else "step1_std_opt"|'
sed_ "$KE/step1_opt/step1_check_and_resubmit.py" 's|Path(__file__).resolve().parent / "step1_std_opt"|Path(__file__).resolve().parent / ("step1_opt" if (Path(__file__).resolve().parent / "step1_opt").is_dir() else "step1_std_opt")|'

echo "== 4) skill.yaml 的 name/src（label、seq 已对齐，不动）=="
Y="$KE/skill.yaml"
sed_ "$Y" 's/name: step1_std_opt, label: S1_opt, src: step1_opt/name: step1_opt, label: S1_opt, src: step1_opt/'
sed_ "$Y" 's/name: step5_uniform, label: S3_uniform, src: step5_uniform/name: step3_uniform, label: S3_uniform, src: step3_uniform/'
sed_ "$Y" 's/name: step6_wave, label: S4_wave, src: step6_wave/name: step4_wave, label: S4_wave, src: step4_wave/'
sed_ "$Y" 's/name: step8_dielect, label: S5_dielect, src: step8_dielect/name: step5_dielect, label: S5_dielect, src: step5_dielect/'
sed_ "$Y" 's/name: step7_elastic, label: S6_elastic, src: step7_elastic/name: step6_elastic, label: S6_elastic, src: step6_elastic/'
sed_ "$Y" 's|name: step9_deform, label: S7_deform, src: deform/step9_deform|name: step7_deform, label: S7_deform, src: deform/step7_deform|'
sed_ "$Y" 's|name: step9b_deform_read, label: S7.1_read, src: deform/step9b_read|name: step7b_deform_read, label: S7.1_read, src: deform/step7b_read|'
sed_ "$Y" 's/name: step10_amset, label: S8_kappa, src: step10_amset/name: step8_amset, label: S8_kappa, src: step8_amset/'
sed_ "$Y" 's|src: bandgap/step2_static|src: bandgap/step2.1_static|'
sed_ "$Y" 's|src: bandgap/step3_wavecar|src: bandgap/step2.2_wave|'
sed_ "$Y" 's|src: bandgap/step4_hse|src: bandgap/step2.3_hse|'
sed_ "$Y" 's|src: bandgap/step4_plot|src: bandgap/step2.4_gap|'
echo "== 完成 =="
