#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
gen_step1_PBE_opt.py
====================
用于层状 M2X2Te5 体系的体相结构优化输入生成。

与旧版的两点区别
----------------
1. Slurm 参数（partition / nodes / ntasks / qos / VASP 路径）已全部固化在
   submit_std.tpl 里，本脚本只填充 {{JOBNAME}}。换机器直接改模板。
2. incar.tpl 是通用模板：脚本只负责 4 个"计算得来"的占位符
   （SYSTEM / ENCUT / GGA / VDW_LINE），且"模板里有才填、没有就跳过"。
   其余任何 VASP 参数在模板里自由增删，脚本不需要改动。

使用方法：
    1. 在下方"用户配置区"设置 FUNC（pbe-d3 / pbesol / pbe）。
    2. 确保当前目录存在：POSCAR, incar.tpl, submit_std.tpl
    3. 直接运行：python gen_step1_PBE_opt.py

脚本会：
    - 自动识别 POSCAR 标题/化学式；
    - 生成 step1_PBE_opt/；
    - 调用 VASPKIT 生成 KPOINTS 和 POTCAR；
    - 根据 POTCAR 最大 ENMAX 自动设置 ENCUT；
    - 写入 workflow_method.txt，供后续步骤继承泛函。
"""

import math
import os
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from dim_common import (AXIS_NAMES, detect_dimension, force_kz1,  # noqa: E402
                        resolve_tpl, validate_poscar)

# =====================================================================
#                           用户配置区
# =====================================================================

# 结构优化泛函，三选一：
#   "pbe-d3" : PBE + DFT-D3(BJ)，自动写入 GGA=PE、IVDW=12
#   "pbesol" : PBEsol，不启用经验色散修正，自动写入 GGA=PS
#   "pbe"    : 纯 PBE，无色散修正，自动写入 GGA=PE
FUNC = "pbesol"

# VASPKIT 设置
RUN_VASPKIT = True
VASPKIT_EXE = "vaspkit"
KSCHEME = "2"       # VASPKIT: 1=Monkhorst-Pack, 2=Gamma-centered
KSPACING = "0.03"   # VASPKIT 倒空间 K 点间距

# ---- 维度自动识别（2D / 3D）----
# "auto": 按 POSCAR 真空层判定 —— 沿某晶轴的最大真空间隙 >= VACUUM_MIN 即认定 2D。
#         判定结果决定用哪套模板（在父目录按后缀选取，缺失时回退到无后缀旧名）：
#             2D -> incar_2d.tpl + submit_std_2d.tpl   3D -> incar_3d.tpl + submit_std_3d.tpl
#         并把 DIM=2D/3D 写进 workflow_method.txt，step2/3/4 据此选各自的
#         submit_std_* / submit_ncl_* 模板，全程无需人工切换。
#         检出 >=2 个真空方向（1D/0D）会直接报错交人工。
# "2d" / "3d": 强制指定，跳过检测。
DIMENSION = "auto"
VACUUM_MIN = 8.0     # Å；2D 常用真空 15~25 Å，8 Å 足以与层状体相的层间距区分

# 2D 时变胞约束的实现流派（务必与所用 VASP 二进制匹配！两种补丁互不兼容）：
#   "optcell_file" : 补丁读运行目录下的 OPTCELL 文件（submit_std_2d.tpl 注释所述、
#                    vasp.6.4.3-optcell 的流派）。脚本会把 INCAR 里的 IOPTCELL 行
#                    转换成 OPTCELL 文件并【删除该行】—— VASP>=6.2 遇到不认识的
#                    INCAR 标签会直接罢工，留着它反而跑不起来。
#   "ioptcell_tag" : 补丁读 INCAR 的 IOPTCELL 标签，原样保留，不写 OPTCELL 文件。
#   "none"         : 两者都不做（自行处理，如 ISIF=2 + 能量-面积扫描）。
CELL_CONSTRAINT_2D = "ioptcell_tag"

# ###################################################################
# ★ 三段式结构优化 ★
# ###################################################################
# 为什么要分段：一上来就 ISIF=3 + CG，离子位置和晶胞两组自由度耦合在一起，
# CG 的线搜索会同时试探原子位移和晶格应变，很容易在一次 trial step 里把结构
# 甩出去（OSZICAR 上表现为能量一步涨好几 eV，然后来回震荡耗光 NSW）。
# 拆开之后每一段只解一个问题，收敛快且稳：
#
#   a  ISIF=2  IBRION=2  (2D 去掉 IOPTCELL)  固定胞，先把原子弛豫干净
#   b  ISIF=3  IBRION=2  (2D 加 IOPTCELL)    放开面内 xx/yy/xy，c 冻结
#   c  ISIF=3  IBRION=1  (2D 加 IOPTCELL)    近极小值改准牛顿，收尾比 CG 快得多
#
# 3D 完全一样，只是三段都没有 IOPTCELL（整个胞自由弛豫）。
#
# 用法：
#   python gen_step1_PBE_opt.py                 自动挑下一个该做的阶段
#   python gen_step1_PBE_opt.py --stage a       指定阶段
#   python gen_step1_PBE_opt.py --stage all     一次把 a 生成好（b/c 需前一段的 CONTCAR）
# 目录名：step1a_PBE_opt / step1b_PBE_opt / step1c_PBE_opt
# 结构来源：a <- ./POSCAR ；b <- step1a/CONTCAR ；c <- step1b/CONTCAR
#
# "single" = 旧行为：单目录 step1_PBE_opt，模板参数原样使用，不分段。
RELAX_STAGES = "auto"          # "auto" | "single"

# 各阶段覆盖的 INCAR 标签。None 表示删除该标签。
# EDIFFG 逐段收紧：前两段没必要死磕力，能进入下一段的吸引域就够了。
STAGE_SPEC = {
    "a": {"_desc": "固定胞，弛豫原子位置",
          "ISIF": "2", "IBRION": "2", "POTIM": "0.2",
          "EDIFFG": "-0.02", "NSW": "200", "IOPTCELL": None},
    "b": {"_desc": "放开晶胞（2D 仅面内），CG",
          "ISIF": "3", "IBRION": "2", "POTIM": "0.2",
          "EDIFFG": "-0.01", "NSW": "200"},
    "c": {"_desc": "准牛顿收尾",
          "ISIF": "3", "IBRION": "1", "POTIM": "0.2",
          "EDIFFG": "-0.001", "NSW": "100"},
}
STAGE_ORDER = ["a", "b", "c"]
# ###################################################################

# 2D 时把 VASPKIT 生成的 KPOINTS 真空方向细分强制改为 1。
# 原因：VASPKIT 102 生成的是三维网格，c≈15~20 Å 时 0.03 的间距常给出 kz=2 ——
# 对 2D 无物理意义且白翻倍机时。
FORCE_KZ1_2D = True

# ENCUT 设置
# None：自动取 ceil(ENCUT_FACTOR * max(ENMAX))，并向上取整到 10 eV
# 数值：手动指定 ENCUT，例如 MANUAL_ENCUT = 450
MANUAL_ENCUT = None
ENCUT_FACTOR = 1.5
FALLBACK_ENCUT = "300"

# 体系名称与作业名
# None：根据 POSCAR 第一行/元素组成自动生成
SYSTEM_OVERRIDE = None
JOBNAME_OVERRIDE = None

# ---- submit.sh Slurm 参数覆盖（渲染模板后再补丁；None=不改，保持模板原值）----
# submit.sh 来源不变（仍从 submit_std_2d/3d.tpl 渲染）；这里只在渲染后覆盖三行：
#   #SBATCH --nodes= / --ntasks-per-node= / --qos=
SUBMIT_OVERRIDE = {
    "nodes":           None,   # 或整数
    "ntasks_per_node": None,   # 或整数
    "qos":             None,   # 或 "regular" 等字符串
}

# ---- DFT+U 自动判定（按 POSCAR 元素）----
# "auto": POSCAR 含下方 U_VALUES 表里的 d/f 元素就注入 LDAU 系列
#         (LDAU=.TRUE., LDAUTYPE=2, 逐元素 LDAUL/LDAUU/LDAUJ)；否则不写 U。
#         判定结果会【覆盖】incar.tpl 里手写的 LDAU* 标签（后处理注入，与磁性同套路）。
# True  : 强制加 U（元素不在表里会报错，请用 U_OVERRIDE 手动给）。
# False : 完全不加 U。
# ★ 重要：U 是强依赖体系/轨道的经验参数。下表给的是文献里常见的起点值
#   （偏 Materials Project 的 GGA+U 一档），【务必按你的体系自查文献核对】。
#   不确定的元素宁可先不填（设 None 跳过）也不要瞎套。
AUTO_U = "auto"            # "auto" | True | False
U_OVERRIDE = {}           # 例: {"Fe": 5.3, "O": 0.0}；写了就优先于内置表(0/None=该元素不加U)
LDAUTYPE = 2              # 2=Dudarev(只需有效 U=U-J，最常用)；1=Liechtenstein
# 每元素有效 U 值（eV）。None 或缺失 = 该元素不加 U。改这里即可增删。
U_VALUES = {
    # 3d 过渡金属（Dudarev 有效 U，文献常见起点；请自查）
    "Ti": 0.0, "V": 3.25, "Cr": 3.7, "Mn": 3.9, "Fe": 5.3,
    "Co": 3.32, "Ni": 6.2, "Cu": 0.0, "Zn": 0.0,
    # 4d/5d 一般较小或不加，这里默认不加（需要自己补）
    # 4f 稀土（f 电子，U 通常较大；示例值，务必自查）
    "Ce": 4.5, "Pr": 5.0, "Nd": 5.0, "Sm": 5.0, "Eu": 5.0,
    "Gd": 6.0, "Tb": 5.0, "Dy": 5.0, "Ho": 5.0, "Er": 5.0, "Tm": 5.0, "Yb": 5.0,
    # 5f 锕系（示例）
    "U": 4.0, "Np": 4.0, "Pu": 4.0,
}
# 轨道角量子数 LDAUL：d 元素=2，f 元素=3。脚本按元素在 D_ELEMS/F_ELEMS 里自动定。

# ---- 磁性自动判定（按 POSCAR 元素）----
# "auto": POSCAR 含下方 MAG_ELEM_MOMENTS 里的元素（3d 过渡金属 / 4f 稀土 / 锕系）
#         就按磁性处理：ISPIN=2 + 按元素给高自旋初始 MAGMOM；否则 ISPIN=1 不写 MAGMOM。
#         判定结果会【覆盖】incar.tpl 里手写的 ISPIN/MAGMOM（脚本渲染后再后处理注入）。
# True / False: 强制磁性 / 强制非磁。
# 说明：
#   * 初始磁矩是 FM 型高自旋起点。若真实基态是 AFM 等特定磁序，请用
#     MAGMOM_OVERRIDE 逐元素改，或干脆改成手写整条 MAGMOM 的方式跑 step1；
#     后续 step2/step3 会继承【收敛后】的逐离子磁矩，能保号、保 AFM。
#   * 起点给磁但体系实为非磁时，SCF 会自己塌缩到 0——step2 检测到塌缩会
#     自动降回 ISPIN=1，不需要人工干预（代价只是 step1 慢一点）。
#   * step1/step2 始终共线（vasp_std）；SOC 到 step3/step4 才开（那里也是自动判定）。
AUTO_MAG = "auto"            # "auto" | True | False
MAGMOM_OVERRIDE = {}         # 例: {"Mn": 5.0, "In": 0.0, "Se": 0.0}（写了就优先于内置表）
MAG_ELEM_MOMENTS = {
    # 3d 过渡金属（高自旋起点；Ti/Cu 等弱磁候选也列入——误报只是白开 ISPIN=2，
    # 会自动塌缩并被 step2 降级；漏报才是静默错误）
    "Sc": 1.0, "Ti": 1.0, "V": 3.0, "Cr": 4.0, "Mn": 5.0,
    "Fe": 4.0, "Co": 3.0, "Ni": 2.0, "Cu": 1.0,
    # 4f 稀土（La/Lu 无 f 磁矩不列）
    "Ce": 1.0, "Pr": 2.0, "Nd": 3.0, "Pm": 4.0, "Sm": 5.0, "Eu": 7.0,
    "Gd": 7.0, "Tb": 6.0, "Dy": 5.0, "Ho": 4.0, "Er": 3.0, "Tm": 2.0, "Yb": 1.0,
    # 常见磁性锕系
    "U": 2.0, "Np": 3.0, "Pu": 4.0,
}
# 重元素表（Z>=50）：step1 只用来打提示，真正开 SOC 是 step3/step4 的事
SOC_ELEMS = {
    "In", "Sn", "Sb", "Te", "I", "Xe", "Cs", "Ba",
    "La", "Ce", "Pr", "Nd", "Pm", "Sm", "Eu", "Gd", "Tb", "Dy", "Ho", "Er",
    "Tm", "Yb", "Lu", "Hf", "Ta", "W", "Re", "Os", "Ir", "Pt", "Au", "Hg",
    "Tl", "Pb", "Bi", "Po", "At", "Rn", "Fr", "Ra", "Ac", "Th", "Pa", "U",
    "Np", "Pu", "Am", "Cm",
}

# ---- LMAXMIX 自动判定（按 POSCAR 元素）----
# 含 f 元素 -> LMAXMIX=6；含 d 元素 -> LMAXMIX=4；否则 2。
# 判定结果会【覆盖】incar.tpl 里手写的 LMAXMIX（与磁性同样的后处理注入方式）。
# 说明：只要 POTCAR 价电子里有 d/f 通道就该升，宁多勿少——LMAXMIX 偏大只是
# 混合器多存一点密度分量，几乎不增加代价；偏小则 d/f 体系 SCF 收敛变差甚至震荡。
D_ELEMS = {
    # 3d
    "Sc", "Ti", "V", "Cr", "Mn", "Fe", "Co", "Ni", "Cu", "Zn",
    # 4d
    "Y", "Zr", "Nb", "Mo", "Tc", "Ru", "Rh", "Pd", "Ag", "Cd",
    # 5d（La/Lu 的 5d 也在此归为 d；若同时命中 F_ELEMS 以 f 优先）
    "La", "Lu", "Hf", "Ta", "W", "Re", "Os", "Ir", "Pt", "Au", "Hg",
    # 主族里 POTCAR 常带 d 半芯态的（Ga_d/Ge_d/In_d/Sn_d/Tl_d/Pb_d/Bi_d 等）
    "Ga", "Ge", "In", "Sn", "Tl", "Pb", "Bi",
}
F_ELEMS = {
    # 4f 镧系
    "Ce", "Pr", "Nd", "Pm", "Sm", "Eu", "Gd", "Tb", "Dy", "Ho", "Er",
    "Tm", "Yb",
    # 5f 锕系
    "Ac", "Th", "Pa", "U", "Np", "Pu", "Am", "Cm",
}

# ---- 原胞检查 ----
# True: 运行前检查 POSCAR 是不是原胞。若是原胞的 N 倍超胞（N>1），
#       自动转成原胞并【原地替换 POSCAR】，原文件备份成 POSCAR_original（不覆盖已有备份）。
#       为什么必须在 step1 就做：后面 gen_step3 的高对称路径是在原胞倒空间里定义的，
#       超胞上的能带是折叠的，路径标签没有物理意义——那时候才发现就白烧了 step1+step2 的机时。
# False: 跳过检查（比如你【故意】要在超胞上算，缺陷/掺杂体系）。
PRIMITIVE_CHECK = True
PRIMITIVE_SYMPREC   = 1e-2    # 对称性识别容差（Å）
PRIMITIVE_ANGLE_TOL = 5.0     # 对称性识别角度容差（度）
PRIMITIVE_BACKUP    = "POSCAR_original"   # 原始（非原胞）结构备份到这个名字

# =====================================================================
#                         用户配置区结束
#  （Slurm 队列/核数/VASP 路径请直接修改 submit_std.tpl，
#    NCORE/KPAR 等其余 VASP 参数请直接修改 incar.tpl）
# =====================================================================

METHOD_FILE = "workflow_method.txt"

FUNC_MAP = {
    "pbe-d3": {
        "GGA": "PE",
        "IVDW": "12",
        "VDW_LINE": "IVDW   = 12            # PBE + DFT-D3(BJ)",
    },
    "pbesol": {
        "GGA": "PS",
        "IVDW": None,
        "VDW_LINE": "# IVDW disabled: PBEsol geometry",
    },
    "pbe": {
        "GGA": "PE",
        "IVDW": None,
        "VDW_LINE": "# IVDW disabled: plain PBE geometry",
    },
}

# 本脚本能填充的全部占位符（模板里出现才填，不出现就跳过）
KNOWN_PLACEHOLDERS = {"SYSTEM", "ENCUT", "GGA", "VDW_LINE", "JOBNAME"}


def validate_user_config():
    """检查脚本顶部的用户配置。"""
    if FUNC not in FUNC_MAP:
        allowed = ", ".join(repr(x) for x in FUNC_MAP)
        sys.exit(f"[ERROR] FUNC={FUNC!r} 无效，只允许：{allowed}")

    if MANUAL_ENCUT is not None:
        try:
            value = float(MANUAL_ENCUT)
        except (TypeError, ValueError):
            sys.exit("[ERROR] MANUAL_ENCUT 必须是数字或 None")
        if value <= 0:
            sys.exit("[ERROR] MANUAL_ENCUT 必须大于 0")

    if ENCUT_FACTOR <= 0:
        sys.exit("[ERROR] ENCUT_FACTOR 必须大于 0")

    if str(DIMENSION).lower() not in ("auto", "2d", "3d"):
        sys.exit("[ERROR] DIMENSION 只允许 'auto' / '2d' / '3d'")
    if CELL_CONSTRAINT_2D not in ("optcell_file", "ioptcell_tag", "none"):
        sys.exit("[ERROR] CELL_CONSTRAINT_2D 只允许 "
                 "'optcell_file' / 'ioptcell_tag' / 'none'")


def sanitize_label(text: str) -> str:
    label = re.sub(r"[^A-Za-z0-9_.-]+", "_", text.strip())
    return label.strip("_.-") or "material"


def read_poscar_identity(path: Path):
    """从 POSCAR 读取标题和化学式，用于 SYSTEM 与作业名。"""
    lines = path.read_text(encoding="utf-8-sig").splitlines()
    if len(lines) < 7:
        sys.exit(f"[ERROR] POSCAR 内容不完整：{path}")

    title_token = sanitize_label(lines[0].split()[0]) if lines[0].split() else ""
    species_line = lines[5].split()

    if species_line and all(re.fullmatch(r"[+-]?\d+", x) for x in species_line):
        species = []
        counts = [int(x) for x in species_line]
    else:
        species = species_line
        try:
            counts = [int(x) for x in lines[6].split()]
        except (ValueError, IndexError):
            sys.exit("[ERROR] 无法读取 POSCAR 元素数量行")

    if species and len(species) == len(counts):
        formula = "".join(
            element + (str(number) if number != 1 else "")
            for element, number in zip(species, counts)
        )
    else:
        formula = "material"

    generic = {"POSCAR", "CONTCAR", "structure", "material"}
    label = title_token if title_token and title_token not in generic else sanitize_label(formula)
    return label, formula


def _free_backup_path(base: Path) -> Path:
    """POSCAR_original -> 已存在就 POSCAR_original_1 / _2 ...  绝不覆盖已有备份。"""
    if not base.exists():
        return base
    i = 1
    while True:
        cand = base.with_name(f"{base.name}_{i}")
        if not cand.exists():
            return cand
        i += 1


def ensure_primitive(poscar: Path):
    """
    确认 POSCAR 是原胞。若是 N 倍超胞（N>1）:
        1. 原文件备份成 PRIMITIVE_BACKUP（已存在则加后缀，不覆盖）；
        2. 把原胞写回 POSCAR，流程照常继续。
    返回一段 provenance 字符串（没转换就返回 None）。
    """
    if not PRIMITIVE_CHECK:
        print("[SKIP] PRIMITIVE_CHECK=False，不检查原胞")
        return None

    try:
        from pymatgen.core import Structure
        from pymatgen.symmetry.analyzer import SpacegroupAnalyzer
    except ImportError:
        print("[WARN] 没装 pymatgen，跳过原胞检查。"
              "若 POSCAR 是超胞，后面 gen_step3 会在生成高对称路径时报错。")
        return None

    raw = poscar.read_text(encoding="utf-8-sig")
    if any(ln.strip()[:1].upper() == "S" for ln in raw.splitlines()[7:8]):
        print("[WARN] POSCAR 带 Selective dynamics；若发生原胞转换，该标记会丢失")

    try:
        struct = Structure.from_file(str(poscar))
        sga = SpacegroupAnalyzer(struct, symprec=PRIMITIVE_SYMPREC,
                                 angle_tolerance=PRIMITIVE_ANGLE_TOL)
        prim = sga.find_primitive()
    except Exception as exc:
        print(f"[WARN] 原胞检查失败（{exc}），按原样继续")
        return None

    ratio = struct.volume / prim.volume
    spg = f"{sga.get_space_group_symbol()} (#{sga.get_space_group_number()})"

    if ratio < 1.01:
        print(f"[OK] POSCAR 已经是原胞（空间群 {spg}，{len(struct)} 原子）")
        return None

    n = int(round(ratio))
    backup = _free_backup_path(poscar.with_name(PRIMITIVE_BACKUP))
    backup.write_text(raw, encoding="utf-8", newline="\n")

    title = raw.splitlines()[0].strip() or "structure"
    prim.to(filename=str(poscar), fmt="poscar")
    lines = poscar.read_text(encoding="utf-8").splitlines()
    lines[0] = f"{title} (primitive, {n}x reduced from {backup.name})"
    poscar.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")

    print(f"[!!] POSCAR 不是原胞：空间群 {spg}，体积是原胞的 {ratio:.2f} 倍")
    print(f"     原结构 : {len(struct):3d} 原子, {struct.composition.formula}, "
          f"V={struct.volume:.2f} Å³  -> 已备份为 {backup.name}")
    print(f"     新 POSCAR: {len(prim):3d} 原子, {prim.composition.formula}, "
          f"V={prim.volume:.2f} Å³  (原胞)")
    print("     原因：能带的高对称路径定义在原胞倒空间里，超胞上的能带是折叠的。")
    print("     若你【就是要】算超胞（缺陷/掺杂），请把 PRIMITIVE_CHECK 设成 False 并恢复备份。")
    return (f"PRIMITIVE=converted ({n}x -> 1x, spacegroup {spg}, "
            f"original saved as {backup.name})")


def build_params(label: str):
    """本脚本"计算得来"的占位符值；模板里没出现的会被自动跳过。"""
    method = FUNC_MAP[FUNC]
    system = SYSTEM_OVERRIDE if SYSTEM_OVERRIDE else label
    jobname = JOBNAME_OVERRIDE if JOBNAME_OVERRIDE else sanitize_label(f"{label}_s1opt")[:80]

    return {
        "SYSTEM": system,
        "ENCUT": FALLBACK_ENCUT,
        "GGA": method["GGA"],
        "VDW_LINE": method["VDW_LINE"],
        "JOBNAME": jobname,
    }


def render(template_path: Path, out_path: Path, params: dict):
    """
    填充模板：
      - params 中的键在模板里"出现才填、没有就跳过"（模板可自由删占位符）；
      - 若模板出现本脚本不认识的占位符，报错并列出可用占位符。
    """
    if not template_path.exists():
        sys.exit(f"[ERROR] 找不到模板：{template_path}")

    text = template_path.read_text(encoding="utf-8")
    for key, val in params.items():
        text = text.replace("{{" + key + "}}", str(val))

    leftover = set(re.findall(r"\{\{(\w+)\}\}", text))
    if leftover:
        sys.exit(
            f"[ERROR] {template_path.name} 含无法填充的占位符：{sorted(leftover)}\n"
            f"        本脚本支持的占位符：{sorted(KNOWN_PLACEHOLDERS)}\n"
            f"        其余参数请在模板中直接写死。"
        )

    out_path.write_text(text, encoding="utf-8", newline="\n")
    print(f"[OK] {out_path.name}")


def run_vaspkit_kpoints(exe: str, outdir: Path, kscheme: str, kspacing: str):
    print(f"[..] VASPKIT 生成 KPOINTS：1 -> 102 -> {kscheme} -> {kspacing}")
    subprocess.run(
        [exe],
        input=f"1\n102\n{kscheme}\n{kspacing}\n",
        text=True,
        cwd=outdir,
        check=True,
    )


def run_vaspkit_potcar(exe: str, outdir: Path):
    potcar = outdir / "POTCAR"
    if potcar.exists():
        print("[OK] POTCAR 已存在，跳过重新生成")
        return

    print("[..] VASPKIT 生成 POTCAR：1 -> 103")
    subprocess.run(
        [exe],
        input="1\n103\n",
        text=True,
        cwd=outdir,
        check=True,
    )


def encut_from_potcar(potcar: Path, factor: float) -> int:
    vals = []
    for line in potcar.read_text(errors="ignore").splitlines():
        match = re.search(r"ENMAX\s*=\s*([\d.]+)", line)
        if match:
            vals.append(float(match.group(1)))

    if not vals:
        sys.exit(f"[ERROR] 在 {potcar} 中没有找到 ENMAX")

    max_enmax = max(vals)
    encut = int(math.ceil(factor * max_enmax / 10.0)) * 10
    print(f"[..] POTCAR ENMAX：{', '.join(f'{x:.1f}' for x in vals)} eV")
    print(f"[..] ENCUT = ceil({factor} x {max_enmax:.1f}) -> {encut} eV")
    return encut


def read_species_and_counts(path: Path):
    """从 POSCAR 读 (元素符号列表, 各元素原子数)。VASP4 无符号行时符号为 None。"""
    lines = path.read_text(encoding="utf-8-sig").splitlines()
    line6 = lines[5].split()
    if line6 and line6[0].lstrip("-").isdigit():
        return None, [int(x) for x in line6]
    return line6, [int(x) for x in lines[6].split()]


def decide_magnetism(symbols, counts):
    """返回 (magnetic, magmom_str_or_None, note)。magmom 为共线 per-species 压缩写法。"""
    if AUTO_MAG is False:
        return False, None, "AUTO_MAG=False 强制非磁"
    if symbols is None:
        return False, None, "POSCAR 无元素符号行(VASP4 格式)，无法自动判定，按非磁处理"

    table = dict(MAG_ELEM_MOMENTS)
    table.update({k: float(v) for k, v in MAGMOM_OVERRIDE.items()})
    hits = [s for s in symbols if table.get(s, 0.0) != 0.0]

    if AUTO_MAG is True and not hits and not MAGMOM_OVERRIDE:
        # 强制磁性但表里没有该体系的元素——给不出合理起点
        sys.exit("[ERROR] AUTO_MAG=True 但 POSCAR 元素都不在磁性表里，"
                 "请用 MAGMOM_OVERRIDE 手动给初始磁矩")
    if not hits:
        return False, None, "元素 %s 均非磁性候选" % "/".join(symbols)

    magmom = "  ".join("%d*%g" % (n, table.get(s, 0.0))
                       for s, n in zip(symbols, counts))
    return True, magmom, "检测到磁性候选元素 %s（高自旋 FM 起点）" % "/".join(sorted(set(hits)))


def apply_magnetism_to_incar(incar_path: Path, magnetic: bool, magmom: str, note: str):
    """后处理生成好的 INCAR：剔除模板里已有的 ISPIN/MAGMOM/NUPDOWN，注入自动判定结果。
       这样无论 incar.tpl 里写没写磁性参数，最终 INCAR 都与判定一致。"""
    keep = [ln for ln in incar_path.read_text(encoding="utf-8").splitlines()
            if not re.match(r"\s*(ISPIN|MAGMOM|NUPDOWN)\s*=", ln, re.IGNORECASE)]
    keep.append("")
    keep.append("# ---- 磁性（gen_step1 按 POSCAR 自动判定：%s）----" % note)
    if magnetic:
        keep.append("ISPIN    = 2")
        keep.append("MAGMOM   = %s" % magmom)
    else:
        keep.append("ISPIN    = 1")
    incar_path.write_text("\n".join(keep) + "\n", encoding="utf-8", newline="\n")


def decide_lmaxmix(symbols):
    """按元素返回 (lmaxmix, note)。f 元素 -> 6；d 元素 -> 4；否则 2。"""
    if symbols is None:
        return 2, "POSCAR 无元素符号行(VASP4 格式)，无法自动判定，保守取 2"
    f_hits = sorted(set(symbols) & F_ELEMS)
    d_hits = sorted(set(symbols) & D_ELEMS)
    if f_hits:
        return 6, "含 f 元素 %s" % "/".join(f_hits)
    if d_hits:
        return 4, "含 d 元素 %s" % "/".join(d_hits)
    return 2, "无 d/f 元素"


def apply_lmaxmix_to_incar(incar_path: Path, lmaxmix: int, note: str):
    """后处理生成好的 INCAR：剔除模板里已有的 LMAXMIX，注入自动判定结果。
       与 apply_magnetism_to_incar 同一套路，保证最终 INCAR 与元素组成一致。"""
    keep = [ln for ln in incar_path.read_text(encoding="utf-8").splitlines()
            if not re.match(r"\s*LMAXMIX\s*=", ln, re.IGNORECASE)]
    keep.append("")
    keep.append("# ---- LMAXMIX（gen_step1 按 POSCAR 自动判定：%s）----" % note)
    keep.append("LMAXMIX  = %d" % lmaxmix)
    incar_path.write_text("\n".join(keep) + "\n", encoding="utf-8", newline="\n")


def decide_u(symbols):
    """返回 (use_u, ldau_lines_or_None, note)。
       按 U_VALUES/U_OVERRIDE 给每个（去重后）元素定 LDAUL/LDAUU/LDAUJ；
       非 d/f 或值为 0/None 的元素给 LDAUL=-1、U=J=0（VASP 惯例：该元素不加 U）。"""
    if AUTO_U is False:
        return False, None, "AUTO_U=False，不加 U"
    if symbols is None:
        return False, None, "POSCAR 无元素符号行(VASP4)，无法判定，不加 U"

    table = dict(U_VALUES)
    table.update({k: (None if v in (0, 0.0) else float(v))
                  for k, v in U_OVERRIDE.items()})

    order = list(dict.fromkeys(symbols))     # 保序去重，与 POTCAR 元素顺序一致
    hits = [e for e in order
            if table.get(e) not in (None, 0, 0.0) and (e in D_ELEMS or e in F_ELEMS)]
    if not hits:
        if AUTO_U is True:
            sys.exit("[ERROR] AUTO_U=True 但没有可加 U 的 d/f 元素，请用 U_OVERRIDE 指定")
        return False, None, "无 d/f 元素或表中无对应 U 值，不加 U"

    ldaul, ldauu, ldauj = [], [], []
    for e in order:
        u = table.get(e)
        if u not in (None, 0, 0.0) and (e in F_ELEMS or e in D_ELEMS):
            l = 3 if e in F_ELEMS else 2
            ldaul.append(str(l)); ldauu.append("%g" % float(u)); ldauj.append("0.0")
        else:
            ldaul.append("-1");   ldauu.append("0.0");           ldauj.append("0.0")

    lines = [
        "LDAU     = .TRUE.",
        "LDAUTYPE = %d" % LDAUTYPE,
        "LDAUL    = %s" % " ".join(ldaul),
        "LDAUU    = %s" % " ".join(ldauu),
        "LDAUJ    = %s" % " ".join(ldauj),
        "LDAUPRINT= 1",
    ]
    detail = ", ".join("%s(U=%g,l=%s)" % (e, float(table[e]), "3" if e in F_ELEMS else "2")
                       for e in hits)
    return True, lines, "对 %s 加 U" % detail


def apply_u_to_incar(incar_path, use_u, ldau_lines, note):
    """后处理 INCAR：先剔除模板里已有的 LDAU* 标签，再按判定注入（或保持不写）。
       同时确保 LMAXMIX>=4（加 U 的 d/f 混合需要；若已有更大值不降低）。"""
    keep = [ln for ln in incar_path.read_text(encoding="utf-8").splitlines()
            if not re.match(r"\s*(LDAU|LDAUTYPE|LDAUL|LDAUU|LDAUJ|LDAUPRINT)\s*=",
                            ln, re.IGNORECASE)]
    keep.append("")
    keep.append("# ---- DFT+U（gen_step1 按 POSCAR 自动判定：%s）----" % note)
    if use_u:
        keep.append("# ★ 以下 U 值来自 gen_step1 的 U_VALUES 表，是【文献常见起点】，")
        keep.append("#   不是对你这个体系的定论 —— 请务必自查文献后按需修改！")
        keep.append("#   改法一（只改这一次）：直接编辑下面 LDAUU 一行；")
        keep.append("#   改法二（以后都用新值）：改 gen_step1 的 U_VALUES / U_OVERRIDE 再重跑 gen。")
        keep.append("#   LDAUL/LDAUU/LDAUJ 每一列依次对应 POSCAR 的一种元素（与 POTCAR 同序）；")
        keep.append("#   LDAUL: 2=d 轨道, 3=f 轨道, -1=该元素不加 U（其 U/J 写 0）。")
        keep.append("#   LDAUTYPE=2(Dudarev) 只用有效 U=U-J，故 LDAUJ 一律给 0。")
        keep.append("#   注意：step2/step3 会原样继承这里的 U；step4(HSE) 是否保留由该脚本的")
        keep.append("#   HSE_U_MODE 决定（默认 remove=纯 HSE06）。")
        keep.extend(ldau_lines)
    else:
        keep.append("# （本体系未加 U。若你判断需要 U，可在此手写 LDAU/LDAUTYPE/LDAUL/")
        keep.append("#   LDAUU/LDAUJ，或改 gen_step1 的 U_VALUES/U_OVERRIDE 后重跑 gen。）")
    incar_path.write_text("\n".join(keep) + "\n", encoding="utf-8", newline="\n")


def _patch_sbatch_param(text, flag, value):
    """把 #SBATCH --<flag>=<...> 行的值改成 value；无该行则在首个 #SBATCH 后补一行。"""
    pat = re.compile(r"^(#SBATCH\s+--%s=)\S+.*$" % re.escape(flag), re.MULTILINE)
    if pat.search(text):
        return pat.sub(r"\g<1>%s" % value, text), True
    out, inserted = [], False
    for ln in text.splitlines(keepends=True):
        out.append(ln)
        if (not inserted) and ln.lstrip().startswith("#SBATCH"):
            out.append("#SBATCH --%s=%s\n" % (flag, value))
            inserted = True
    return ("".join(out), True) if inserted else (text, False)


