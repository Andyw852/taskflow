#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
mol_common.py — gen_step1_PBE_opt.py 的 0D（孤立分子/团簇）分支

为什么单独一个模块：M@C60 这类"分子放在真空盒里"的体系和层状体相在
几乎每一个自动判定上都反着来（维度、变胞、k 点、磁性、U、偶极），
硬塞进原来的 2D/3D 流程要改十几处，容易把已经跑通的 band 技能搞坏。
这里把 0D 整条路径独立出来，主脚本只需要加两行 hook。

主脚本 gen_step1_PBE_opt.py 里的改法（就这两处）：

    import mol_common                                     # 与其它 import 放一起

    def main():
        cwd = Path.cwd()
        if not (cwd / "POSCAR").exists():
            sys.exit("[ERROR] 当前目录缺少 POSCAR")

        # ↓↓↓ 新增：0D 体系走独立分支，其余逻辑完全不受影响
        if mol_common.is_molecule(cwd / "POSCAR", VACUUM_MIN, DIMENSION):
            mol_common.generate(cwd, globals())
            return
        # ↑↑↑

        prim_note = ensure_primitive(cwd / "POSCAR")
        ...

判定规则：POSCAR 有 >=2 个方向的真空间隙 >= VACUUM_MIN 就是 0D
（原来的 detect_dimension 遇到这种情况是直接报错交人工的）。
也可以在主脚本里把 DIMENSION 设成 "0d" 强制走这里。

模板：优先用父目录的 incar_0d.tpl / submit_std_0d.tpl，
      没有就回退到 incar_3d.tpl / submit_std_3d.tpl（下面的后处理会把
      不适合分子的标签全部改掉，所以直接借用 3D 模板是安全的）。
