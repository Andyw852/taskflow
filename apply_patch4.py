#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""apply_patch4.py —— 分组源目录布局（v1.5）。

技能源目录可以「大步骤套小步骤」，每个步骤在 skill.yaml 里用 src 指明
自己的源文件在技能目录下的哪个子路径（相对技能根）：

    steps:
      - {name: step1_std_opt, src: step1_opt/, ...}
      - {name: step2_PBE_static, src: bandgap/step2_static/, ...}
      - {name: step3_PBE_WAVECAR, src: bandgap/step3_wavecar/, ...}

于是磁盘上可以长这样（大步骤是文件夹，里面套小步骤）：

    skill/ke/
    ├── step1_opt/           gen + 模板
    ├── bandgap/             ← 大步骤文件夹
    │   ├── step2_static/    gen + 模板
    │   ├── step3_wavecar/
    │   └── step4_hse/
    └── deform/
        ├── step9_deform/
        └── step9b_read/

而超算上的**材料计算目录仍是平的**（step2_PBE_static/ 等），不受影响 ——
src 只改「去技能目录哪个子文件夹找源文件」，不改「在材料目录下建哪个计算目录」。

src 未设时，行为完全等同 v1.3 的 per_step（找 <技能>/<步骤名>/）。
所以这个补丁对现有 band / elastic / 扁平 ke 零影响。

前置：已打过 apply_patch.py / 2 / 3。

    python3 apply_patch4.py <tf 路径> [-o 输出路径]
"""
import argparse
import os
import sys

PRE = ["def _skill_asset_dirs(", "def remote_sbatch_fanout("]
APPLIED = "# v1.5 src"

# ---------------------------------------------------------------------------
# _skill_asset_dirs：per_step 分支里，优先用步骤的 src 子路径
# ---------------------------------------------------------------------------
OLD = '''    troot = os.path.join(base, tdir)
    out = []
    if layout == "per_step":
        if sname:
            out.append(os.path.join(troot, str(sname)))
        else:
            out.extend(sorted(d for d in glob.glob(os.path.join(troot, "*"))
                              if os.path.isdir(d)))
    out.append(troot)
    out.append(base)
    return out'''

NEW = '''    troot = os.path.join(base, tdir)
    out = []
    # v1.5 src：步骤在清单里声明的源子路径（相对技能根），大步骤套小步骤时用。
    # steps_cfg 经 _seg 下发到采集器，本地则从 t["steps"] 取。
    steps_cfg = list(seg.get("steps_cfg") or t.get("steps_cfg")
                     or t.get("steps") or [])
    for _grp in (t.get("optional_steps") or {}).values():   # 可选组里的步骤也带 src
        steps_cfg += (_grp or {}).get("steps") or []
    src_map = {}
    for _s in steps_cfg:
        if _s.get("src"):
            src_map[_s.get("name")] = str(_s["src"]).strip("/")
    if layout == "per_step":
        if sname:
            if sname in src_map:
                out.append(os.path.join(base, src_map[sname]))
            out.append(os.path.join(troot, str(sname)))
        else:
            for _v in src_map.values():          # 不指定步骤：所有 src 都算命中
                out.append(os.path.join(base, _v))
            out.extend(sorted(d for d in glob.glob(os.path.join(troot, "*"))
                              if os.path.isdir(d)))
    out.append(troot)
    out.append(base)
    seen, uniq = set(), []
    for d in out:
        rd = os.path.normpath(d)
        if rd not in seen:
            seen.add(rd)
            uniq.append(d)
    return uniq'''

# steps 里的 src 也要能透传到采集器（_seg.steps_cfg 已整体带过去，无需额外改）
# 但 _LOCAL_ONLY_STEP_KEYS 要把 src 加进去，别下发给远端当计算参数
LO_OLD = '''_LOCAL_ONLY_STEP_KEYS = {"gen", "gen_need", "aux_files", "run", "group", "seq",
                         "contcar_to_poscar", "fetch_all", "fetch_files", "after"}'''
LO_NEW = '''_LOCAL_ONLY_STEP_KEYS = {"gen", "gen_need", "aux_files", "run", "group", "seq",
                         "contcar_to_poscar", "fetch_all", "fetch_files", "after",
                         "src"}   # v1.5 src'''


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("tf")
    ap.add_argument("-o", "--out")
    a = ap.parse_args()
    src = open(a.tf, encoding="utf-8").read()
    for mark in PRE:
        if mark not in src:
            sys.exit("失败：缺少前置补丁（找不到 %s）。" % mark)
    if APPLIED in src:
        sys.exit("该 tf 已经打过本补丁，无需重复执行。")

    for name, old, new in [("_skill_asset_dirs 支持 src", OLD, NEW),
                           ("src 加入本地键黑名单", LO_OLD, LO_NEW)]:
        n = src.count(old)
        if n != 1:
            sys.exit("失败：%s 的锚点出现 %d 次（应为 1）。" % (name, n))
        src = src.replace(old, new, 1)
        print("  ok  " + name)

    out = a.out or (a.tf + ".patched4")
    with open(out, "w", encoding="utf-8") as f:
        f.write(src)
    os.chmod(out, 0o755)
    print("\n已写出 %s（%d 行）" % (out, src.count("\n") + 1))


if __name__ == "__main__":
    main()
