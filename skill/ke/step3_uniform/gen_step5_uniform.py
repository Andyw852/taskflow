#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""gen_step3_uniform.py —— AMSET uniform 密网格自洽（step3_uniform）。

在材料目录下运行，从结构优化结果接力：
  1. POSCAR ← step1_std_opt/CONTCAR
  2. VASPKIT 生成密 KPOINTS（kspacing 见下）+ POTCAR
  3. 按 2D/3D 渲染 incar_uniform_*.tpl，产出 WAVECAR 供 amset wave
产出目录：step3_uniform/
"""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import ke_common as kc
from dim_common import require_dim, resolve_tpl  # noqa: E402

# =========================== 可改参数区 ===========================
OUTDIR_NAME  = "step3_uniform"
PREV_CANDS   = ["step1_opt", "step1_std_opt"]      # 结构来源（找第一个有 CONTCAR 的）
DIMENSION    = "auto"                 # auto | 2d | 3d
VASPKIT_EXE  = "vaspkit"
KSCHEME      = "2"                    # 2 = Γ 心
KSPACING     = "0.03"                 # ★AMSET 密网格；要更密改这里
FUNC         = "pbe"                  # pbe | pbesol | pbe-d3
MANUAL_ENCUT = None                   # None=从 POTCAR 自动；或写数值
ENCUT_FACTOR = 1.5
STEP_LABEL   = "S3_uniform"
# =================================================================

GGA_MAP = {"pbe": "PE", "pbesol": "PS", "pbe-d3": "PE"}


def main():
    cwd = Path.cwd()
    out = cwd / OUTDIR_NAME
    out.mkdir(exist_ok=True)

    prev = kc.find_prev_dir(cwd, PREV_CANDS)
    if prev is None:
        sys.exit("[ERROR] 找不到含 CONTCAR 的上一步目录：%s" % PREV_CANDS)
    kc.relay_poscar(prev / "CONTCAR", out / "POSCAR", "step1_opt")

    dim = kc.read_method_dim(prev / kc.METHOD_FILE)
    if dim is None:
        dim, vac_axis = kc.resolve_dim_for(out / "POSCAR", DIMENSION)
    else:
        _, vac_axis = kc.resolve_dim_for(out / "POSCAR", dim)
        require_dim(dim, ('2d', '3d'), "step3_uniform",
                    why="载流子输运/形变势建立在能带色散上，孤立分子没有色散")
    print("[..] 维度：%s" % dim.upper())
    kc.write_method(out / kc.METHOD_FILE, dim, "uniform 密网格自洽")

    kc.vaspkit_kpoints(out, KSCHEME, KSPACING, VASPKIT_EXE, dim, vac_axis)
    kc.vaspkit_potcar(out, VASPKIT_EXE)

    encut = MANUAL_ENCUT or kc.encut_from_potcar(out / "POTCAR", ENCUT_FACTOR)
    tpl = Path(__file__).resolve().parent / ("incar_uniform_%s.tpl" % dim)
    if not tpl.is_file():
        sys.exit("[ERROR] 找不到模板 %s" % tpl.name)
    system = cwd.name + " uniform"
    kc.render_tpl(tpl, {"SYSTEM": system, "ENCUT": encut, "GGA": GGA_MAP[FUNC]},
                  out / "INCAR")

    submit_tpl = resolve_tpl(Path(__file__).resolve().parent, "submit_std", dim)
    submit = out / "submit.sh"
    submit.write_text(submit_tpl.read_text(encoding="utf-8"), encoding="utf-8", newline="\n")
    kc.patch_submit_jobname(submit, kc.new_jobname(cwd, STEP_LABEL))

    print("[DONE] %s：INCAR/KPOINTS/POTCAR/POSCAR 就绪，可提交" % OUTDIR_NAME)


if __name__ == "__main__":
    main()