"""

import re
import sys
from pathlib import Path

import numpy as np

# =====================================================================
#                      0D 专用配置（只影响分子分支）
# =====================================================================
OUTDIR_NAME = "step1_PBE_opt"   # 与主脚本 single 模式同名，tf 的 check_* 能直接认

# --- 结构弛豫：分子在真空盒里只能固定胞 ---
# ISIF=3 会把没有能量代价的真空一起弛豫掉，盒子直接塌到贴着分子上，
# 于是每个体系的盒子都不一样，能量再也没法横向比。所以 0D 只做一段 ISIF=2。
MOL_ISIF = "2"
MOL_IBRION = "2"
MOL_NSW = "300"
MOL_EDIFFG = "-0.01"        # 分子不需要 -0.001，那是给声子/力常数留的
MOL_POTIM = "0.2"

# --- k 点：只要 Γ ---
# VASPKIT 的 KP-resolved 0.03 对 20 Å 的盒子会给出 2x2x2，8 倍机时烧在
# 没有物理意义的"分子能带"上。这里直接写死 Γ。
MOL_GAMMA_ONLY = True

# --- 偶极修正 ---
# Li@C60 实际是 Li+@C60-，有净偶极；周期镜像间的偶极-偶极作用在 20 Å 盒里
# 是十几 meV 量级，恰好是排包合能顺序的分辨率。
MOL_DIPOLE = True
MOL_IDIPOL = "4"

# --- 其它分子专用标签 ---
MOL_ISYM = "0"          # 偏心金属别被对称化拉回高对称位；None=不写
MOL_LREAL = ".FALSE."   # 实空间投影的力噪声底在 1e-3，会卡住紧判据；None=不写
MOL_KPAR = "1"          # 只有一个不可约 k 点，KPAR>1 无意义甚至报错；None=不写
MOL_LASPH = ".TRUE."    # 非球形梯度修正，含 d/f 原子建议开；None=不写

# --- 磁性 ---
# 元素表那套（只认 3d/4f/5f）会把 Li@C60 / K@C60 / Al@C60 / N@C60 判成非磁，
# 但它们都是奇电子体系，ISPIN=1 强行成对，能量偏高且不物理。
# 这里改成按 POTCAR 的 ZVAL 数总价电子：奇数 -> 必须 ISPIN=2。
MOL_FORCE_ISPIN2 = True       # True: 一律 ISPIN=2（闭壳层会自己塌到 0，代价只是慢一点）
MOL_DEFAULT_MOMENT = 1.0      # 不在磁性元素表里的客体原子，初始磁矩给这个值
MOL_HOST_ELEMENT = "C"        # 笼子元素，初始磁矩给 0

# --- DFT+U ---
# 表里的 U 是从氧化物拟合的，套到碳笼里的裸原子没有依据；更要命的是
# 只有部分元素在表里，会让序列一半 GGA、一半 GGA+U，总能不可比。
MOL_DISABLE_U = True

# --- ENCUT ---
# 默认沿用主脚本的逐体系 auto（= ENCUT_FACTOR x max(ENMAX)）。
# MOL_ENCUT_FLOOR 给整个序列一个下限：auto 值低于它就抬上去，
# 这样大多数体系落在同一个值上，又不会让 ENMAX 高的势（Li_sv 之类）欠收敛。
# 设 None = 完全不干预。用法：想全序列固定就把主脚本的 MANUAL_ENCUT 写死。
MOL_ENCUT_FLOOR = None        # 例如 650
# =====================================================================


# ---------------------------------------------------------------------
# 维度判定
# ---------------------------------------------------------------------
def vacuum_gaps(poscar: Path):
    """返回沿三个晶轴的最大真空间隙 (Å)。周期性地找分数坐标的最大空隙。"""
    lines = Path(poscar).read_text(encoding="utf-8-sig").splitlines()
    scale = float(lines[1].split()[0])
    latt = np.array([[float(x) for x in lines[i].split()[:3]] for i in (2, 3, 4)]) * scale
    line6 = lines[5].split()
    if line6 and line6[0].lstrip("-").isdigit():
        counts, i = [int(x) for x in line6], 6
    else:
        counts, i = [int(x) for x in lines[6].split()], 7
    if lines[i].strip()[:1].upper() == "S":
        i += 1
    direct = lines[i].strip()[:1].upper() == "D"
    i += 1
    n = sum(counts)
    pos = np.array([[float(x) for x in lines[i + k].split()[:3]] for k in range(n)])
    frac = pos if direct else pos @ np.linalg.inv(latt)
    frac = frac % 1.0

    gaps = []
    for ax in range(3):
        f = np.sort(frac[:, ax])
        d = np.diff(np.append(f, f[0] + 1.0))          # 环形间隙
        gaps.append(float(d.max() * np.linalg.norm(latt[ax])))
    return gaps


def is_molecule(poscar: Path, vacuum_min: float, dimension_setting: str = "auto"):
    """>=2 个方向有真空 -> 0D。DIMENSION='0d' 可强制；'2d'/'3d' 则一定不走这里。"""
    mode = str(dimension_setting).lower()
    if mode == "0d":
        return True
    if mode in ("2d", "3d"):
        return False
    gaps = vacuum_gaps(poscar)
    return sum(1 for g in gaps if g >= vacuum_min) >= 2


# ---------------------------------------------------------------------
# POTCAR 解析：价电子总数（判奇偶）
# ---------------------------------------------------------------------
def potcar_zvals(potcar: Path):
    """按 POTCAR 中出现顺序返回各元素的 ZVAL。"""
    zs = []
    for line in Path(potcar).read_text(errors="ignore").splitlines():
        m = re.search(r"ZVAL\s*=\s*([\d.]+)", line)
        if m:
            zs.append(float(m.group(1)))
    return zs


def valence_electrons(potcar: Path, counts):
    zs = potcar_zvals(potcar)
    if len(zs) != len(counts):
        return None
    return sum(z * n for z, n in zip(zs, counts))


# ---------------------------------------------------------------------
# INCAR 后处理
# ---------------------------------------------------------------------
def _strip(lines, keys):
    pat = re.compile(r"\s*(%s)\s*=" % "|".join(keys), re.IGNORECASE)
    return [ln for ln in lines if not pat.match(ln)]


def structure_center_frac(poscar: Path):
    """结构（几何）中心的分数坐标，用作 DIPOL —— 偶极修正的参考点。"""
    lines = Path(poscar).read_text(encoding="utf-8-sig").splitlines()
    scale = float(lines[1].split()[0])
    latt = np.array([[float(x) for x in lines[i].split()[:3]] for i in (2, 3, 4)]) * scale
    line6 = lines[5].split()
    if line6 and line6[0].lstrip("-").isdigit():
        counts, i = [int(x) for x in line6], 6
    else:
        counts, i = [int(x) for x in lines[6].split()], 7
    if lines[i].strip()[:1].upper() == "S":
        i += 1
    direct = lines[i].strip()[:1].upper() == "D"
    i += 1
    n = sum(counts)
    pos = np.array([[float(x) for x in lines[i + k].split()[:3]] for k in range(n)])
    frac = pos if direct else pos @ np.linalg.inv(latt)
    return (frac.mean(axis=0) % 1.0)


def apply_molecule_incar(incar_path: Path, poscar: Path = None):
    """把 3D 体相模板改造成分子模板：固定胞、Γ、偶极、关对称、实空间投影。"""
    keys = ["ISIF", "IBRION", "NSW", "EDIFFG", "POTIM", "IOPTCELL",
            "ISYM", "LREAL", "KPAR", "LASPH", "IDIPOL", "LDIPOL", "DIPOL"]
    keep = _strip(Path(incar_path).read_text(encoding="utf-8").splitlines(), keys)
    keep += ["", "# ---- 0D 分子模式（mol_common 注入）----"]
    keep.append("%-8s = %s   # 固定晶胞：真空没有能量代价，ISIF=3 会把盒子压塌" % ("ISIF", MOL_ISIF))
    for k, v in (("IBRION", MOL_IBRION), ("POTIM", MOL_POTIM),
                 ("NSW", MOL_NSW), ("EDIFFG", MOL_EDIFFG),
                 ("ISYM", MOL_ISYM), ("LREAL", MOL_LREAL),
                 ("KPAR", MOL_KPAR), ("LASPH", MOL_LASPH)):
        if v is not None:
            keep.append("%-8s = %s" % (k, v))
    if MOL_DIPOLE:
        keep.append("LDIPOL   = .TRUE.")
        keep.append("IDIPOL   = %s   # 客体->笼电荷转移带来净偶极，需修正镜像相互作用"
                    % MOL_IDIPOL)
        if poscar is not None:
            c = structure_center_frac(poscar)
            keep.append("DIPOL    = %.4f %.4f %.4f   # 偶极参考点=结构几何中心"
                        % tuple(c))
    Path(incar_path).write_text("\n".join(keep) + "\n", encoding="utf-8", newline="\n")


def apply_molecule_magnetism(incar_path: Path, symbols, counts, nelect, mag_table):
    """按价电子奇偶 + 元素表决定 ISPIN/MAGMOM。返回一行说明。"""
    keep = _strip(Path(incar_path).read_text(encoding="utf-8").splitlines(),
                  ["ISPIN", "MAGMOM", "NUPDOWN"])

    odd = (nelect is not None) and (abs(nelect - round(nelect)) < 1e-6) and (int(round(nelect)) % 2 == 1)
    guest = [s for s in (symbols or []) if s != MOL_HOST_ELEMENT]
    tm_hit = [s for s in guest if mag_table.get(s, 0.0) != 0.0]

    if MOL_FORCE_ISPIN2 or odd or tm_hit:
        moments = []
        for s, n in zip(symbols, counts):
            if s == MOL_HOST_ELEMENT:
                m = 0.0
            else:
                m = mag_table.get(s, MOL_DEFAULT_MOMENT) or MOL_DEFAULT_MOMENT
            moments.append("%d*%g" % (n, m))
        magmom = "  ".join(moments)
        why = ("总价电子 %s（奇数，必须开自旋）" % (int(round(nelect)) if nelect else "?")
               if odd else
               ("含磁性候选 %s" % "/".join(tm_hit) if tm_hit else "MOL_FORCE_ISPIN2=True"))
        keep += ["", "# ---- 磁性（mol_common：%s）----" % why,
                 "ISPIN    = 2", "MAGMOM   = %s" % magmom]
        note = "ISPIN=2, MAGMOM=%s — %s" % (magmom, why)
    else:
        keep += ["", "# ---- 磁性（mol_common：偶电子且无磁性候选元素）----", "ISPIN    = 1"]
        note = "ISPIN=1（偶电子闭壳层）"
    Path(incar_path).write_text("\n".join(keep) + "\n", encoding="utf-8", newline="\n")
    return note


def disable_u(incar_path: Path):
    keep = _strip(Path(incar_path).read_text(encoding="utf-8").splitlines(),
                  ["LDAU", "LDAUTYPE", "LDAUL", "LDAUU", "LDAUJ", "LDAUPRINT"])
    keep += ["", "# ---- DFT+U：0D 模式默认关闭（mol_common）----",
             "# 表里的 U 拟合自氧化物，对碳笼内的裸原子没有依据；且只有部分元素在表里，",
             "# 会让序列一半 GGA 一半 GGA+U，总能不可比。要加 U 请整个序列统一加。"]
    Path(incar_path).write_text("\n".join(keep) + "\n", encoding="utf-8", newline="\n")


def write_gamma_kpoints(outdir: Path):
    (outdir / "KPOINTS").write_text(
        "Gamma only (0D molecule)\n0\nGamma\n1 1 1\n0 0 0\n",
        encoding="utf-8", newline="\n")


# ---------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------
def _pick_tpl(cwd: Path, stem: str, G):
    """优先 <stem>_0d.tpl，其次回退到主脚本的 3D 模板解析。"""
    for base in (cwd, cwd.parent):
        cand = base / ("%s_0d.tpl" % stem)
        if cand.is_file():
            return cand
    return G["resolve_tpl"](cwd, stem, "3d")


def generate(cwd: Path, G):
    """0D 分支的完整生成流程。G = 主脚本的 globals()。"""
    print("[..] 维度：0D — 检出 >=2 个真空方向（孤立分子/团簇），走 mol_common 分支")
    gaps = vacuum_gaps(cwd / "POSCAR")
    print("[..] 各晶轴真空间隙：a=%.1f b=%.1f c=%.1f Å" % tuple(gaps))
    print("[SKIP] 原胞检查（分子无平移对称性可约化）")

    incar_tpl = _pick_tpl(cwd, "incar", G)
    submit_tpl = _pick_tpl(cwd, "submit_std", G)
    print("[..] 模板：%s + %s" % (incar_tpl.name, submit_tpl.name))

    func, func_src = G["resolve_func"](incar_tpl, OUTDIR_NAME)
    G["FUNC"] = func                      # 让主脚本的 build_params/validate 用同一个值
    G["validate_user_config"]()
    print("[..] 泛函：%s（来源：%s）" % (func, func_src))

    label, formula = G["read_poscar_identity"](cwd / "POSCAR")
    params = G["build_params"](label)
    outdir = cwd / OUTDIR_NAME
    outdir.mkdir(exist_ok=True)
    print("[..] 结构标签：%s   化学式：%s" % (label, formula))
    print("[..] 输出目录：%s" % outdir)

    (outdir / "POSCAR").write_text(
        (cwd / "POSCAR").read_text(encoding="utf-8-sig"),
        encoding="utf-8", newline="\n")
    print("[OK] POSCAR")

    G["render"](submit_tpl, outdir / "submit.sh", params)
    G["override_submit_slurm"](outdir / "submit.sh", G["SUBMIT_OVERRIDE"])

    # KPOINTS：Γ 点直接写，不跑 vaspkit 102
    if MOL_GAMMA_ONLY:
        write_gamma_kpoints(outdir)
        print("[OK] KPOINTS（Γ only）")
    have_potcar = (outdir / "POTCAR").exists()
    if G["RUN_VASPKIT"]:
        try:
            G["run_vaspkit_potcar"](G["VASPKIT_EXE"], outdir)
            have_potcar = (outdir / "POTCAR").exists()
        except FileNotFoundError:
            sys.exit("[ERROR] 找不到 VASPKIT：%s" % G["VASPKIT_EXE"])
    else:
        print("[SKIP] RUN_VASPKIT=False，未生成 POTCAR")

    # ENCUT
    if G["MANUAL_ENCUT"] is not None:
        encut = int(G["MANUAL_ENCUT"])
        print("[..] 使用手动 ENCUT = %d eV（全序列固定）" % encut)
    elif have_potcar:
        encut = G["encut_from_potcar"](outdir / "POTCAR", G["ENCUT_FACTOR"])
        if MOL_ENCUT_FLOOR and encut < MOL_ENCUT_FLOOR:
            print("[..] ENCUT %d 低于序列下限 %d，抬到下限" % (encut, MOL_ENCUT_FLOOR))
            encut = MOL_ENCUT_FLOOR
    else:
        encut = int(G["FALLBACK_ENCUT"])
        print("[WARN] 没有 POTCAR，ENCUT 暂用兜底值 %d eV" % encut)
    params["ENCUT"] = str(encut)

    # INCAR：先渲染 + 泛函校验，再做分子后处理
    G["render"](incar_tpl, outdir / "INCAR", params)
    G["validate_generated_incar"](outdir / "INCAR")
    print("[OK] INCAR 泛函检查通过")

    apply_molecule_incar(outdir / "INCAR", outdir / "POSCAR")
    print("[OK] 分子模式标签已注入（ISIF=2 / Γ / 偶极修正 / ISYM=0 / LREAL=.FALSE.）")

    symbols, counts = G["read_species_and_counts"](outdir / "POSCAR")
    nelect = valence_electrons(outdir / "POTCAR", counts) if have_potcar else None
    mag_note = apply_molecule_magnetism(outdir / "INCAR", symbols, counts,
                                        nelect, G["MAG_ELEM_MOMENTS"])
    print("[..] 磁性：%s" % mag_note)
    if nelect is None and have_potcar:
        print("[WARN] POTCAR 的 ZVAL 数与元素数对不上，未能判奇偶")

    lmaxmix, lmm_note = G["decide_lmaxmix"](symbols)
    G["apply_lmaxmix_to_incar"](outdir / "INCAR", lmaxmix, lmm_note)
    print("[..] LMAXMIX = %d — %s" % (lmaxmix, lmm_note))

    if MOL_DISABLE_U:
        disable_u(outdir / "INCAR")
        print("[..] DFT+U：off（0D 模式默认关闭，保证序列内总能可比）")

    # workflow_method.txt：把 ENCUT/NELECT 也记下来，
    # 后面算包合能时可以核对空笼、块体参考是不是同一档
    method = G["FUNC_MAP"][func]
    lines = ["FUNC=%s" % func, "GGA=%s" % method["GGA"],
             "IVDW=%s" % (method["IVDW"] or "NONE"),
             "LABEL=%s" % label, "FORMULA=%s" % formula,
             "DIM=0D", "ENCUT=%d" % encut,
             "NELECT=%s" % ("%d" % round(nelect) if nelect else "unknown"),
             "MAG=%s" % ("magnetic" if "ISPIN    = 2" in
                         (outdir / "INCAR").read_text(encoding="utf-8") else "nonmag")]
    (outdir / "workflow_method.txt").write_text("\n".join(lines) + "\n",
                                                encoding="utf-8", newline="\n")
    print("[OK] workflow_method.txt")

    print("\n文件检查：")
    for name in ("POSCAR", "INCAR", "submit.sh", "KPOINTS", "POTCAR",
                 "workflow_method.txt"):
        print("[%s] %s" % ("OK" if (outdir / name).exists() else "MISSING", name))
    print("[..] 0D 模式只有一段 ISIF=2 弛豫，跑完直接进 step2，不要再 --stage b/c")
    print("[DONE] %s 已生成（0D 分子模式），可提交" % OUTDIR_NAME)
