#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""apply_patch2.py —— 模板目录布局（v1.3）。

在已打过 apply_patch.py 的 tf 上追加：技能目录里的模板可以收进
templates/ 子目录，并可按步骤再分子目录。

    python3 apply_patch2.py <tf 路径> [-o 输出路径]

默认输出 <tf>.patched2。每处锚点都做唯一性断言，可重复运行。
"""
import argparse
import os
import sys

PRE_MARK = 'SKILL_MANIFEST = "skill.yaml"'      # 必须先打过 apply_patch.py
APPLIED_MARK = "def _skill_asset_dirs("

# ---------------------------------------------------------------------------
# P1  清单里认 template_dir / template_layout 两个键
# ---------------------------------------------------------------------------
P1_OLD = '''_MANIFEST_TYPE_KEYS = ("desc", "steps", "optional_steps", "gen_need", "aux_files",
                       "gen_dir", "plot_steps", "run_steps", "dir_name",
                       "skill_subdir", "hpc", "work_dir", "root")'''
P1_NEW = '''_MANIFEST_TYPE_KEYS = ("desc", "steps", "optional_steps", "gen_need", "aux_files",
                       "gen_dir", "plot_steps", "run_steps", "dir_name",
                       "skill_subdir", "hpc", "work_dir", "root",
                       "template_dir", "template_layout")'''

# ---------------------------------------------------------------------------
# P2  技能目录内部的查找顺序（新函数）+ find_asset 接受步骤名
# ---------------------------------------------------------------------------
P2_OLD = '''def find_asset(cfg, t, m, fname):
    """v3 资源查找链：材料/<技能>/逻辑名（v1.6 最优先）→ project_setting/逻辑名
    → project_setting/映射名 → skill_dir/逻辑名 → skill_dir/映射名。'''

P2_NEW = '''def _skill_asset_dirs(t, m, base, sname=None):
    """一个技能根目录下的查找顺序（模板目录布局，v1.3）。

    template_layout: shared（缺省）
        <技能>/templates/<文件>   →  <技能>/<文件>
        所有步骤共用同一套模板。

    template_layout: per_step
        <技能>/templates/<步骤名>/<文件>  →  <技能>/templates/<文件>
                                          →  <技能>/<文件>
        每个步骤先找自己的目录；步骤目录里没有才回落到公共模板。
        不知道是哪个步骤时（如 tf hpc 查模板齐不齐），所有步骤目录都算命中。

    两种布局都保留最后的平铺兜底，所以模板直接摊在技能根目录下依然能用。
    """
    seg = (m.get("_seg") or {})
    tdir = str(seg.get("template_dir") or t.get("template_dir") or "templates")
    layout = str(seg.get("template_layout") or t.get("template_layout")
                 or "shared").strip().lower()
    troot = os.path.join(base, tdir)
    out = []
    if layout == "per_step":
        if sname:
            out.append(os.path.join(troot, str(sname)))
        else:
            out.extend(sorted(d for d in glob.glob(os.path.join(troot, "*"))
                              if os.path.isdir(d)))
    out.append(troot)
    out.append(base)
    return out