def override_submit_slurm(submit_path, override):
    """渲染后覆盖 submit.sh 的 nodes/ntasks_per_node/qos（None 项跳过）。打印改动。"""
    text = Path(submit_path).read_text(encoding="utf-8")
    flag_map = [("nodes", "nodes"), ("ntasks_per_node", "ntasks-per-node"), ("qos", "qos")]
    changed = []
    for key, flag in flag_map:
        val = override.get(key)
        if val is None:
            continue
        text, ok = _patch_sbatch_param(text, flag, val)
        changed.append("--%s=%s" % (flag, val) if ok else "[未写入 --%s]" % flag)
    Path(submit_path).write_text(text, encoding="utf-8", newline="\n")
    if changed:
        print("[..] submit.sh 覆盖 Slurm 参数：%s" % ", ".join(changed))
    else:
        print("[..] submit.sh Slurm 参数：未覆盖（SUBMIT_OVERRIDE 全为 None）")


def resolve_dimension(poscar: Path):
    """按 DIMENSION 配置返回 (dim, vac_axis, note)。2D 时强制要求真空沿 c 轴。"""
    mode = str(DIMENSION).lower()
    if mode in ("2d", "3d"):
        return mode, (2 if mode == "2d" else None), "DIMENSION=%r 强制指定" % DIMENSION

    dim, axis, vacs = detect_dimension(poscar, VACUUM_MIN)
    detail = ", ".join("%s=%.1f" % (AXIS_NAMES[i], v) for i, v in enumerate(vacs))
    if dim == "2d":
        note = "自动判定：沿 %s 轴真空 %.1f Å（各向真空 %s Å）" % (
            AXIS_NAMES[axis], vacs[axis], detail)
        if axis != 2:
            sys.exit(
                "[ERROR] 检测到 2D 体系，但真空沿 %s 轴而非 c 轴。\n"
                "        incar_2d.tpl 的 IOPTCELL/OPTCELL 约束假设固定 c 轴，"
                "真空不在 c 会锁错方向。\n"
                "        请先把结构旋转/重排成真空沿第 3 个晶格矢量（标准做法），"
                "再重新运行。" % AXIS_NAMES[axis])
    else:
        note = "自动判定：无真空方向（各向最大间隙 %s Å，阈值 %.1f Å）" % (
            detail, VACUUM_MIN)
    return dim, axis, note


