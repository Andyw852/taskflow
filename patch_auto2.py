#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
patch_auto2.py —— taskflow (tf) 表格第三行 + 即时步立刻拉回
在 taskflow 包根目录下直接运行：  python3 patch_auto2.py

做两件事：
  1. 状态表（tf list / tf status / tf watch）每个材料多出第三行：分组列
     （S2_bandgap 这种由多个子步骤合并成的列）显示当前所在子步骤在超算上的
     真实目录名，如 step2.2_pbe / step2.3_hse。取的是该步骤的远端目录
     basename，不写死任何技能的步骤名，别的技能自动适用。
     非分组列（一列一步骤）第三行显示 "-"，不撑宽表格。
  2. run:gen 的本地即时步（画图/读取）跑完立刻把产物拉回本地 result/，
     不再等下一轮 auto_fetch。手动 tf start 触发的也一样会拉。
     （若已打过 patch_auto.py，顺带把级联里那段重复的补拉删掉。）

可与 patch_auto.py 叠加，先后顺序不限。
回滚：把 versions/vX/tf.bak2.<时间戳> 覆盖回 versions/vX/tf。
"""
import os
import shutil
import sys
import time

MARK = "patch_auto2"

# --------------------------------------------------------------------------
# 1) 表格第三行：分组列显示子步骤的超算目录名
# --------------------------------------------------------------------------
OLD_RENDER_HEAD = '''def render_table(data):
'''
NEW_RENDER_HEAD = '''def _step_dirname(s):
    """patch_auto2：步骤在超算上的目录名（basename）。dir 缺失时退回 name。
    通用取法，不依赖任何技能的命名约定。"""
    d = s.get("dir") or s.get("name") or ""
    return os.path.basename(str(d).rstrip("/")) or "-"


def _group_dir(ms):
    """patch_auto2：分组列第三行——当前落在哪个子步骤（显示其超算目录名）。
    有作业的优先（和第二行的作业号对得上）；否则取第一个未完成的；
    全完成则显示最后一个子步骤。"""
    for s in ms:
        if s.get("job"):
            return _step_dirname(s)
    for s in ms:
        if s["kind"] != "OK":
            return _step_dirname(s)
    return _step_dirname(ms[-1]) if ms else "-"


def render_table(data):
'''

OLD_ROWS = '''    pairs = []  # (t, row1, row2)；row1 = 各步骤状态词；row2 = 节点/任务号/时长
    for t, m in all_mats:
        cols = {}
        for s in m["steps"]:
            cols.setdefault(col_of(m, s), []).append(s)
        word, act = {}, {}
        for c, ms in cols.items():
            if len(ms) == 1:
                word[c] = _cell_word(ms[0])
                act[c] = _cell_info(ms[0])
            else:
                word[c] = _group_word(ms)
                act[c] = _group_info(ms)
        hpc = m.get("hpc_name") or data.get("host") or "-"
        dim = m.get("dim") or "-"
        row1 = [m["name"], t["key"], hpc, dim] + [word.get(x, "") for x in labels]
        row2 = ["", "", "", ""] + [act.get(x, "") for x in labels]
        pairs.append((t, row1, row2))
    rows = [r for _, r1, r2 in pairs for r in (r1, r2)]
'''
NEW_ROWS = '''    # patch_auto2：row3 = 分组列当前子步骤的超算目录名
    pairs = []  # (t, row1, row2, row3)
    for t, m in all_mats:
        cols = {}
        for s in m["steps"]:
            cols.setdefault(col_of(m, s), []).append(s)
        word, act, sub = {}, {}, {}
        for c, ms in cols.items():
            if len(ms) == 1:
                word[c] = _cell_word(ms[0])
                act[c] = _cell_info(ms[0])
                sub[c] = "-"
            else:
                word[c] = _group_word(ms)
                act[c] = _group_info(ms)
                sub[c] = _group_dir(ms)
        hpc = m.get("hpc_name") or data.get("host") or "-"
        dim = m.get("dim") or "-"
        row1 = [m["name"], t["key"], hpc, dim] + [word.get(x, "") for x in labels]
        row2 = ["", "", "", ""] + [act.get(x, "") for x in labels]
        row3 = ["", "", "", ""] + [sub.get(x, "") for x in labels]
        pairs.append((t, row1, row2, row3))
    rows = [r for _, r1, r2, r3 in pairs for r in (r1, r2, r3)]
'''

OLD_PRINT = '''    for t, r1, r2 in pairs:
        if prev_tt is not None and t["key"] != prev_tt:
            print(line())
        print(fmt(r1))
        print(fmt(r2))
        prev_tt = t["key"]
'''
NEW_PRINT = '''    for t, r1, r2, r3 in pairs:
        if prev_tt is not None and t["key"] != prev_tt:
            print(line())
        print(fmt(r1))
        print(fmt(r2))
        if any(c not in ("", "-") for c in r3):   # patch_auto2：没内容就不占行
            print(fmt(r3))
        prev_tt = t["key"]
'''

# --------------------------------------------------------------------------
# 2) run:gen 即时步跑完立刻拉回
# --------------------------------------------------------------------------
OLD_GENSTEP = '''        _fetch_stamp_clear(m, s["name"])   # v1.11：产物已更新，让 auto-fetch 重拉
        _scancel_clear(m, s["name"])       # v1.4：重跑成功，清 stop 标记
        return True
'''
NEW_GENSTEP = '''        _fetch_stamp_clear(m, s["name"])   # v1.11：产物已更新，让 auto-fetch 重拉
        _scancel_clear(m, s["name"])       # v1.4：重跑成功，清 stop 标记
        if m.get("result_dir"):   # patch_auto2：即时步产物立刻拉回，
            s["done"], s["exists"] = True, True   # 不等下一轮 auto_fetch
            try:
                if fetch_material(cfg, m, only_steps={s["name"]}, quiet=True):
                    print("%s: 已拉回 → %s"
                          % (tag, os.path.join(m["result_dir"], s["name"])))
            except Exception as _e:   # noqa: BLE001
                print("警告：拉回 %s 失败：%s" % (s["name"], _e), file=sys.stderr)
        return True
'''

# 可选：patch_auto.py 级联里那段补拉已被上面取代，删掉避免重复传输
OPT_CASCADE_FETCH = '''            if _done_now and m.get("result_dir"):
                # 本轮 auto_fetch 已经跑过了，级联出来的新产物这里补拉一次
                for _nm in _done_now:
                    _fetch_stamp_clear(m, _nm)
                try:
                    fetch_material(cfg, m, only_steps=set(_done_now), quiet=True)
                    print("auto-fetch %s: %s → %s"
                          % (m["name"], ",".join(_done_now), m["result_dir"]))
                except Exception as _e:   # noqa: BLE001
                    print("警告：auto-fetch（级联）%s 失败：%s" % (m["name"], _e),
                          file=sys.stderr)
'''
OPT_CASCADE_FETCH_NEW = '''            # patch_auto2：产物已在 do_run_gen_step 里当场拉回，这里不再重复
'''

PATCHES = [
    ("表格 _group_dir 辅助函数", OLD_RENDER_HEAD, NEW_RENDER_HEAD),
    ("表格第三行组装", OLD_ROWS, NEW_ROWS),
    ("表格第三行打印", OLD_PRINT, NEW_PRINT),
    ("即时步立刻拉回", OLD_GENSTEP, NEW_GENSTEP),
]
OPTIONAL = [
    ("去掉级联里的重复补拉", OPT_CASCADE_FETCH, OPT_CASCADE_FETCH_NEW),
]


def find_tf(argv):
    if len(argv) > 1:
        return os.path.abspath(argv[1])
    here = os.getcwd()
    cands = []
    for root, dirs, files in os.walk(here):
        dirs[:] = [d for d in dirs if d not in (".git", "skill", "setting")]
        if "tf" in files and os.sep + "versions" + os.sep in root + os.sep:
            cands.append(os.path.join(root, "tf"))
    if len(cands) > 1:
        cands.sort()
        print("发现多个 tf，用最新的：%s" % cands[-1])
    if cands:
        return cands[-1]
    p = os.path.join(here, "versions", "v1.0", "tf")
    return p if os.path.isfile(p) else None


def main():
    path = find_tf(sys.argv)
    if not path or not os.path.isfile(path):
        sys.exit("错误：没找到 versions/*/tf。请在 taskflow 包根下运行，"
                 "或显式指定：python3 patch_auto2.py /path/to/versions/v1.0/tf")
    src = open(path, encoding="utf-8").read()

    if MARK in src:
        sys.exit("这个 tf 已经打过 patch_auto2 补丁了，无需重复运行。\n"
                 "（要重打：先用 tf.bak2.* 还原）")

    missing = [name for name, old, _ in PATCHES if src.count(old) != 1]
    if missing:
        sys.exit("错误：以下锚点没有唯一匹配，可能你的 tf 版本和补丁不符：\n  - "
                 + "\n  - ".join(missing)
                 + "\n补丁基于 GitHub Andyw852/taskflow @ d0bd8bb（TF_VERSION 1.0）。")

    out = src
    for _name, old, new in PATCHES:
        out = out.replace(old, new, 1)
    for name, old, new in OPTIONAL:
        if out.count(old) == 1:
            out = out.replace(old, new, 1)
            print("（顺带）%s" % name)

    try:
        compile(out, path, "exec")
    except SyntaxError as e:
        sys.exit("错误：打完补丁后语法检查失败（%s 第 %s 行），已放弃写入。"
                 % (e.msg, e.lineno))

    bak = "%s.bak2.%s" % (path, time.strftime("%Y%m%d-%H%M%S"))
    shutil.copy2(path, bak)
    mode = os.stat(path).st_mode
    with open(path, "w", encoding="utf-8") as f:
        f.write(out)
    os.chmod(path, mode)

    print("已打补丁：%s" % path)
    print("备份    ：%s" % bak)
    print("")
    print("自检：")
    print("  tf list        # S2_bandgap 列下方多一行 step2.3_hse 之类的目录名")
    print("  tf status      # 画完的 plot 步骤应打印「已拉回 → .../result/...」")


if __name__ == "__main__":
    main()
