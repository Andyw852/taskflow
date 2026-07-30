#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
dim_common.py —— 2D/3D 维度自动识别 + 模板选择（gen_step1~4 共用）
==================================================================
判据：
    沿某个晶格方向的最大真空间隙 >= vacuum_min（默认 8 Å）记该方向"有真空"。
        0 个方向有真空 -> 3D
        1 个方向有真空 -> 2D（记录真空轴）
        >=2 个方向     -> 1D/0D，本工作流不支持，直接报错交人工。
    真空厚度 = 该方向的垂直胞高 × 分数坐标最大间隙（含周期回绕）。

模板命名约定（放在工作流父目录）：
    incar_2d.tpl / incar_3d.tpl
    submit_std_2d.tpl / submit_std_3d.tpl
    submit_ncl_2d.tpl / submit_ncl_3d.tpl
    找不到带后缀的会回退到不带后缀的 incar.tpl / submit_std.tpl / submit_ncl.tpl
    （兼容旧用法：目录里只放一套时行为与旧版一致）。

维度继承：
    gen_step1 判定后写入 workflow_method.txt 的 DIM=2D/3D；
    step2/3/4 优先读上一步 workflow_method.txt 的 DIM=，读不到再按结构现场判定。

纯标准库实现（不依赖 numpy/pymatgen），gen_step1 保持零依赖可用。
"""

import re
from pathlib import Path

VACUUM_MIN = 8.0   # Å，真空判定阈值（2D 常用真空 15~25 Å，8 Å 足以与层间距区分）

AXIS_NAMES = ("a", "b", "c")


# ---------------------------------------------------------------- 3x3 线代
def _cross(u, v):
    return (u[1] * v[2] - u[2] * v[1],
            u[2] * v[0] - u[0] * v[2],
            u[0] * v[1] - u[1] * v[0])


def _dot(u, v):
    return u[0] * v[0] + u[1] * v[1] + u[2] * v[2]


def _norm(u):
    return (_dot(u, u)) ** 0.5


def _det3(m):
    return _dot(m[0], _cross(m[1], m[2]))


def _inv3(m):
    d = _det3(m)
    if abs(d) < 1e-12:
        raise ValueError("晶格矩阵奇异（体积为 0）")
    c0, c1, c2 = _cross(m[1], m[2]), _cross(m[2], m[0]), _cross(m[0], m[1])
    # inv = adj^T / det；adj 行 = 余子式叉积
    return [[c0[0] / d, c1[0] / d, c2[0] / d],
            [c0[1] / d, c1[1] / d, c2[1] / d],
            [c0[2] / d, c1[2] / d, c2[2] / d]]


# ---------------------------------------------------------------- POSCAR 解析
def read_poscar_cell_frac(path):
    """读 POSCAR，返回 (lattice 3x3 已含缩放, 分数坐标列表)。
       兼容 VASP4/5、Selective dynamics、Direct/Cartesian、负缩放（目标体积）。"""
    lines = Path(path).read_text(encoding="utf-8-sig").splitlines()
    if len(lines) < 8:
        raise ValueError("POSCAR 行数不足")

    scale = float(lines[1].split()[0])
    lat = [[float(x) for x in lines[2 + i].split()[:3]] for i in range(3)]
    if scale < 0:  # 负数 = 目标体积
        vol = abs(_det3(lat))
        scale = (abs(scale) / vol) ** (1.0 / 3.0)
    lat = [[scale * x for x in row] for row in lat]

    # 元素符号行（VASP5）可有可无
    idx = 5
    tokens = lines[idx].split()
    if not tokens:
        raise ValueError("POSCAR 第 6 行为空")
    if not re.fullmatch(r"[+-]?\d+", tokens[0]):
        idx += 1
    counts = [int(x) for x in lines[idx].split()]
    natoms = sum(counts)

    idx += 1
    if lines[idx].strip()[:1].upper() == "S":   # Selective dynamics
        idx += 1
    mode = lines[idx].strip()[:1].upper()       # D=Direct, C/K=Cartesian
    idx += 1

    coords = []
    for ln in lines[idx:idx + natoms]:
        t = ln.split()
        if len(t) < 3:
            raise ValueError("POSCAR 坐标行不完整: %r" % ln)
        coords.append([float(t[0]), float(t[1]), float(t[2])])
    if len(coords) != natoms:
        raise ValueError("POSCAR 坐标行数 (%d) 与原子数 (%d) 不符"
                         % (len(coords), natoms))

    if mode in ("C", "K"):
        inv = _inv3(lat)                        # frac = cart · lat^-1（行向量约定）
        cart = [[scale * x for x in c] for c in coords]   # Cartesian 同样乘缩放因子
        coords = [[_dot(c, [inv[0][j], inv[1][j], inv[2][j]]) for j in range(3)]
                  for c in cart]
    return lat, coords


def validate_poscar(path):
    """POSCAR/CONTCAR 完整性粗检：能完整解析返回 None；否则返回原因字符串。
    用途：弛豫写到一半的 CONTCAR 文件"存在但残缺"，直接拷给下一步会让
    vaspkit/VASP 读文件崩（forrtl end-of-file）——接力前先校验。"""
    p = Path(path)
    if not p.is_file():
        return "文件不存在"
    if p.stat().st_size == 0:
        return "空文件（上一步还没写出结构）"
    try:
        read_poscar_cell_frac(p)
    except Exception as e:
        return str(e)
    return None


# ---------------------------------------------------------------- 维度判定
def vacuum_per_axis(lat, frac):
    """返回沿 a/b/c 三个方向的真空厚度 (Å)：垂直胞高 × 最大分数间隙。"""
    vol = abs(_det3(lat))
    out = []
    for i in range(3):
        j, k = (i + 1) % 3, (i + 2) % 3
        area = _norm(_cross(lat[j], lat[k]))
        height = vol / area if area > 1e-12 else 0.0
        f = sorted((c[i] % 1.0) for c in frac)
        if len(f) == 1:
            gap = 1.0
        else:
            gaps = [f[n + 1] - f[n] for n in range(len(f) - 1)]
            gaps.append(f[0] + 1.0 - f[-1])
            gap = max(gaps)
        out.append(gap * height)
    return out


def detect_dimension(poscar_path, vacuum_min=VACUUM_MIN):
    """按结构判定维度。返回 (dim, axis, vacuums)：
       dim = "2d"/"3d"；axis = 真空轴 0/1/2（3D 时为 None）；vacuums = 三方向真空 Å。
       检测到 >=2 个真空方向（1D/0D）直接 SystemExit。"""
    lat, frac = read_poscar_cell_frac(poscar_path)
    vacs = vacuum_per_axis(lat, frac)
    hit = [i for i, v in enumerate(vacs) if v >= vacuum_min]
    if len(hit) >= 2:
        raise SystemExit(
            "[ERROR] %s 检测到 %d 个方向有 >= %.1f Å 真空（%s）—— 疑似 1D/0D 体系，"
            "本工作流只支持 2D/3D。若判定有误，请调整 vacuum_min 或强制 DIMENSION。"
            % (poscar_path, len(hit), vacuum_min,
               ", ".join("%s=%.1f Å" % (AXIS_NAMES[i], vacs[i]) for i in hit)))
    if len(hit) == 1:
        return "2d", hit[0], vacs
    return "3d", None, vacs


# ---------------------------------------------------------------- DIM 继承
def read_dim(method_file):
    """读 workflow_method.txt 的 DIM=2D/3D；没有返回 None。"""
    p = Path(method_file)
    if not p.exists():
        return None
    for line in p.read_text(encoding="utf-8", errors="ignore").splitlines():
        if line.upper().startswith("DIM="):
            val = line.split("=", 1)[1].strip().lower()
            if val in ("2d", "3d"):
                return val
    return None


def resolve_dim(method_file, struct_path, vacuum_min=VACUUM_MIN):
    """step2/3/4 用：优先继承上一步 workflow_method.txt 的 DIM=，
       缺失时按结构现场判定。返回 (dim, 说明字符串)。"""
    dim = read_dim(method_file)
    if dim:
        return dim, "继承自 %s (DIM=%s)" % (method_file, dim.upper())
    dim, axis, vacs = detect_dimension(struct_path, vacuum_min)
    if dim == "2d":
        note = ("按结构判定：沿 %s 轴真空 %.1f Å"
                % (AXIS_NAMES[axis], vacs[axis]))
    else:
        note = ("按结构判定：无真空方向 (max=%.1f Å < %.1f Å)"
                % (max(vacs), vacuum_min))
    return dim, note + "（上一步 workflow_method.txt 无 DIM= 记录，建议用新版 gen_step1 重建）"


# ---------------------------------------------------------------- 模板选择
def resolve_tpl(base_dir, base, dim):
    """按维度选模板：<base>_<dim>.tpl 优先，回退 <base>.tpl；都没有则报错。"""
    base_dir = Path(base_dir)
    cand = base_dir / ("%s_%s.tpl" % (base, dim))
    if cand.exists():
        return cand
    fallback = base_dir / ("%s.tpl" % base)
    if fallback.exists():
        return fallback
    raise SystemExit(
        "[ERROR] 找不到 %s 材料的模板：%s（也没有回退模板 %s）"
        % (dim.upper(), cand.name, fallback.name))


# ---------------------------------------------------------------- KPOINTS kz->1
def force_kz1(kpoints_path, axis=2):
    """2D：把 VASPKIT 自动网格 KPOINTS 中真空方向的细分强制改为 1。
       返回 (changed, note)。非自动网格格式不动。"""
    p = Path(kpoints_path)
    if not p.exists():
        return False, "KPOINTS 不存在"
    lines = p.read_text(errors="ignore").splitlines()
    if len(lines) < 4:
        return False, "KPOINTS 行数不足，未修改"
    t1 = lines[1].split()
    if not t1 or t1[0].strip() != "0":
        return False, "KPOINTS 非自动网格格式（第 2 行不是 0），未修改"
    parts = lines[3].split()
    try:
        nums = [int(x) for x in parts[:3]]
    except (ValueError, IndexError):
        return False, "无法解析 KPOINTS 细分行，未修改"
    if nums[axis] == 1:
        return False, "真空方向细分已是 1"
    old = nums[axis]
    nums[axis] = 1
    tail = ("  " + " ".join(parts[3:])) if len(parts) > 3 else ""
    lines[3] = "  ".join(str(n) for n in nums) + tail
    p.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    return True, "%s 方向 %d -> 1" % (AXIS_NAMES[axis], old)


# ---------------------------------------------------------------- 2D 路径过滤
def filter_kpath_2d(kpt_coords, segments, axis=2, tol=1e-3):
    """2D：从 seekpath/SC 的三维路径里剔除真空方向分量非零的高对称点
       （六方的 A/L/H 之类，对 2D 无物理意义），并按剔除点切断分段。
       返回 (kpt_coords, new_segments, dropped_labels)。"""
    def _off_plane(c):
        z = float(c[axis]) % 1.0
        return min(z, 1.0 - z) > tol

    dropped = sorted({lab for lab, c in kpt_coords.items() if _off_plane(c)})
    if not dropped:
        return kpt_coords, [list(s) for s in segments], []

    bad = set(dropped)
    new_segments = []
    for seg in segments:
        cur = []
        for lab in seg:
            if lab in bad:
                if len(cur) >= 2:
                    new_segments.append(cur)
                cur = []
            else:
                cur.append(lab)
        if len(cur) >= 2:
            new_segments.append(cur)
    kept = {lab: c for lab, c in kpt_coords.items() if lab not in bad}
    return kept, new_segments, dropped
