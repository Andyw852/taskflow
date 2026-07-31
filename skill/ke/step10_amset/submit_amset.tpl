#!/bin/bash
# =====================================================================
# submit_amset.tpl —— AMSET 命令行步骤的提交模板（step4_wave / step8_amset）
#
# 与 submit_std_*.tpl 的区别：不跑 mpirun vasp，而是在 amset_clean 环境里
# 跑 amset 命令行。真正的命令由各步的 gen 脚本填进 {{AMSET_CMD}}。
#
# 集群参数写死在本文件；换机器/换队列只改这里。
# gen 脚本负责替换：{{JOBNAME}}  {{AMSET_CMD}}
# =====================================================================
#SBATCH --partition=cpu192
#SBATCH --job-name={{JOBNAME}}
#SBATCH --nodes=1
#SBATCH --ntasks-per-node=48
#SBATCH --output=queue.out
#SBATCH --error=queue.err
#SBATCH --qos=premium

cd $SLURM_SUBMIT_DIR

# --- amset 环境 ------------------------------------------------------
# 注意：非交互 shell 里 conda activate 需要先 source conda.sh，
# 直接写 `conda activate` 会报 "CommandNotFoundError: Your shell has not
# been properly configured to use 'conda activate'"。
source /public/home/wangchao/miniconda3/etc/profile.d/conda.sh
conda activate amset_clean

# 防止 amset 内部的 BLAS 线程与 SLURM 分配打架
export OMP_NUM_THREADS=1
export OPENBLAS_NUM_THREADS=1
export MKL_NUM_THREADS=1

echo "[amset] env=$CONDA_DEFAULT_ENV  which=$(which amset)"
amset --version || true

# --- 本步骤要执行的 amset 命令（由 gen 脚本填充）----------------------
{{AMSET_CMD}}
