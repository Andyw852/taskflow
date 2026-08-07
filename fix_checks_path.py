#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
fix_checks_path.py —— 修复 tf 驱动漏打的 patch_common_opt 补丁（checks 路径）

背景
----
_common 池重构进 opt/ 子目录后，find_asset / dim_common 加载都加了
"回落到 _common/*/ 子目录" 的兜底，唯独 _load_manifest 里解析 skill.yaml 的
    checks: ../_common/checks_relax.py
这条漏了。于是 checks 文件（已挪到 _common/opt/checks_relax.py）找不到，
_skill_checks 静默变 None，relax_injob 判据注册不上，band/elastic/ke/kl
四个技能的 step1（作业内分段弛豫）在 CHECKERS.get(name, ck_outcar) 处被
静默降级成通用 OUTCAR 判据 —— 不报错，但收敛判断失真。

本脚本
------
在 _load_manifest 的 checks 解析处补上同样的兜底逻辑（按 basename 在
_common/*/ 里找一层），skill.yaml 一行都不用改，四个技能一次修好。

用法
----
    放在 taskflow 仓库根目录下，然后：
        python3 fix_checks_path.py
    可选：显式指定要打补丁的 tf 文件（默认自动定位）：
        python3 fix_checks_path.py /path/to/tf [更多 tf ...]

特性：幂等（重复运行安全）、改前自动 .bak 备份、改后 py_compile 校验；
      失败自动回滚。不动任何 skill.yaml。
"""
import os
import sys
import shutil
import py_compile

HERE = os.path.dirname(os.path.abspath(__file__))

# 补丁锚点：这两行连续出现的地方就是 _load_manifest 里 checks 的解析处
ANCHOR = (
    '    cp = os.path.join(sdir, str(chk)) if chk else None\n'
    '    skel["_skill_checks"] = cp if (cp and os.path.isfile(cp)) else None\n'
)
MARKER = "patch_common_opt：公共判据文件"   # 幂等标记
PATCHED = (
    '    cp = os.path.join(sdir, str(chk)) if chk else None\n'
    '    # patch_common_opt：公共判据文件随 _common 重构挪进了公共步骤子目录（opt/ 等），\n'
    '    # 但老 skill.yaml 仍写重构前路径（../_common/checks_relax.py）。字面路径找不到、\n'
    '    # 且指向公共池时，按 basename 在 _common/*/ 里兜底一层——与 find_asset /\n'
    '    # dim_common 加载里 <pool>/*/ 的处理保持一致，skill.yaml 一行都不用改。\n'
    '    if cp and chk and not os.path.isfile(cp) and COMMON_POOL_DIR in str(chk):\n'
    '        _pool = os.path.normpath(os.path.join(sdir, os.path.dirname(str(chk))))\n'
    '        for _hit in sorted(glob.glob(os.path.join(_pool, "*",\n'
    '                                                   os.path.basename(str(chk))))):\n'
    '            if os.path.isfile(_hit):\n'
    '                cp = _hit\n'
    '                break\n'
    '    skel["_skill_checks"] = cp if (cp and os.path.isfile(cp)) else None\n'
)


def looks_like_tf(text):
    """是不是我们要打补丁的 tf 驱动（有 _load_manifest 且用 COMMON_POOL_DIR）。"""
    return "_load_manifest" in text and "COMMON_POOL_DIR" in text


def find_targets(argv):
    """自动定位要打补丁的 tf 文件；去重（按真实路径）。"""
    cands = list(argv)
    # 仓库内约定位置
    cands.append(os.path.join(HERE, "versions", "v1.0", "tf"))
    cands.append(os.path.join(HERE, "tf"))
    # PATH 上真正在用的 tf（跟随软链到真实文件）
    which = shutil.which("tf")
    if which:
        cands.append(os.path.realpath(which))
    # 仓库内其它 versions/*/tf
    vroot = os.path.join(HERE, "versions")
    if os.path.isdir(vroot):
        for d in sorted(os.listdir(vroot)):
            p = os.path.join(vroot, d, "tf")
            if os.path.isfile(p):
                cands.append(p)

    seen, out = set(), []
    for c in cands:
        if not c or not os.path.isfile(c):
            continue
        rp = os.path.realpath(c)
        if rp in seen:
            continue
        seen.add(rp)
        out.append(rp)
    return out


def patch_one(path):
    """返回 ('patched'|'already'|'skip'|'error', message)。"""
    try:
        with open(path, "r", encoding="utf-8") as fh:
            text = fh.read()
    except OSError as e:
        return "error", "读取失败：%s" % e

    if not looks_like_tf(text):
        return "skip", "不是目标 tf 驱动（没有 _load_manifest/COMMON_POOL_DIR），跳过"
    if MARKER in text:
        return "already", "已打过补丁，跳过"
    if ANCHOR not in text:
        return "skip", ("没找到 checks 解析锚点——可能 tf 版本不同或已被改过；"
                        "未改动，请人工核对 _load_manifest")
    if text.count(ANCHOR) != 1:
        return "skip", "锚点出现 %d 次（应为 1 次），保守起见不自动改" % text.count(ANCHOR)

    new_text = text.replace(ANCHOR, PATCHED, 1)

    bak = path + ".bak"
    try:
        if not os.path.exists(bak):
            shutil.copy2(path, bak)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(new_text)
    except OSError as e:
        return "error", "写入失败：%s" % e

    # 编译校验，失败则回滚
    try:
        py_compile.compile(path, doraise=True)
    except py_compile.PyCompileError as e:
        shutil.copy2(bak, path)
        return "error", "补丁后语法错误，已回滚：%s" % e

    return "patched", "已打补丁（备份：%s）" % os.path.basename(bak)


def main():
    targets = find_targets(sys.argv[1:])
    if not targets:
        print("✗ 没有找到 tf 驱动。请在 taskflow 仓库根目录运行，"
              "或显式传入：python3 fix_checks_path.py /path/to/tf")
        return 2

    print("将检查以下 tf 文件：")
    for t in targets:
        print("   -", t)
    print()

    rc = 0
    n_patched = 0
    for t in targets:
        status, msg = patch_one(t)
        icon = {"patched": "✓", "already": "•", "skip": "–", "error": "✗"}[status]
        print("%s %s\n    %s" % (icon, t, msg))
        if status == "patched":
            n_patched += 1
        if status == "error":
            rc = 1

    print()
    if n_patched:
        print("完成：本次打补丁 %d 个文件。" % n_patched)
        print("验证：")
        print("    tf -tt band status      # step1 现在应走 relax_injob，不再降级 outcar")
        print("    tf -tt elastic status")
    elif rc == 0:
        print("无需改动（都已是修复后的状态）。")
    return rc


if __name__ == "__main__":
    sys.exit(main())
