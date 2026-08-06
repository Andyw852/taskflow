# -*- coding: utf-8 -*-
"""ke_common.py —— ke 技能新步骤（uniform / dfpt / deform / amset）的公共工具。

只依赖标准库 + dim_common（同目录，setup 已放好）。故意不碰 pymatgen，
让 gen 脚本在登录节点用系统 python 就能跑。VASPKIT 负责 KPOINTS/POTCAR。

放置：由 skill.yaml 的 gen_need 列出，随每个用它的步骤推到材料目录。
      ——因此本文件要复制进每个用到它的步骤源目录（step3_uniform、
        step5_dielect、step7_deform）。见 setup_ke.sh。
"""
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from dim_common import (detect_dimension, force_kz1, validate_poscar,  # noqa: E402
                        VACUUM_MIN)

METHOD_FILE = "workflow_method.txt"


# --------------------------------------------------------------------------
# 维度
# --------------------------------------------------------------------------
def resolve_dim_for(poscar: Path, dimension="auto", vacuum_min=VACUUM_MIN):
    """返回 (dim, vac_axis)。dim ∈ {'2d','3d'}；vac_axis 仅 2D 有意义。"""
    mode = str(dimension).lower()
    if mode in ("2d", "3d"):
        return mode, (2 if mode == "2d" else None)
    dim, axis, vacs = detect_dimension(poscar, vacuum_min)
    if dim == "2d" and axis != 2:
        sys.exit("[ERROR] 检测到 2D 但真空不在 c 轴（在 %d 轴）。请把结构旋转成"
                 "真空沿第 3 个晶格矢量再重跑。" % axis)
    return dim, (axis if dim == "2d" else None)


def read_method_dim(method_file: Path):
    """从上一步的 workflow_method.txt 读 DIM=2D/3D（有就返回 '2d'/'3d'，无返回 None）。"""
    if not method_file.is_file():
        return None
    for ln in method_file.read_text(errors="ignore").splitlines():
        if ln.strip().upper().startswith("DIM="):
            v = ln.split("=", 1)[1].strip().lower()
            if v in ("2d", "3d"):
                return v
    return None


def write_method(path: Path, dim: str, note: str):
    path.write_text("DIM=%s\n# %s\n" % (dim.upper(), note),
                    encoding="utf-8", newline="\n")


# --------------------------------------------------------------------------
# VASPKIT：KPOINTS / POTCAR / ENCUT
# --------------------------------------------------------------------------
def vaspkit_kpoints(outdir: Path, kscheme="2", kspacing="0.03",
                    exe="vaspkit", dim="3d", vac_axis=2, force_kz1_2d=True):
    """VASPKIT 1→102→scheme→kspacing 生成 KPOINTS；2D 把真空方向细分压回 1。"""
    print("[..] VASPKIT KPOINTS：1 -> 102 -> %s -> %s" % (kscheme, kspacing))
    subprocess.run([exe], input="1\n102\n%s\n%s\n" % (kscheme, kspacing),
                   text=True, cwd=outdir, check=True)
    if dim == "2d" and force_kz1_2d:
        changed, note = force_kz1(outdir / "KPOINTS", axis=vac_axis if vac_axis is not None else 2)
        print("[%s] 2D KPOINTS 真空方向细分：%s" % ("OK" if changed else "..", note))


def vaspkit_potcar(outdir: Path, exe="vaspkit"):
    if (outdir / "POTCAR").exists():
        print("[OK] POTCAR 已存在，跳过")
        return
    print("[..] VASPKIT POTCAR：1 -> 103")
    subprocess.run([exe], input="1\n103\n", text=True, cwd=outdir, check=True)


def encut_from_potcar(potcar: Path, factor=1.5, fallback=300):
    vals = []
    for ln in potcar.read_text(errors="ignore").splitlines():
        m = re.search(r"ENMAX\s*=\s*([\d.]+)", ln)
        if m:
            vals.append(float(m.group(1)))
    if not vals:
        return int(fallback)
    import math
    return int(math.ceil(max(vals) * factor / 10.0) * 10)


# --------------------------------------------------------------------------
# INCAR 模板渲染 + 键改写
# --------------------------------------------------------------------------
def render_tpl(tpl_path: Path, subs: dict, out_path: Path):
    """把模板里的 {{KEY}} 占位符替换成 subs[KEY]，写出。"""
    text = tpl_path.read_text(encoding="utf-8")
    for k, v in subs.items():
        text = text.replace("{{%s}}" % k, str(v))
    left = re.findall(r"\{\{([A-Z_]+)\}\}", text)
    if left:
        sys.exit("[ERROR] 模板 %s 还有未填占位符：%s" % (tpl_path.name, ", ".join(set(left))))
    out_path.write_text(text, encoding="utf-8", newline="\n")
    print("[OK] %s" % out_path.name)


def parse_incar(text: str):
    d = {}
    for ln in text.splitlines():
        ln = ln.split("#", 1)[0].split("!", 1)[0].strip()
        if "=" in ln:
            k, v = ln.split("=", 1)
            d[k.strip().upper()] = v.strip()
    return d


def incar_text(d: dict, system="calc"):
    out = ["SYSTEM = %s" % system, ""]
    for k, v in d.items():
        if k == "SYSTEM":
            continue
        out.append("%-10s = %s" % (k, v))
    return "\n".join(out) + "\n"


def merge_incar(base: dict, overrides: dict):
    """overrides 里 value 为 None 表示删除该键。"""
    d = dict(base)
    for k, v in overrides.items():
        k = k.upper()
        if v is None:
            d.pop(k, None)
        else:
            d[k] = str(v)
    return d


# --------------------------------------------------------------------------
# 结构接力
# --------------------------------------------------------------------------
def relay_poscar(prev_contcar: Path, dst_poscar: Path, label="上一步"):
    """把上一步 CONTCAR 拷成本步 POSCAR；缺失就报错退出（绝不静默用旧结构）。"""
    if not prev_contcar.is_file():
        sys.exit("[ERROR] %s 的 CONTCAR 不存在：%s\n"
                 "        请确认上一步已完成再生成本步。" % (label, prev_contcar))
    validate_poscar(prev_contcar)
    shutil.copyfile(prev_contcar, dst_poscar)
    print("[OK] POSCAR ← %s" % prev_contcar)


def find_prev_dir(cwd: Path, candidates):
    """按顺序找第一个存在且有 CONTCAR 的目录名。"""
    for name in candidates:
        d = cwd / name
        if (d / "CONTCAR").is_file():
            return d
    return None


def new_jobname(cwd: Path, step_label: str):
    return "%s-ke-%s" % (cwd.name, step_label)


def patch_submit_jobname(submit: Path, jobname: str):
    text = submit.read_text(encoding="utf-8")
    text = text.replace("{{JOBNAME}}", jobname)
    submit.write_text(text, encoding="utf-8", newline="\n")
