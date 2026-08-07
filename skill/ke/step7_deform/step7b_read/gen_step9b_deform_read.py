#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""gen_step7b_deform_read.py —— amset deform read → deformation.h5（step7b_deform_read）。

run:gen 步骤：在登录节点直接跑，不提交 SLURM。
把 step7_deform 的全部形变单点结果读进 deformation.h5。秒级完成。
产出：本步目录下的 deformation.h5（done_marker）。
"""
import glob
import os
import subprocess
import sys
from pathlib import Path

# =========================== 可改参数区 ===========================
OUTDIR_NAME  = "step7b_deform_read"
DEFORM_DIR   = "step7_deform"
# patch_deform_fix：只匹配形变目录。绝不能用 "*deform*"——它会把
# "undeformed" 自己也匹配进去，undeformed 必须单独作为 bulk 传给 read。
DEFORM_GLOB  = "deform-*"
AMSET_ENV_SRC = "source /public/home/wangchao/miniconda3/etc/profile.d/conda.sh && conda activate amset_clean"
# =================================================================


# patch_dim_guard：本步不跑 VASP、也不解析结构，所以没有 dim 变量可用。
# 直接从 step1 的 workflow_method.txt 读 DIM=，0D 就带原因退出，
# 免得 -f 强推时抛一句看不懂的"缺 xxx.h5"。
_STEP1_CANDS = ("step1_opt", "step1_std_opt",
                "step1c_PBE_opt", "step1b_PBE_opt", "step1a_PBE_opt")


def _guard_not_0d(cwd, step_name, why):
    from pathlib import Path as _P
    for name in _STEP1_CANDS:
        mf = _P(cwd) / name / "workflow_method.txt"
        if not mf.is_file():
            continue
        for ln in mf.read_text(errors="ignore").splitlines():
            if ln.strip().upper().startswith("DIM="):
                dim = ln.split("=", 1)[1].strip().lower()
                if dim == "0d":
                    sys.exit("[ERROR] %s 不支持 0D 体系。\n"
                             "        原因：%s\n"
                             "        支持的维度：2D, 3D\n"
                             "        若判定有误，检查 %s 的 DIM=。"
                             % (step_name, why, mf))
                return
        return


def main():
    cwd = Path.cwd()
    out = cwd / OUTDIR_NAME
    out.mkdir(exist_ok=True)
    _guard_not_0d(cwd, "step7b_deform_read",
                  "形变势是能带对应变的响应，孤立分子没有能带色散")
    dfm = cwd / DEFORM_DIR
    if not dfm.is_dir():
        sys.exit("[ERROR] 找不到 %s（形变单点没生成？）" % dfm)

    # 校验每个形变子目录都有 vasprun.xml，否则 read 会失败或给错结果
    subs = sorted(p for p in glob.glob(str(dfm / DEFORM_GLOB)) if os.path.isdir(p))
    und = str(dfm / "undeformed")
    if not os.path.isdir(und):
        sys.exit("[ERROR] 缺 %s —— 它是形变势的参考态，没有它 read 无法对齐"
                 % und)
    subs.append(und)
    if not [p for p in subs if p != und]:
        sys.exit("[ERROR] %s 下没有 deform-* 子目录（step7 没跑或跑挂了）" % dfm)
    missing = [os.path.basename(p) for p in subs
               if not (os.path.isfile(os.path.join(p, "vasprun.xml"))
                       or os.path.isfile(os.path.join(p, "vasprun.xml.gz")))]
    if missing:
        sys.exit("[ERROR] 以下形变单点还没算完（缺 vasprun.xml）：%s\n"
                 "        等 step7_deform 全部 done 再跑本步。"
                 % ", ".join(missing[:8]))

    # amset deform read 在形变目录里跑，产出 deformation.h5，再挪到本步目录
    # patch_deform_fix：amset 的签名是 read(bulk_folder, deformation_folders...)，
    # 【未形变的必须排第一个】。原来写成 `read *deform* undeformed`，既顺序
    # 颠倒，又因为 "*deform*" 会匹配到 "undeformed" 自己，把第一个形变目录
    # 当成了 bulk。这个错不报异常，只会安静地给出错误的形变势。
    cmd = ("%s && cd %s && amset deform read undeformed %s "
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