def find_asset(cfg, t, m, fname, sname=None):
    """v3 资源查找链：材料/<技能>/逻辑名（v1.6 最优先）→ project_setting/逻辑名
    → project_setting/映射名 → skill_dir 内按 _skill_asset_dirs 的顺序（v1.3）。'''

# ---------------------------------------------------------------------------
# P3  find_asset 里改用新的目录顺序
# ---------------------------------------------------------------------------
P3_OLD = '''    for base in sdirs:
        cands.append(os.path.join(base, fname))
        if real:
            cands.append(os.path.join(base, real))
    for c in cands:'''
P3_NEW = '''    for base in sdirs:
        for d in _skill_asset_dirs(t, m, base, sname):   # v1.3：模板目录布局
            cands.append(os.path.join(d, fname))
            if real:
                cands.append(os.path.join(d, real))
    for c in cands:'''

# ---------------------------------------------------------------------------
# P4  remote_gen 把步骤名传下去（per_step 布局靠它定位）
# ---------------------------------------------------------------------------
P4_OLD = '        gsrc = find_asset(cfg, t, m, gen_script)'
P4_NEW = '        gsrc = find_asset(cfg, t, m, gen_script, sname)'

P5_OLD = '        local_src = find_asset(cfg, t, m, f)'
P5_NEW = '        local_src = find_asset(cfg, t, m, f, sname)'

# ---------------------------------------------------------------------------
# P6  _seg 带上两个新键（项目段也能覆盖布局）
# ---------------------------------------------------------------------------
P6_OLD = '''                r["_seg"] = {"steps_cfg": t.get("steps"),
                             "gen_need": t.get("gen_need"),
                             "aux_files": t.get("aux_files"),
                             "skill_dir": t.get("skill_dir"),'''
P6_NEW = '''                r["_seg"] = {"steps_cfg": t.get("steps"),
                             "gen_need": t.get("gen_need"),
                             "aux_files": t.get("aux_files"),
                             "skill_dir": t.get("skill_dir"),
                             "template_dir": t.get("template_dir"),
                             "template_layout": t.get("template_layout"),'''

# ---------------------------------------------------------------------------
# P7  tf init 复制模板时也走新布局；per_step 布局不往 project_setting 复制
#     （project_setting 优先级高于技能目录，复制进去会让一份模板盖住所有步骤）
# ---------------------------------------------------------------------------
P7_OLD = '''        srcf = os.path.join(sd, real) if sd else None
        if srcf and os.path.isfile(srcf):
            shutil.copyfile(srcf, dst)
            print("已复制模板 %s" % dst)
        else:
            print("提示：skill_dir 里找不到 %s，请手动放入 %s" % (real, dst))'''
P7_NEW = '''        _layout = str((t or {}).get("template_layout") or "shared").lower()
        if _layout == "per_step":
            # 每步一套模板：不能复制到 project_setting（那里一份会盖住所有步骤）。
            # 模板留在 skill/<技能>/templates/<步骤名>/，要按项目改就放
            # 材料/<技能>/ 下（优先级仍高于技能目录）。
            continue
        srcf = None
        for _d in (_skill_asset_dirs(t or {}, {}, sd) if sd else []):
            _c = os.path.join(_d, real)
            if os.path.isfile(_c):
                srcf = _c
                break
        if srcf:
            shutil.copyfile(srcf, dst)
            print("已复制模板 %s" % dst)
        else:
            print("提示：skill_dir 里找不到 %s，请手动放入 %s" % (real, dst))'''

PATCHES = [
    ("P1  清单认 template_dir / template_layout", P1_OLD, P1_NEW),
    ("P2  _skill_asset_dirs + find_asset 签名", P2_OLD, P2_NEW),
    ("P3  find_asset 使用新目录顺序", P3_OLD, P3_NEW),
    ("P4  remote_gen 传步骤名（gen 脚本）", P4_OLD, P4_NEW),
    ("P5  remote_gen 传步骤名（依赖文件）", P5_OLD, P5_NEW),
    ("P6  _seg 携带布局字段", P6_OLD, P6_NEW),
    ("P7  tf init 按布局取模板", P7_OLD, P7_NEW),
]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("tf")
    ap.add_argument("-o", "--out")
    a = ap.parse_args()
    src = open(a.tf, encoding="utf-8").read()
    if PRE_MARK not in src:
        sys.exit("失败：这个 tf 还没打过 apply_patch.py（找不到技能注册表）。")
    if APPLIED_MARK in src:
        sys.exit("该 tf 已经打过本补丁，无需重复执行。")

    for name, old, new in PATCHES:
        n = src.count(old)
        if n != 1:
            sys.exit("失败：%s 的锚点出现 %d 次（应为 1 次）。\n锚点：%s"
                     % (name, n, old.splitlines()[0][:70]))
        src = src.replace(old, new, 1)
        print("  ok  " + name)

    out = a.out or (a.tf + ".patched2")
    with open(out, "w", encoding="utf-8") as f:
        f.write(src)
    os.chmod(out, 0o755)
    print("\n已写出 %s（%d 行）" % (out, src.count("\n") + 1))


if __name__ == "__main__":
    main()
