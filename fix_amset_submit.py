#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
fix_amset_submit.py —— 修 ke 的 amset 步骤（step4_wave / step8_amset）
                       submit.sh 生成失败的 bug。

现象：
    start ...[ke|S4_wave]: gen 失败。
    [ERROR] submit.sh 未推送到 .../ke/step4_wave（gen_need 里要有 submit_amset.tpl）

根因：
    tf 把 gen_need 里的文件按【原名】推到 gen 运行目录（submit_amset.tpl 就叫
    submit_amset.tpl），并不会把它改名成 submit.sh。维度步骤之所以有 submit.sh，
    是因为它们的 gen 脚本自己用 render() 把模板渲染成 submit.sh。而
    gen_step6_wave.py / gen_step10_amset.py 只会去找【现成的】out/submit.sh，
    自己不渲染——于是推来的 submit_amset.tpl 没人用，脚本报"submit.sh 未推送"。

修法：
    让这两个 gen 脚本自己读【与脚本同目录】的 submit_amset.tpl，渲染（填
    {{JOBNAME}} / {{AMSET_CMD}}）成 out/submit.sh，跟维度步骤一个套路。

用法（放在 taskflow 仓库根目录）：
    python3 fix_amset_submit.py
特性：幂等、逐文件 .bak 备份、锚点唯一才落盘、改后 py_compile、失败回滚。
"""
import os
import sys
import shutil
import py_compile

HERE = os.path.dirname(os.path.abspath(__file__))
MARKER = "tf 把 submit_amset.tpl 与本脚本一起推到"   # 幂等标记

# 两个文件的 old 段各不相同（jobname 位置不一样），分别精确匹配。
EDITS = [
    (
        "skill/ke/step4_wave/gen_step6_wave.py",
        '    submit = out / "submit.sh"\n'
        '    if not submit.is_file():\n'
        '        sys.exit("[ERROR] submit.sh 未推送到 %s（gen_need 里要有 submit_amset.tpl）" % out)\n'
        '    text = submit.read_text(encoding="utf-8")\n',
        '    # tf 把 submit_amset.tpl 与本脚本一起推到 gen 运行目录，但按原名推、不会改成\n'
        '    # submit.sh；本步自己把它渲染成 out/submit.sh（维度步靠各自 gen 的 render，这里同理）。\n'
        '    here = Path(__file__).resolve().parent\n'
        '    tpl = next((p for p in (here / "submit_amset.tpl", cwd / "submit_amset.tpl")\n'
        '                if p.is_file()), None)\n'
        '    if tpl is None:\n'
        '        sys.exit("[ERROR] 找不到 submit_amset.tpl（gen_need 里要有它，且应随 gen 脚本一起推送）")\n'
        '    submit = out / "submit.sh"\n'
        '    text = tpl.read_text(encoding="utf-8")\n',
    ),
    (
        "skill/ke/step8_amset/gen_step10_amset.py",
        '    submit = out / "submit.sh"\n'
        '    if not submit.is_file():\n'
        '        sys.exit("[ERROR] submit.sh 未推送到 %s（gen_need 里要有 submit_amset.tpl）" % out)\n'
        '    jobname = ("%s-ke-%s" % (cwd.name, STEP_LABEL)) if not _HAS_KC \\\n'
        '        else kc.new_jobname(cwd, STEP_LABEL)\n'
        '    text = submit.read_text(encoding="utf-8")\n',
        '    # tf 把 submit_amset.tpl 与本脚本一起推到 gen 运行目录，但按原名推、不会改成\n'
        '    # submit.sh；本步自己把它渲染成 out/submit.sh（维度步靠各自 gen 的 render，这里同理）。\n'
        '    here = Path(__file__).resolve().parent\n'
        '    tpl = next((p for p in (here / "submit_amset.tpl", cwd / "submit_amset.tpl")\n'
        '                if p.is_file()), None)\n'
        '    if tpl is None:\n'
        '        sys.exit("[ERROR] 找不到 submit_amset.tpl（gen_need 里要有它，且应随 gen 脚本一起推送）")\n'
        '    submit = out / "submit.sh"\n'
        '    jobname = ("%s-ke-%s" % (cwd.name, STEP_LABEL)) if not _HAS_KC \\\n'
        '        else kc.new_jobname(cwd, STEP_LABEL)\n'
        '    text = tpl.read_text(encoding="utf-8")\n',
    ),
]


def patch_file(rel, old, new):
    path = os.path.join(HERE, rel)
    if not os.path.isfile(path):
        return "skip", "文件不存在，跳过"
    with open(path, "r", encoding="utf-8") as fh:
        text = fh.read()
    if MARKER in text:
        return "already", "已改过，跳过"
    n = text.count(old)
    if n != 1:
        return "skip", "锚点匹配 %d 次（应为 1）——未改动，请人工核对" % n
    new_text = text.replace(old, new, 1)
    bak = path + ".bak"
    if not os.path.exists(bak):
        shutil.copy2(path, bak)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(new_text)
    try:
        py_compile.compile(path, doraise=True)
    except py_compile.PyCompileError as e:
        shutil.copy2(bak, path)
        return "error", "语法错误已回滚：%s" % e
    return "patched", "submit.sh 改为自渲染 submit_amset.tpl（备份：%s）" % os.path.basename(bak)


def main():
    rc, n = 0, 0
    for rel, old, new in EDITS:
        status, msg = patch_file(rel, old, new)
        icon = {"patched": "✓", "already": "•", "skip": "–", "error": "✗"}[status]
        print("%s %s\n    %s" % (icon, rel, msg))
        if status == "patched":
            n += 1
        if status == "error":
            rc = 1
    print()
    if n:
        print("完成：%d 个 amset gen 脚本已修。" % n)
        print("重跑：tf -tt ke start   （S4_wave 现在应能生成 submit.sh 并提交）")
    elif rc == 0:
        print("无需改动（都已是修复后的状态）。")
    return rc


if __name__ == "__main__":
    sys.exit(main())
