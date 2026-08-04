#!/bin/bash
# ShengBTE BTE 提交模板（step6_kappa, solver=shengbte）。占位符 {{JOBNAME}} {{SHENGBTE_EXE}}
# 需先备好 CONTROL + FORCE_CONSTANTS_2ND/3RD（见 gen_step6 提示：建议 METHOD=alm）。
#SBATCH --partition=cpu192
#SBATCH --job-name={{JOBNAME}}
#SBATCH --nodes=1
#SBATCH --ntasks-per-node=48
#SBATCH --output=queue.out
#SBATCH --error=queue.err
#SBATCH --qos=premium
cd $SLURM_SUBMIT_DIR
source /public/home/wangchao/miniconda3/etc/profile.d/conda.sh
conda activate atomate2_p_a
mpirun -np $SLURM_NTASKS {{SHENGBTE_EXE}} 2>&1 | tee shengbte.log
if [ -f BTE.kappa_tensor ]; then
  python - <<'PY'
import json
rows=[l.split() for l in open('BTE.kappa_tensor') if l.strip() and not l.startswith('#')]
d={'KAPPA_DONE':bool(rows)}
if rows:
    d['temperatures']=[float(r[0]) for r in rows]
    d['kappa_xx']=[float(r[1]) for r in rows]
json.dump(d,open('kappa_summary.json','w'),ensure_ascii=False,indent=2)
print('KAPPA_DONE' if rows else 'NO_KAPPA')
PY
fi
