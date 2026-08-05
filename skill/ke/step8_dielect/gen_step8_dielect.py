#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""gen_step8_dielect.py —— DFPT 介电常数（step8_dielect）。

结构从优化结果接力，IBRION=8 + LEPSILON 一次微扰求 ε∞ 与 ε₀。
产出目录：step8_dielect/，判据看 OUTCAR 的 MACROSCOPIC STATIC DIELECTRIC TENSOR。
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
import ke_common as kc
from dim_common import require_dim  # noqa: E402

# =========================== 可改参数区 ===========================
OUTDIR_NAME  = "step8_dielect"
PREV_CANDS   = ["step1_std_opt"]
DIMENSION    = "auto"
VASPKIT_EXE  = "vaspkit"
KSCHEME      = "2"
KSPACING     = "0.04"          # DFPT 比 uniform 稍稀即可
FUNC         = "pbe"
MANUAL_ENCUT = None
ENCUT_FACTOR = 1.5
STEP_LABEL   = "S5_dielect"
# =================================================================
GGA_MAP = {"pbe": "PE", "pbesol": "PS", "pbe-d3": "PE"}

def main():
    cwd = Path.cwd(); out = cwd / OUTDIR_NAME; out.mkdir(exist_ok=True)
    prev = kc.find_prev_dir(cwd, PREV_CANDS)
    if prev is None:
        sys.exit("[ERROR] 找不到含 CONTCAR 的上一步：%s" % PREV_CANDS)
    kc.relay_poscar(prev / "CONTCAR", out / "POSCAR", "step1_std_opt")
    dim = kc.read_method_dim(prev / kc.METHOD_FILE) \
        or kc.resolve_dim_for(out / "POSCAR", DIMENSION)[0]
    _, vac_axis = kc.resolve_dim_for(out / "POSCAR", dim)
    require_dim(dim, ('2d', '3d'), "step8_dielect",
                why="DFPT 给的是介电张量；分子对应的是极化率，定义和量纲都不同")
    print("[..] 维度：%s" % dim.upper())
    kc.write_method(out / kc.METHOD_FILE, dim, "DFPT 介电常数")
    kc.vaspkit_kpoints(out, KSCHEME, KSPACING, VASPKIT_EXE, dim, vac_axis)
    kc.vaspkit_potcar(out, VASPKIT_EXE)
    encut = MANUAL_ENCUT or kc.encut_from_potcar(out / "POTCAR", ENCUT_FACTOR)
    tpl = Path(__file__).resolve().parent / ("incar_dfpt_%s.tpl" % dim)
    if not tpl.is_file():
        sys.exit("[ERROR] 找不到模板 %s" % tpl.name)
    kc.render_tpl(tpl, {"SYSTEM": cwd.name + " DFPT", "ENCUT": encut,
                        "GGA": GGA_MAP[FUNC]}, out / "INCAR")
    submit = out / "submit.sh"
    if not submit.is_file():
        sys.exit("[ERROR] submit.sh 未推送到 %s" % out)
    kc.patch_submit_jobname(submit, kc.new_jobname(cwd, STEP_LABEL))
    print("[DONE] %s：DFPT 输入就绪（KPAR=NCORE=1），可提交" % OUTDIR_NAME)

if __name__ == "__main__":
    main()