def apply_stage_to_incar(incar_path: Path, stage: str):
    """按 STAGE_SPEC 覆盖 INCAR 里的弛豫控制标签。值为 None 的标签直接删除。"""
    spec = {k: v for k, v in STAGE_SPEC[stage].items() if not k.startswith("_")}
    keys = set(spec)
    keep = [ln for ln in incar_path.read_text(encoding="utf-8").splitlines()
            if not (re.match(r"\s*([A-Za-z_]+)\s*=", ln)
                    and re.match(r"\s*([A-Za-z_]+)\s*=", ln).group(1).upper() in keys)]
    keep.append("")
    keep.append("# ---- 阶段 %s：%s（gen_step1 注入）----"
                % (stage, STAGE_SPEC[stage]["_desc"]))
    for k in ("ISIF", "IBRION", "POTIM", "EDIFFG", "NSW", "IOPTCELL"):
        if k in spec and spec[k] is not None:
            keep.append("%-8s = %s" % (k, spec[k]))
    dropped = [k for k, v in spec.items() if v is None]
    if dropped:
        keep.append("# 本阶段已删除：%s" % ", ".join(sorted(dropped)))
    incar_path.write_text("\n".join(keep) + "\n", encoding="utf-8", newline="\n")


def resolve_stage(cwd: Path):
    """返回 (stage, outdir_name, src_poscar)。stage=None 表示 single 模式。"""
    argv = sys.argv[1:]
    want = None
    if "--stage" in argv:
        i = argv.index("--stage")
        if i + 1 >= len(argv):
            sys.exit("[ERROR] --stage 后面要跟 a / b / c")
        want = argv[i + 1].strip().lower()
        if want == "all":
            want = "a"
        if want not in STAGE_ORDER:
            sys.exit("[ERROR] --stage 只能是 a / b / c（或 all，等价于 a）")

    if RELAX_STAGES == "single" and want is None:
        return None, "step1_PBE_opt", cwd / "POSCAR"

    def dirname(st):
        return "step1%s_PBE_opt" % st

    def src_of(st):
        if st == "a":
            return cwd / "POSCAR"
        prev = cwd / dirname(STAGE_ORDER[STAGE_ORDER.index(st) - 1])
        return prev / "CONTCAR"

    if want is None:                       # 自动挑下一个
        want = "a"
        for st in STAGE_ORDER:
            d = cwd / dirname(st)
            if not d.exists():
                want = st
                break
            # 目录已在：若已有 CONTCAR 且还有后续阶段，就往后走
            idx = STAGE_ORDER.index(st)
            if (d / "CONTCAR").exists() and idx + 1 < len(STAGE_ORDER):
                want = STAGE_ORDER[idx + 1]
            else:
                want = st
                break

    src = src_of(want)
    if not src.exists():
        prev = STAGE_ORDER[STAGE_ORDER.index(want) - 1] if want != "a" else None
        sys.exit("[ERROR] 阶段 %s 需要 %s，但它不存在。\n"
                 "        请先跑完阶段 %s（%s），再回来生成阶段 %s。"
                 % (want, src, prev, dirname(prev) if prev else "?", want))
    # v1.3：接力结构完整性校验——前一段还在跑时 CONTCAR 只写了一半，
    # 直接拿去生成会让 vaspkit/VASP 读文件崩（forrtl end-of-file）
    bad = validate_poscar(src)
    if bad:
        sys.exit("[ERROR] %s 不完整：%s。\n"
                 "        上一段弛豫很可能还在跑（CONTCAR 写了一半）——\n"
                 "        等 tf 里上一段变 done 再生成；确认已正常结束就检查该文件内容。"
                 % (src, bad))
    return want, dirname(want), src


