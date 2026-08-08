#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
fix_start_init_guard.py —— 让 `tf start` 不再启动"没为本技能初始化"的材料。

现象：
    只 init 了 Mo2S3、Zn3O2 的 kl，`tf -tt kl start` 却把没 init 的 Mg2C60 也交了
    （Mg2C60-kl-S1_opt）。因为 band/ke/kl 共用数据根，kl 按 POSCAR 扫到 Mg2C60，
    而 cmd_start / _start_ready 不检查该材料是否为本技能初始化（ps.dir 是否存在）。

    （auto_advance 已有同类门槛——见 fix_autoadvance_init_guard.py；本补丁补上
      显式 `tf start` 这条路。）

修法：
    _start_ready 顶部：ps.dir 为空（无本技能 project_setting）直接跳过并提示先 init；
    cmd_start 的「-j 全材料」循环：同样跳过未 init 的材料。
    已 init 的材料 ps.dir 有值，行为不变。

用法（放在 taskflow 仓库根目录）：python3 fix_start_init_guard.py
特性：幂等、.bak 备份、锚点唯一才落盘、py_compile 校验、失败回滚。自动定位
     versions/v1.0/tf 及 PATH 上的 tf。
"""
import os, sys, shutil, py_compile

HERE = os.path.dirname(os.path.abspath(__file__))
MARKER = "未为本技能初始化的材料（无 project_setting -> ps.dir 为空）不 start"

EDITS = [
    (   # _start_ready 顶部守卫
        '    fails = 0\n'
        '    ready = m.get("actives")\n'
        '    if ready is None:\n',
        '    # 未为本技能初始化的材料（无 project_setting -> ps.dir 为空）不 start：\n'
        '    # 与 auto_advance 一致，避免共用数据根时 start 误跑没 init 的材料。\n'
        '    if not (m.get("ps") or {}).get("dir"):\n'
        '        print("跳过 %s[%s]：未 init 本技能（先 tf -tt %s -p %s init）。"\n'
        '              % (m["name"], m["tt"], m["tt"], m["name"]))\n'
        '        return 0\n'
        '    fails = 0\n'
        '    ready = m.get("actives")\n'
        '    if ready is None:\n',
    ),
    (   # cmd_start 的 -j 全材料循环守卫
        '        for t, m, s in step_targets(data, jname):\n'
        '            if s["kind"] == "OK" or s.get("job"):\n'
        '                continue\n',
        '        for t, m, s in step_targets(data, jname):\n'
        '            if not (m.get("ps") or {}).get("dir"):\n'
        '                continue   # 未 init 本技能的材料不 start\n'
        '            if s["kind"] == "OK" or s.get("job"):\n'
        '                continue\n',
    ),
]


def targets(argv):
    cands = list(argv) + [os.path.join(HERE, "versions", "v1.0", "tf"),
                          os.path.join(HERE, "tf")]
    which = shutil.which("tf")
    if which:
        cands.append(os.path.realpath(which))
    vroot = os.path.join(HERE, "versions")
    if os.path.isdir(vroot):
        for d in sorted(os.listdir(vroot)):
            cands.append(os.path.join(vroot, d, "tf"))
    seen, out = set(), []
    for c in cands:
        if c and os.path.isfile(c):
            rp = os.path.realpath(c)
            if rp not in seen:
                seen.add(rp); out.append(rp)
    return out


def patch(path):
    s = open(path, encoding="utf-8").read()
    if "def _start_ready(" not in s or "def cmd_start(" not in s:
        return "skip", "不是目标 tf 驱动，跳过"
    if MARKER in s:
        return "already", "已改过，跳过"
    for old, _ in EDITS:
        if s.count(old) != 1:
            return "skip", "某锚点匹配 %d 次（应为 1），未改动，请人工核对" % s.count(old)
    new = s
    for old, rep in EDITS:
        new = new.replace(old, rep, 1)
    bak = path + ".bak"
    if not os.path.exists(bak):
        shutil.copy2(path, bak)
    open(path, "w", encoding="utf-8").write(new)
    try:
        py_compile.compile(path, doraise=True)
    except py_compile.PyCompileError as e:
        shutil.copy2(bak, path); return "error", "语法错误已回滚：%s" % e
    return "patched", "start 加了 init 门槛（备份：%s）" % os.path.basename(bak)


def main():
    tg = targets(sys.argv[1:])
    if not tg:
        print("✗ 找不到 tf 驱动，请在仓库根目录运行或传入路径。"); return 2
    rc, n = 0, 0
    for t in tg:
        st, msg = patch(t)
        icon = {"patched": "✓", "already": "•", "skip": "–", "error": "✗"}[st]
        print("%s %s\n    %s" % (icon, t, msg))
        if st == "patched":
            n += 1
        if st == "error":
            rc = 1
    print()
    if n:
        print("完成。tf start 不会再启动没 init 本技能的材料。")
    elif rc == 0:
        print("无需改动（都已修复）。")
    return rc


if __name__ == "__main__":
    sys.exit(main())
