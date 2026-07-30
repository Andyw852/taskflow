#!/bin/bash
# =====================================================================
# submit_ncl_3d.tpl —— vasp_ncl 提交模板（3D，step3/step4，SOC 非共线；官方 VASP）
# 集群参数在此模板中直接写死；换机器/换队列/换 VASP 时只改本文件。
# 脚本只填充 JOBNAME 占位符（按体系与步骤自动生成，可用 --jobname 覆盖）。
# =====================================================================
#SBATCH --partition=cpu192
#SBATCH --job-name={{JOBNAME}}
#SBATCH --nodes=1
#SBATCH --ntasks-per-node=96
#SBATCH --output=queue.out
#SBATCH --error=queue.err
#SBATCH --qos=premium

cd $SLURM_SUBMIT_DIR

# 清掉 conda（它的 MKL 会劫持库）和残留环境
conda deactivate 2>/dev/null
conda deactivate 2>/dev/null
module purge
unset LD_LIBRARY_PATH

# 清空位置参数，否则 setvars.sh 会把 SLURM 传进来的东西当选项、只打印帮助后退出
set --
source /public/software/intel/2022.3/setvars.sh --force > /dev/null 2>&1

# 官方 VASP 6.4.3（与 oneAPI 2022.3 配套；非共线/SOC 用 vasp_ncl）
module load vasp/6.4.3-oneapi2022.3
export OMP_NUM_THREADS=1

mpirun -np $SLURM_NTASKS vasp_ncl
