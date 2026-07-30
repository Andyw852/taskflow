#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
gen_step2_elastic.py — 弹性/力学性能流程 step2：弹性常数（VASP 有限差分 IBRION=6）

沿用 gen_step2_static 的"继承 step1 INCAR + 改写"套路：自动继承 ENCUT / GGA / IVDW /
ISPIN / MAGMOM / LMAXMIX / LDAU*，只注入 IBRION=6 弹性标签，与 step1 完全一致。
方法（泛函）与维度（2D/3D）从 step1 的 workflow_method.txt 继承。

OUTCAR 中 TOTAL ELASTIC MODULI = clamped-ion + 离子弛豫贡献 ← step3 取这个。
并行：IBRION=6 有限差分对并行敏感，NCORE=1（=NPAR ranks）最稳妥，KPAR 继承 step1。
2D：删 IOPTCELL（弹性形变要作用到面内所有分量，不能再锁胞；N/m 换算在 step3）。

用法（在材料父目录运行）：
    python gen_step2_elastic.py
    python gen_step2_elastic.py --no-vaspkit
    python gen_step2_elastic.py --potim 0.010 --nfree 2      # CLI 覆盖配置区默认值
"""
import argparse
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from dim_common import force_kz1, resolve_dim, resolve_tpl, validate_poscar  # noqa: E402

# =====================================================================
#                           用户配置区
#   （改这里即可调整注入参数；CLI 同名参数可临时覆盖，缺省即取此处值）
# =====================================================================

# ---- IBRION=6 有限差分弹性参数 ----
POTIM   = "0.015"      # 形变（应变）幅度
NFREE   = "4"          # 每个独立应变的差分点数：2 或 4（4=四点中心差分，更准）
EDIFF   = "1E-7"       # 电子自洽收敛（弹性对精度敏感）
PREC    = "Accurate"
NCORE_ELASTIC = "1"    # 有限差分并行安全值（=NPAR ranks）；KPAR 继承 step1

# ---- KPOINTS（VASPKIT；弹性比静态更密）----
RUN_VASPKIT = True
VASPKIT_EXE = "vaspkit"
KSCHEME  = "2"         # 1=Monkhorst-Pack, 2=Gamma-centered
KSPACING = "0.02"      # 倒空间 K 点间距（static 用 0.03，弹性更密）

# ---- 在"继承 step1 + 上面注入"之外，额外增删的 INCAR 标签 ----
# 例：INCAR_SET_EXTRA = {"ALGO": "Normal", "SYMPREC": "1E-5"}
INCAR_SET_EXTRA    = {}
INCAR_REMOVE_EXTRA = []     # 例：["LDIPOL", "IDIPOL"]

# ---- submit.sh Slurm 参数覆盖（渲染模板后再补丁；None=不改，保持模板原值）----
SUBMIT_OVERRIDE = {
    "nodes":           None,
    "ntasks_per_node": None,
    "qos":             None,
}

# =====================================================================
#                         用户配置区结束
# =====================================================================

STEP1_DIR = "step1_std_opt"
STEP2_DIR = "step7_elastic"   # ke：改名避免和带隙段 step2_* 混淆
INCAR_FILE = "INCAR"
POTCAR_FILE = "POTCAR"
METHOD_FILE = "workflow_method.txt"

# 弛豫专用、不应带进弹性步的标签（IBRION/ISIF/POTIM/NSW 会被注入值覆盖）
INCAR_REMOVE_BASE = {"EDIFFG", "IOPTCELL", "LORBIT", "IBRION", "ISIF", "POTIM", "NSW"}


def parse_args():
    p = argparse.ArgumentParser(description="Generate step2 IBRION=6 elastic inputs")
    p.add_argument("--vaspkit", default=VASPKIT_EXE)
    p.add_argument("--no-vaspkit", action="store_true",
                   help="复用 step1 KPOINTS 而非重新生成")
    p.add_argument("--kscheme", default=KSCHEME)
    p.add_argument("--kspacing", default=KSPACING)
    p.add_argument("--potim", default=POTIM, help="有限差分应变幅度")
    p.add_argument("--nfree", default=NFREE, choices=["2", "4"])
    p.add_argument("--jobname", default=None)
    return p.parse_args()


def sanitize_label(text):
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", text.strip()).strip("_.-") or "material"


def read_structure_label(path):
    lines = path.read_text(encoding="utf-8-sig").splitlines()
    if not lines:
        return "material"
    token = lines[0].split()[0] if lines[0].split() else "material"
    return sanitize_label(token)


def parse_incar(path):
    items = []
    for line in open(path):
        s = line.strip()
        if not s or s[0] in "#!":
            continue
        for marker in ("#", "!"):
            if marker in s:
                s = s.split(marker, 1)[0].strip()
        if "=" not in s:
            continue
        for part in s.split(";"):
            if "=" in part:
                key, value = part.split("=", 1)
                items.append((key.strip().upper(), value.strip()))
    return items


def build_incar(src_items, remove, set_values):
    """透传 step1 INCAR：删 remove、改 set，SYSTEM 单列。与 gen_step2_static 同实现。"""
    remove = {k.upper() for k in remove}
    set_values = {k.upper(): v for k, v in set_values.items()}
    body, seen = [], set()
    for key, value in src_items:
        if key in remove or key == "SYSTEM":
            continue
        body.append((key, set_values.get(key, value)))
        seen.add(key)
    for key, value in set_values.items():
        if key != "SYSTEM" and key not in seen:
            body.append((key, value))
    lines = [f"SYSTEM = {set_values['SYSTEM']}"]
    lines.extend(f"{key:<8s} = {value}" for key, value in body)
    return "\n".join(lines) + "\n"


def render_submit(tpl_path, out_path, params):
    if not os.path.exists(tpl_path):
        raise SystemExit(f"[ERROR] 缺少 submit 模板: {tpl_path}")
    text = Path(tpl_path).read_text(encoding="utf-8")
    for key, value in params.items():
        text = text.replace("{{" + key + "}}", str(value))
    leftover = set(re.findall(r"\{\{(\w+)\}\}", text))
    if leftover:
        raise SystemExit(f"[ERROR] {tpl_path} 有未填充占位符: {leftover}（本脚本只填 JOBNAME）")
    Path(out_path).write_text(text, encoding="utf-8", newline="\n")


def _patch_sbatch_param(text, flag, value):
    pat = re.compile(r"^(#SBATCH\s+--%s=)\S+.*$" % re.escape(flag), re.MULTILINE)
    if pat.search(text):
        return pat.sub(r"\g<1>%s" % value, text), True
    return text, False


def override_submit_slurm(submit_path, override):
    text = Path(submit_path).read_text(encoding="utf-8")
    changed = []
    for key, flag in [("nodes", "nodes"), ("ntasks_per_node", "ntasks-per-node"), ("qos", "qos")]:
        val = override.get(key)
        if val is None:
            continue
        text, ok = _patch_sbatch_param(text, flag, val)
        changed.append("--%s=%s" % (flag, val) if ok else "[未写入 --%s]" % flag)
    Path(submit_path).write_text(text, encoding="utf-8", newline="\n")
    if changed:
        print("[..] submit.sh 覆盖 Slurm 参数：%s" % ", ".join(changed))


def run_vaspkit_kpoints(exe, outdir, kscheme, kspacing):
    print(f"[..] VASPKIT KPOINTS: 1 -> 102 -> {kscheme} -> {kspacing}")
    subprocess.run([exe], input=f"1\n102\n{kscheme}\n{kspacing}\n",
                   text=True, cwd=outdir, check=True)


def main():
    args = parse_args()
    step1, step2 = Path(STEP1_DIR), Path(STEP2_DIR)
    if not step1.is_dir():
        sys.exit(f"[ERROR] 缺少 {STEP1_DIR}；请在材料父目录运行")

    incar_path = step1 / INCAR_FILE
    if not incar_path.exists():
        sys.exit(f"[ERROR] 缺少 {incar_path}")

    struct = next((step1 / n for n in ("CONTCAR", "POSCAR") if (step1 / n).exists()), None)
    if struct is None:
        sys.exit(f"[ERROR] {STEP1_DIR} 里没有 CONTCAR/POSCAR")
    # v1.3：接力结构完整性校验——step1 还在跑时 CONTCAR 只写了一半，
    # 直接拷给 step2 会让 vaspkit 读文件崩（forrtl end-of-file）
    bad = validate_poscar(struct)
    if bad:
        sys.exit(f"[ERROR] {struct} 不完整：{bad}\n"
                 "        step1 优化很可能还在跑（CONTCAR 写了一半）——\n"
                 "        等 tf 里 S1_opt 变 done 再生成 S2；强行用半成品结构算弹性没有意义。")
    if struct.name != "CONTCAR":
        print("[WARN] step1 无 CONTCAR，改用 step1 POSCAR（弛豫可能未完成）")

    items = parse_incar(incar_path)
    label = read_structure_label(struct)
    step2.mkdir(exist_ok=True)
    Path(step2 / "POSCAR").write_text(struct.read_text(encoding="utf-8-sig"),
                                      encoding="utf-8", newline="\n")

    # 维度继承（step1 workflow_method.txt 的 DIM=；缺失按结构判定）
    dim, dim_note = resolve_dim(step1 / METHOD_FILE, step2 / "POSCAR")
    submit_tpl = resolve_tpl(Path.cwd(), "submit_std", dim)
    print(f"[..] 维度：{dim.upper()} — {dim_note}")
    print(f"[..] 提交模板：{submit_tpl.name}")
    if dim == "2d":
        print("[..] 2D：删除 IOPTCELL（IBRION=6 需对面内所有分量施应变）；"
              "面内刚度 N/m 换算在 step3 完成")

    # POTCAR 继承 step1
    potcar_src = step1 / POTCAR_FILE
    if not potcar_src.exists():
        sys.exit(f"[ERROR] 缺少 {potcar_src}")
    shutil.copyfile(potcar_src, step2 / POTCAR_FILE)

    # KPOINTS
    if args.no_vaspkit or not RUN_VASPKIT:
        old = step1 / "KPOINTS"
        if not old.exists():
            sys.exit("[ERROR] 未启用 VASPKIT 但 step1 无 KPOINTS")
        shutil.copyfile(old, step2 / "KPOINTS")
        print("[WARN] 复用 step1 KPOINTS；弹性建议重新加密")
    else:
        try:
            run_vaspkit_kpoints(args.vaspkit, step2, args.kscheme, args.kspacing)
            if dim == "2d":
                changed, note = force_kz1(step2 / "KPOINTS")
                print(f"[{'OK' if changed else '..'}] 2D KPOINTS 真空方向细分：{note}")
        except FileNotFoundError:
            sys.exit(f"[ERROR] 找不到 VASPKIT：{args.vaspkit}")
        except subprocess.CalledProcessError as exc:
            sys.exit(f"[ERROR] VASPKIT 失败，returncode={exc.returncode}")

    # submit.sh（弹性用 vasp_std）
    jobname = args.jobname or sanitize_label(f"{label}_s2elastic")[:80]
    render_submit(str(submit_tpl), step2 / "submit.sh", {"JOBNAME": jobname})
    override_submit_slurm(step2 / "submit.sh", SUBMIT_OVERRIDE)

    # INCAR：继承 step1 + 注入 IBRION=6（含配置区的额外增删）
    incar_set = {
        "SYSTEM":  f"{label} elastic IBRION6 (step2)",
        "IBRION":  "6",
        "ISIF":    "3",
        "NFREE":   args.nfree,
        "POTIM":   args.potim,
        "NSW":     "1",
        "EDIFF":   EDIFF,
        "PREC":    PREC,
        "NCORE":   NCORE_ELASTIC,
        "LWAVE":   ".FALSE.",
        "LCHARG":  ".FALSE.",
        "ADDGRID": ".TRUE.",
        "LREAL":   ".FALSE.",
    }
    incar_set.update({k.upper(): v for k, v in INCAR_SET_EXTRA.items()})
    # ISYM 不强灌（v2.0 审查修复）：LDIPOL/LCALCPOL 打开时必须 0（偶极/铁电体系，
    # 对称性与偶极校正冲突）；step1 显式设过就继承；都没设才补 2
    # （IBRION=6 开对称性可减少一半形变计算量）
    base_kv = {k.upper(): str(v) for k, v in items}
    if base_kv.get("LDIPOL", "").upper() in (".TRUE.", "T", "TRUE", "1") or \
       base_kv.get("LCALCPOL", "").upper() in (".TRUE.", "T", "TRUE", "1"):
        incar_set["ISYM"] = "0"
    elif "ISYM" not in base_kv:
        incar_set["ISYM"] = "2"
    incar_remove = set(INCAR_REMOVE_BASE) | {k.upper() for k in INCAR_REMOVE_EXTRA}
    text = build_incar(items, incar_remove, incar_set)
    (step2 / "INCAR").write_text(text, encoding="utf-8", newline="\n")
    print(f"[OK] INCAR（IBRION=6, POTIM={args.potim}, NFREE={args.nfree}, NCORE={NCORE_ELASTIC}）")

    if (step1 / METHOD_FILE).exists():
        shutil.copyfile(step1 / METHOD_FILE, step2 / METHOD_FILE)

    print("\n文件检查：")
    for name in ["POSCAR", "INCAR", "submit.sh", "KPOINTS", "POTCAR", METHOD_FILE]:
        print(f"[{'OK' if (step2 / name).exists() else 'MISSING'}] {name}")
    print("\n[DONE] step2_elastic 已生成，可用 vasp_std 提交")


if __name__ == "__main__":
    main()
