#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""gen_step9b_deform_read.py —— amset deform read → deformation.h5（step9b_deform_read）。

run:gen 步骤：在登录节点直接跑，不提交 SLURM。
把 step9_deform 的全部形变单点结果读进 deformation.h5。秒级完成。
产出：本步目录下的 deformation.h5（done_marker）。
"""
import glob
import os
import subprocess
import sys
from pathlib import Path

# =========================== 可改参数区 ===========================
OUTDIR_NAME  = "step9b_deform_read"
DEFORM_DIR   = "step9_deform"
DEFORM_GLOB  = "*deform*"
AMSET_ENV_SRC = "source /public/home/wangchao/miniconda3/etc/profile.d/conda.sh && conda activate amset_clean"
# =================================================================


def main():
    cwd = Path.cwd()
    out = cwd / OUTDIR_NAME
    out.mkdir(exist_ok=True)
    dfm = cwd / DEFORM_DIR
    if not dfm.is_dir():
        sys.exit("[ERROR] 找不到 %s（形变单点没生成？）" % dfm)

    # 校验每个形变子目录都有 vasprun.xml，否则 read 会失败或给错结果
    subs = sorted(p for p in glob.glob(str(dfm / DEFORM_GLOB)) if os.path.isdir(p))
    subs += [p for p in [str(dfm / "undeformed")] if os.path.isdir(p)]
    missing = [os.path.basename(p) for p in subs
               if not (os.path.isfile(os.path.join(p, "vasprun.xml"))
                       or os.path.isfile(os.path.join(p, "vasprun.xml.gz")))]
    if missing:
        sys.exit("[ERROR] 以下形变单点还没算完（缺 vasprun.xml）：%s\n"
                 "        等 step9_deform 全部 done 再跑本步。"
                 % ", ".join(missing[:8]))

    # amset deform read 在形变目录里跑，产出 deformation.h5，再挪到本步目录
    cmd = ("%s && cd %s && amset deform read %s undeformed "
           ">> deform_read.log 2>&1"
           % (AMSET_ENV_SRC, str(dfm), DEFORM_GLOB))
    print("[..] amset deform read ...")
    rc = subprocess.run(["bash", "-lc", cmd]).returncode
    h5 = dfm / "deformation.h5"
    if rc != 0 or not h5.is_file():
        sys.exit("[ERROR] amset deform read 失败，看 %s/deform_read.log" % dfm)
    dst = out / "deformation.h5"
    if dst.exists():
        dst.unlink()
    os.replace(str(h5), str(dst))
    print("[DONE] %s：deformation.h5 已生成" % OUTDIR_NAME)


if __name__ == "__main__":
    main()
