#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""gen_step8_amset.py —— 写 settings.yaml → amset run → σ/S/κ_e（step8_amset）。

汇集前面所有产物，写 amset 的 settings.yaml，提交到计算节点跑 amset run。
输入软链：
  wavefunction.h5   ← step4_wave
  deformation.h5    ← step7b_deform_read
介电常数从 step5_dielect/OUTCAR 解析，带隙从带隙段或配置读，弹性从 step6_elastic。
产出目录：step8_amset/，产物 transport.json（判据看 thermal_conductivity）。
"""
import glob
import os
import re
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
try:
    import ke_common as kc
    _HAS_KC = True
except Exception:
    _HAS_KC = False

# =========================== 可改参数区 ===========================
OUTDIR_NAME = "step8_amset"
WAVE_DIR    = "step4_wave"
READ_DIR    = "step7b_deform_read"
DIELECT_DIR = "step5_dielect"
BANDGAP_PLOT = "step4_band_plot"      # 带隙段画图步，band_summary.json 里有 gap
STEP_LABEL  = "S8_kappa"
AMSET_CMD   = "amset run >> amset.log 2>&1 && ls -l transport.json"
# --- 输运设置（可改）---
DOPING      = "-1e21:-1e17:5, 1e17:1e21:5"   # n 型 + p 型各 5 点（对数均布）cm^-3
TEMPERATURES = "100:900:9"            # 100,200,...,900 K，每 100 K 一个点
SCATTERING  = ["ACD", "IMP", "POP"]   # 形变势声学 + 电离杂质 + 极性光学
MANUAL_BANDGAP = None                 # None=自动读；或写数值(eV) 覆盖 scissor
# --- 弹性常数来源（amset run 的 ACD 散射需要）---
#   MANUAL_ELASTIC 填了就用它，否则从 ELASTIC_DIR/OUTCAR 自动解析（kBar→GPa）。
#   直接填：单个数（各向同性近似，GPa），或 6x6 列表（完整 Cij，GPa）。
MANUAL_ELASTIC = None
ELASTIC_DIR = "step6_elastic"
# =================================================================


def read_dielectric(dielect_dir: Path):
    """从 DFPT OUTCAR 读 ε∞（电子）与 ε₀（静态）对角平均。"""
    oc = dielect_dir / "OUTCAR"
    if not oc.is_file():
        return None, None
    txt = oc.read_text(errors="ignore")
    def grab(tag):
        # 取 tag 之后第一块 3x3，对角平均
        i = txt.rfind(tag)
        if i < 0:
            return None
        rows = []
        for ln in txt[i:].splitlines()[1:]:
            nums = re.findall(r"-?\d+\.\d+", ln)
            if len(nums) >= 3:
                rows.append([float(x) for x in nums[:3]])
            if len(rows) == 3:
                break
        if len(rows) < 3:
            return None
        return round((rows[0][0] + rows[1][1] + rows[2][2]) / 3.0, 4)
    eps_inf = grab("MACROSCOPIC STATIC DIELECTRIC TENSOR (including local field effects in DFT)")
    eps_0 = grab("MACROSCOPIC STATIC DIELECTRIC TENSOR IONIC CONTRIBUTION")
    # ε₀ = 电子 + 离子
    if eps_inf is not None and eps_0 is not None:
        eps_static = round(eps_inf + eps_0, 4)
    else:
        eps_static = eps_inf
    return eps_inf, eps_static


def read_elastic(cwd: Path):
    """弹性常数来源：MANUAL_ELASTIC 优先，否则从 step6_elastic/OUTCAR 解析。
    返回 amset settings.yaml 用的值：单标量(GPa) 或 6x6 列表(GPa)，读不到返回 None。"""
    if MANUAL_ELASTIC is not None:
        return MANUAL_ELASTIC
    oc = cwd / ELASTIC_DIR / "OUTCAR"
    if not oc.is_file():
        return None
    txt = oc.read_text(errors="ignore")
    i = txt.rfind("TOTAL ELASTIC MODULI")
    if i < 0:
        return None
    rows, labels = [], ("XX", "YY", "ZZ", "XY", "YZ", "ZX")
    for ln in txt[i:].splitlines():
        p = ln.split()
        if p and p[0] in labels and len(p) >= 7:
            try:
                rows.append([float(x) for x in p[1:7]])
            except ValueError:
                pass
        if len(rows) == 6:
            break
    if len(rows) != 6:
        return None
    # VASP 输出 kBar，amset 要 GPa
    return [[round(v / 10.0, 3) for v in r] for r in rows]


def read_bandgap(cwd: Path):
    if MANUAL_BANDGAP is not None:
        return float(MANUAL_BANDGAP)
    import json
    bs = cwd / BANDGAP_PLOT / "band_summary.json"
    if bs.is_file():
        try:
            d = json.loads(bs.read_text())
            for k in ("band_gap", "bandgap", "gap", "Egap"):
                if k in d:
                    return float(d[k])
        except Exception:
            pass
    # 退回项目配置
    for cand in (cwd / "project_setting" / "setting.yaml",):
        if cand.is_file():
            for ln in cand.read_text(errors="ignore").splitlines():
                m = re.match(r"\s*bandgap\s*:\s*([\d.]+)", ln)
                if m:
                    return float(m.group(1))
    return None


def link(out: Path, src: Path, name: str):
    if not src.is_file():
        sys.exit("[ERROR] 缺 %s：%s（前置步骤没完成？）" % (name, src))
    dst = out / name
    if dst.is_symlink() or dst.exists():
        dst.unlink()
    dst.symlink_to(os.path.relpath(src, out))
    print("[OK] 软链 %s" % name)


def write_settings(out: Path, eps_inf, eps_static, gap, elastic):
    lines = ["# amset settings.yaml（gen_step10 自动生成，可手改后重跑本步）",
             "doping: [%s]" % DOPING,
             "temperatures: [%s]" % TEMPERATURES,
             "scattering_type: [%s]" % ", ".join(SCATTERING),
             "deformation_potential: deformation.h5"]
    if eps_inf is not None:
        lines.append("high_frequency_dielectric: %s" % eps_inf)
    if eps_static is not None:
        lines.append("static_dielectric: %s" % eps_static)
    if gap is not None:
        lines.append("bandgap: %s" % gap)
    if elastic is not None:
        if isinstance(elastic, (int, float)):
            lines.append("elastic_constant: %s" % elastic)   # 各向同性标量
        else:                                                # 6x6 Cij
            lines.append("elastic_constant:")
            for row in elastic:
                lines.append("  - [%s]" % ", ".join("%g" % v for v in row))
    else:
        lines.append("# elastic_constant: 未读到——step6_elastic 没算完，或手填 "
                     "MANUAL_ELASTIC。ACD 散射需要它。")
    (out / "settings.yaml").write_text("\n".join(lines) + "\n",
                                       encoding="utf-8", newline="\n")
    ela = ("标量%s" % elastic if isinstance(elastic, (int, float))
           else ("6x6" if elastic else "无"))
    print("[OK] settings.yaml：ε∞=%s ε₀=%s gap=%s 弹性=%s"
          % (eps_inf, eps_static, gap, ela))


def main():
    cwd = Path.cwd()
    out = cwd / OUTDIR_NAME
    out.mkdir(exist_ok=True)
    link(out, cwd / WAVE_DIR / "wavefunction.h5", "wavefunction.h5")
    link(out, cwd / READ_DIR / "deformation.h5", "deformation.h5")
    eps_inf, eps_static = read_dielectric(cwd / DIELECT_DIR)
    gap = read_bandgap(cwd)
    elastic = read_elastic(cwd)
    if gap is None:
        print("[WARN] 没读到带隙——settings.yaml 不写 bandgap，AMSET 会用 DFT 带隙"
              "（偏小）。带隙段关了的话请在 project_setting/setting.yaml 写 bandgap: 值")
    if elastic is None:
        print("[WARN] 没读到弹性常数——step6_elastic 没算完，或手填 MANUAL_ELASTIC。"
              "ACD 声学散射需要它。")
    write_settings(out, eps_inf, eps_static, gap, elastic)

    submit = out / "submit.sh"
    if not submit.is_file():
        sys.exit("[ERROR] submit.sh 未推送到 %s（gen_need 里要有 submit_amset.tpl）" % out)
    jobname = ("%s-ke-%s" % (cwd.name, STEP_LABEL)) if not _HAS_KC \
        else kc.new_jobname(cwd, STEP_LABEL)
    text = submit.read_text(encoding="utf-8")
    text = text.replace("{{JOBNAME}}", jobname).replace("{{AMSET_CMD}}", AMSET_CMD)
    submit.write_text(text, encoding="utf-8", newline="\n")
    print("[DONE] %s：settings.yaml + 软链就绪，提交后 amset run 产出 transport.json"
          % OUTDIR_NAME)


if __name__ == "__main__":
    main()
