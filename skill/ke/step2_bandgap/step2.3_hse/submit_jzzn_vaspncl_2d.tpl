#!/bin/bash
# =====================================================================
# submit_ncl_2d.tpl —— vasp_ncl 提交模板（2D，step3/step4，SOC 非共线；optcell 补丁版）
# =====================================================================
#SBATCH --partition=cpu192
#SBATCH --job-name={{JOBNAME}}
#SBATCH --nodes=1
#SBATCH --ntasks-per-node=96
#SBATCH --output=queue.out
#SBATCH --error=queue.err
#SBATCH --qos=regular
cd $SLURM_SUBMIT_DIR
conda deactivate 2>/dev/null
conda deactivate 2>/dev/null
module purge
unset LD_LIBRARY_PATH
module load aocc/aocc-compiler-4.1.0 aocl/4.1.0 openmpi/4.1.5-aocc
ulimit -s unlimited
export OMP_NUM_THREADS=1
export OMPI_MCA_pml=ucx
export OMPI_MCA_btl=^openib,uct
export UCX_TLS=rc,sm,self
export UCX_NET_DEVICES=mlx5_0:1
mpirun -np $SLURM_NTASKS /public/home/wangchao/software/vasp.6.4.3-optcell/bin/vasp_ncl