def apply_cell_constraint_2d(incar_path: Path, outdir: Path):
    """2D 后处理：按 CELL_CONSTRAINT_2D 处理 IOPTCELL 标签 / OPTCELL 文件。"""
    lines = incar_path.read_text(encoding="utf-8").splitlines()
    iopt, kept = None, []
    for ln in lines:
        m = re.match(r"\s*IOPTCELL\s*=\s*([\d\s]+?)\s*(?:[#!].*)?$", ln, re.IGNORECASE)
        if m:
            vals = m.group(1).split()
            if len(vals) == 9 and all(v in ("0", "1") for v in vals):
                iopt = [int(v) for v in vals]
            continue          # IOPTCELL 行先统一摘出，按流派决定去留
        kept.append(ln)

    mode = CELL_CONSTRAINT_2D
    if mode == "ioptcell_tag":
        if iopt is None:
            print("[WARN] CELL_CONSTRAINT_2D='ioptcell_tag' 但模板/INCAR 中没有合法的 "
                  "IOPTCELL 行 —— c 轴将不受约束，ISIF=3 会连真空一起弛豫！")
        return                # 原样保留，什么都不改

    if iopt is None:
        iopt = [1, 1, 0, 1, 1, 0, 0, 0, 0]   # 默认：面内 xx/yy/xy 放开，c 固定

    if mode == "optcell_file":
        optcell = outdir / "OPTCELL"
        optcell.write_text(
            "\n".join("".join(str(iopt[3 * r + c]) for c in range(3))
                      for r in range(3)) + "\n",
            encoding="utf-8", newline="\n")
        kept.append("")
        kept.append("# 2D 约束变胞：IOPTCELL 已转换为 OPTCELL 文件"
                    "（optcell_file 流派，标签本身已删除以免 VASP 报未知标签）")
        incar_path.write_text("\n".join(kept) + "\n", encoding="utf-8", newline="\n")
        print("[OK] OPTCELL（%s / %s / %s）已写入，INCAR 中的 IOPTCELL 行已移除"
              % tuple("".join(str(iopt[3 * r + c]) for c in range(3)) for r in range(3)))
        return

    # mode == "none"
    incar_path.write_text("\n".join(kept) + "\n", encoding="utf-8", newline="\n")
    vals = {k: v for k, v in read_incar_values(incar_path).items()}
    if vals.get("ISIF", "").startswith("3"):
        print("[WARN] CELL_CONSTRAINT_2D='none' 且 ISIF=3 —— c 轴（真空层）会被一起"
              "弛豫、真空可能塌缩！请确认这是你想要的。")


