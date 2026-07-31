#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""apply_patch5.py —— 点号步骤名 + 序号精确匹配（v1.8）。

在你改好的 v1.7 tf（技能级 project_setting）基础上追加：

  1. 步骤名可以带点号：step2.1_static、step2.2_wavecar 都能被 tf 正确处理。
  2. -j 序号匹配更精确：
       -j 2      → 匹配 seq==2 或名字 step2 开头（不含 step2.1 这种子步）
       -j 2.1    → 精确匹配 seq==2.1（或名字 step2.1_*）
     不再有「-j 2 顺带把 step2.1 也选上」的串扰。
  3. fanout / 各处 glob 不受影响（它们按 name 全等，本就安全）。

每个技能仍然独立：本补丁只改「序号/名字怎么解析」，不碰 project_setting 隔离。

    python3 apply_patch5.py <你的 tf> [-o 输出]

不依赖前面哪一版补丁号，只要求 tf 里有 _step_seq_match 和 step_seq（你的 v1.7 有）。
"""
import argparse
import os
import re
import sys

APPLIED = "def _seq_key("

# ---------------------------------------------------------------------------
# P1  统一的序号解析工具（放在 step_seq 之前）
# ---------------------------------------------------------------------------
P1_ANCHOR = "def step_seq(s):"
P1_NEW = '''def _seq_key(v):
    """把 seq / -j token 归一成可比较的数：'2'->2.0，'2.1'->2.1，非数->None。"""
    if v is None:
        return None
    try:
        return float(str(v).strip())
    except (TypeError, ValueError):
        return None


def _name_seq(name):
    """从步骤名抽序号：step2 -> 2.0，step2.1_static -> 2.1，step1a_opt -> 1.0。
    抓 'step' 后面的数字（可带一位小数），字母后缀（a/b/c）忽略。"""
    m = re.match(r"step(\\d+(?:\\.\\d+)?)", str(name or ""))
    return float(m.group(1)) if m else None


def step_seq(s):
'''

# ---------------------------------------------------------------------------
# P2  run_steps 的 match：用 _seq_key 精确比较（原本已用 float，但要处理点号名）
#     原逻辑对 seq 缺失时不认名字里的点号，这里补上。
# ---------------------------------------------------------------------------
P2_OLD = '''        sq = step_seq(s)           # v1.2：序号来自清单的 seq，不再认 band_plot
        if sq is None:
            return False
        try:
            return float(ts) == float(sq)
        except ValueError:
            return False'''
P2_NEW = '''        # v1.8：seq 优先，其次名字里的点号序号；点号精确比较，不做前缀近似
        want = _seq_key(ts)
        if want is None:
            return False
        sq = _seq_key(step_seq(s))
        if sq is None:
            sq = _name_seq(s.get("name"))
        return sq is not None and abs(sq - want) < 1e-9'''

# ---------------------------------------------------------------------------
# P3  _step_seq_match：整数按前缀（保持老行为），但排除带点号的子步
# ---------------------------------------------------------------------------
P3_OLD = '''def _step_seq_match(s, n):
    """v1.7：数字 = 逻辑步骤号（stepN 前缀，band_plot 除外）。
    三段式弛豫时 1 指首段 step1a（b/c 段用 label 指，如 S1b_cell）。"""
    nm = str(s.get("name", ""))
    return nm.startswith("step%d" % n) and "band_plot" not in nm'''
P3_NEW = '''def _step_seq_match(s, n):
    """v1.8：整数 -j N 匹配逻辑步骤号 N。
    - seq 恰为 N（整数）→ 命中；
    - 名字 stepN 开头，但**排除 stepN.M 子步**（step2 命中，step2.1 不命中）；
    - band_plot 画图步除外（历史行为）。
    带点号的子步用 -j N.M 或 label 指定，不会被整数 N 顺带选上。"""
    nm = str(s.get("name", ""))
    if "band_plot" in nm:
        return False
    sk = _seq_key(s.get("seq"))
    if sk is not None and abs(sk - n) < 1e-9:
        return True
    # 名字前缀：stepN 后面不能紧跟小数点（否则是 stepN.M 子步）
    return bool(re.match(r"step%d(?!\\.\\d)" % n, nm))'''

# ---------------------------------------------------------------------------
# P4  find_step / find_step_soft：数字 token 支持点号（2.1 走精确 seq 匹配）
# ---------------------------------------------------------------------------
P4A_OLD = '''def find_step(m, jname):
    steps = m["steps"]
    if jname.isdigit():
        for s in steps:
            if _step_seq_match(s, int(jname)):
                return s'''
P4A_NEW = '''def _find_by_dotted(steps, jname):
    """v1.8：-j 2.1 这类点号 token，按 seq / 名字序号精确匹配。命中返回步骤，否则 None。"""
    want = _seq_key(jname)
    if want is None:
        return None
    for s in steps:
        sq = _seq_key(step_seq(s))
        if sq is None:
            sq = _name_seq(s.get("name"))
        if sq is not None and abs(sq - want) < 1e-9:
            return s
    return None


def find_step(m, jname):
    steps = m["steps"]
    if jname.isdigit():
        for s in steps:
            if _step_seq_match(s, int(jname)):
                return s'''

P4B_OLD = '''    for s in steps:
        if s["name"] == jname or s["label"] == jname:
            return s
    sys.exit("错误：%s 没有步骤 '%s'（现有：%s）。'''
P4B_NEW = '''    for s in steps:
        if s["name"] == jname or s["label"] == jname:
            return s
    _d = _find_by_dotted(steps, jname)      # v1.8：-j 2.1 点号序号
    if _d is not None:
        return _d
    sys.exit("错误：%s 没有步骤 '%s'（现有：%s）。'''

P4C_OLD = '''def find_step_soft(m, jname):
    """find_step 的宽容版：材料没有该步骤时返回 None 而不是退出。"""
    steps = m["steps"]
    if jname.isdigit():
        for s in steps:
            if _step_seq_match(s, int(jname)):
                return s
        return None
    for s in steps:
        if s["name"] == jname or s["label"] == jname:
            return s
    return None'''
P4C_NEW = '''def find_step_soft(m, jname):
    """find_step 的宽容版：材料没有该步骤时返回 None 而不是退出。"""
    steps = m["steps"]
    if jname.isdigit():
        for s in steps:
            if _step_seq_match(s, int(jname)):
                return s
        return None
    for s in steps:
        if s["name"] == jname or s["label"] == jname:
            return s
    return _find_by_dotted(steps, jname)    # v1.8：-j 2.1 点号序号'''

PATCHES = [
    ("P1  序号解析工具 _seq_key/_name_seq", P1_ANCHOR, P1_NEW + "    " + '"""步骤序号：优先清单里的 seq，缺省从 stepN 名字推。"""', None),
    ("P2  run_steps 点号匹配", P2_OLD, P2_NEW, None),
    ("P3  _step_seq_match 排除子步", P3_OLD, P3_NEW, None),
    ("P4a find_step 加点号解析", P4A_OLD, P4A_NEW, None),
    ("P4b find_step 兜底点号", P4B_OLD, P4B_NEW, None),
    ("P4c find_step_soft 点号", P4C_OLD, P4C_NEW, None),
]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("tf")
    ap.add_argument("-o", "--out")
    a = ap.parse_args()
    src = open(a.tf, encoding="utf-8").read()
    if APPLIED in src:
        sys.exit("该 tf 已经打过本补丁（找到 _seq_key），无需重复执行。")
    for mark in ("_step_seq_match", "def step_seq(s):", "def find_step(m, jname):"):
        if mark not in src:
            sys.exit("失败：这个 tf 缺少 %s，不是预期的 v1.7 版本。" % mark)

    # P1 特殊：把 step_seq 的 docstring 首行一起吃掉再重写，避免重复
    p1_old = P1_ANCHOR + '\n    """步骤序号：优先清单里的 seq，缺省从 stepN 名字推。"""'
    if src.count(p1_old) != 1:
        sys.exit("失败：P1 锚点（step_seq + docstring）不唯一或缺失。")
    src = src.replace(p1_old, P1_NEW + '    """步骤序号：优先清单里的 seq，缺省从 stepN 名字推。"""', 1)
    print("  ok  P1  序号解析工具 _seq_key/_name_seq")

    for name, old, new, _ in PATCHES[1:]:
        n = src.count(old)
        if n != 1:
            sys.exit("失败：%s 的锚点出现 %d 次（应为 1）。\n%s"
                     % (name, n, old.splitlines()[0][:70]))
        src = src.replace(old, new, 1)
        print("  ok  " + name)

    out = a.out or (a.tf + ".patched5")
    with open(out, "w", encoding="utf-8") as f:
        f.write(src)
    os.chmod(out, 0o755)
    print("\n已写出 %s（%d 行）" % (out, src.count("\n") + 1))


if __name__ == "__main__":
    main()