def write_method_file(path: Path, label: str, formula: str, prim_note: str = None,
                      mag_line: str = None, dim_line: str = None):
    method = FUNC_MAP[FUNC]
    lines = [
        f"FUNC={FUNC}",
        f"GGA={method['GGA']}",
        f"IVDW={method['IVDW'] if method['IVDW'] else 'NONE'}",
        f"LABEL={label}",
        f"FORMULA={formula}",
    ]
    if dim_line:
        lines.append(dim_line)
    if mag_line:
        lines.append(mag_line)
    if prim_note:
        lines.append(prim_note)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")


def read_incar_values(path: Path):
    values = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        text = line.strip()
        if not text or text.startswith(("#", "!")):
            continue

        for marker in ("#", "!"):
            if marker in text:
                text = text.split(marker, 1)[0].strip()

        for part in text.split(";"):
            if "=" in part:
                key, value = part.split("=", 1)
                values[key.strip().upper()] = value.strip()
    return values


def validate_generated_incar(path: Path):
    """
    确认生成的 INCAR 与顶部 FUNC 一致。
    只校验方法关键的 GGA / IVDW 两项——其余参数模板自由增删，不做限制。
    """
    values = read_incar_values(path)
    method = FUNC_MAP[FUNC]
    gga = values.get("GGA", "").upper()
    ivdw = values.get("IVDW", "").split()[0] if values.get("IVDW") else None

    if gga != method["GGA"]:
        sys.exit(
            f"[ERROR] 生成的 INCAR 中 GGA={gga or '(missing)'}，与 FUNC={FUNC!r} "
            f"要求的 {method['GGA']} 不一致。\n"
            "        请保留 incar.tpl 中的 GGA = {{GGA}}，"
            "或将其手动固定为一致的值。"
        )

    if ivdw != method["IVDW"]:
        if method["IVDW"] is None:
            sys.exit(
                f"[ERROR] FUNC={FUNC!r} 不应启用色散修正，但生成的 INCAR 有 IVDW={ivdw}。\n"
                "        请删除 incar.tpl 中写死的 IVDW，只保留 {{VDW_LINE}}。"
            )
        sys.exit(
            f"[ERROR] FUNC={FUNC!r} 要求 IVDW={method['IVDW']}，"
            f"但生成的 INCAR 中 IVDW={ivdw or '(missing)'}。\n"
            "        请确认 incar.tpl 中的 {{VDW_LINE}} 单独占一行。"
        )


def main():
    validate_user_config()
    cwd = Path.cwd()

    if not (cwd / "POSCAR").exists():
        sys.exit("[ERROR] 当前目录缺少 POSCAR")

    # 原胞检查必须在读 label/formula、拷 POSCAR、跑 VASPKIT 之前——
    # 否则 KPOINTS/POTCAR/ENCUT 全是按超胞算的
    prim_note = ensure_primitive(cwd / "POSCAR")

    # ---- 维度判定 + 按维度选模板（2D/3D 各一套，缺失回退到无后缀旧名）----
    dim, vac_axis, dim_note = resolve_dimension(cwd / "POSCAR")
    incar_tpl = resolve_tpl(cwd, "incar", dim)
    submit_tpl = resolve_tpl(cwd, "submit_std", dim)
    print(f"[..] 维度：{dim.upper()} — {dim_note}")
    print(f"[..] 模板：{incar_tpl.name} + {submit_tpl.name}")
    if dim == "2d" and incar_tpl.name == "incar.tpl":
        print("[WARN] 2D 体系但只找到了无后缀 incar.tpl —— 请确认它就是 2D 模板"
              "（含 c 轴约束），建议改名为 incar_2d.tpl 并补一套 *_3d.tpl")

    label, formula = read_poscar_identity(cwd / "POSCAR")
    params = build_params(label)

    stage, outdir_name, src_poscar = resolve_stage(cwd)
    outdir = cwd / outdir_name
    outdir.mkdir(exist_ok=True)
    if stage:
        print("[..] 弛豫阶段：%s —— %s" % (stage, STAGE_SPEC[stage]["_desc"]))
        print("[..] 结构来源：%s" % src_poscar)

    print(f"[..] 结构标签：{label}")
    print(f"[..] 化学式：{formula}")
    print(f"[..] 泛函：{FUNC}")
    print(f"[..] GGA={params['GGA']}，IVDW={FUNC_MAP[FUNC]['IVDW'] or 'off'}")
    print(f"[..] 输出目录：{outdir}")

    # 复制 POSCAR
    poscar_text = src_poscar.read_text(encoding="utf-8-sig")
    (outdir / "POSCAR").write_text(poscar_text, encoding="utf-8", newline="\n")
    print("[OK] POSCAR")

    # 生成提交脚本（Slurm 参数已固化在模板里，只填 JOBNAME）
    render(submit_tpl, outdir / "submit.sh", params)
    override_submit_slurm(outdir / "submit.sh", SUBMIT_OVERRIDE)

    # 生成 KPOINTS / POTCAR
    have_potcar = (outdir / "POTCAR").exists()
    if RUN_VASPKIT:
        try:
            run_vaspkit_kpoints(VASPKIT_EXE, outdir, KSCHEME, KSPACING)
            if dim == "2d" and FORCE_KZ1_2D:
                changed, kz_note = force_kz1(outdir / "KPOINTS", axis=vac_axis)
                print(f"[{'OK' if changed else '..'}] 2D KPOINTS 真空方向细分：{kz_note}")
            run_vaspkit_potcar(VASPKIT_EXE, outdir)
            have_potcar = (outdir / "POTCAR").exists()
        except FileNotFoundError:
            sys.exit(f"[ERROR] 找不到 VASPKIT：{VASPKIT_EXE}")
        except subprocess.CalledProcessError as exc:
            sys.exit(f"[ERROR] VASPKIT 执行失败，returncode={exc.returncode}")
    else:
        print("[SKIP] RUN_VASPKIT=False，已跳过 VASPKIT")

    # 确定 ENCUT
    if MANUAL_ENCUT is not None:
        params["ENCUT"] = str(MANUAL_ENCUT)
        print(f"[..] 使用手动 ENCUT = {MANUAL_ENCUT} eV")
    elif have_potcar:
        params["ENCUT"] = str(encut_from_potcar(outdir / "POTCAR", ENCUT_FACTOR))
    else:
        print(f"[WARN] 没有 POTCAR，ENCUT 暂用兜底值 {params['ENCUT']} eV")

    # 生成并校验 INCAR
    render(incar_tpl, outdir / "INCAR", params)
    validate_generated_incar(outdir / "INCAR")
    print("[OK] INCAR 泛函检查通过")

    # ---- 磁性自动判定并注入 INCAR（覆盖模板里的 ISPIN/MAGMOM）----
    if stage:
        # 阶段参数必须在 2D 变胞约束处理【之前】注入：
        # 阶段 a 会删掉 IOPTCELL，apply_cell_constraint_2d 才不会去写 OPTCELL 文件
        apply_stage_to_incar(outdir / "INCAR", stage)
        print("[OK] 阶段 %s 参数已注入 INCAR" % stage)

    symbols, counts = read_species_and_counts(outdir / "POSCAR")
    magnetic, magmom, mag_note = decide_magnetism(symbols, counts)
    apply_magnetism_to_incar(outdir / "INCAR", magnetic, magmom, mag_note)
    if magnetic:
        print(f"[..] 磁性：ON  — {mag_note}")
        print(f"     ISPIN=2, MAGMOM = {magmom}")
        print("     （FM 高自旋起点；要 AFM 请改 MAGMOM_OVERRIDE 或手写 MAGMOM）")
    else:
        print(f"[..] 磁性：off — {mag_note}")

    # ---- LMAXMIX 自动判定并注入 INCAR（覆盖模板里的 LMAXMIX）----
    lmaxmix, lmm_note = decide_lmaxmix(symbols)
    apply_lmaxmix_to_incar(outdir / "INCAR", lmaxmix, lmm_note)
    print(f"[..] LMAXMIX = {lmaxmix} — {lmm_note}")

    # ---- DFT+U 自动判定并注入 INCAR（覆盖模板里的 LDAU*）----
    use_u, ldau_lines, u_note = decide_u(symbols)
    apply_u_to_incar(outdir / "INCAR", use_u, ldau_lines, u_note)
    if use_u:
        print(f"[..] DFT+U：ON  — {u_note}")
        print("     （U 值为文献起点，务必自查；step2/3 继承，step4 由 HSE_U_MODE 决定去留）")
    else:
        print(f"[..] DFT+U：off — {u_note}")

    # ---- 2D：变胞约束流派处理（OPTCELL 文件 / IOPTCELL 标签）----
    if dim == "2d":
        apply_cell_constraint_2d(outdir / "INCAR", outdir)

    heavy = sorted(set(symbols or []) & SOC_ELEMS)
    if heavy:
        print(f"[..] 含重元素 {'/'.join(heavy)}：step1/step2 保持共线（正常），"
              "SOC 会在 step3/step4 自动打开")

    # 记录方法，供后续步骤继承
    write_method_file(outdir / METHOD_FILE, label, formula, prim_note,
                      mag_line=f"MAG={'magnetic' if magnetic else 'nonmag'}",
                      dim_line=f"DIM={dim.upper()}")
    print(f"[OK] {METHOD_FILE}")

    print("\n文件检查：")
    names = ["POSCAR", "INCAR", "submit.sh", "KPOINTS", "POTCAR", METHOD_FILE]
    if dim == "2d" and CELL_CONSTRAINT_2D == "optcell_file":
        names.append("OPTCELL")
    for name in names:
        status = "OK" if (outdir / name).exists() else "MISSING"
        print(f"[{status}] {name}")

    if stage:
        idx = STAGE_ORDER.index(stage)
        if idx + 1 < len(STAGE_ORDER):
            nxt = STAGE_ORDER[idx + 1]
            print("[..] 跑完后执行 gen_step1_PBE_opt.py --stage %s（读 %s/CONTCAR 续接）"
                  % (nxt, outdir_name))
        else:
            print("[..] 这是最后一个弛豫阶段，跑完后执行 gen_step2_static.py")
    # tf 只取 gen 输出的最后一行来显示，所以把结论放在最后
    print("[DONE] %s 已生成（阶段 %s），可提交"
          % (outdir_name, stage if stage else "single"))


if __name__ == "__main__":
    main()
