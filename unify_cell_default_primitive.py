#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
unify_cell_default_primitive.py —— 把 elastic / ke / kl 的 gen_step1 默认晶胞
统一改成 primitive（band 本来就是 primitive，不动）。

改完四技能默认全是"原胞"。哪个项目需要惯用晶轴取向（弹性 C_ij / 电子热导输运张量），
就在该项目该技能的 step.conf 里写 CELL_POLICY=standard 要回来——这依赖先应用
add_cell_stepconf.py（让 step.conf 能控晶胞）。

只改每个文件里 R.run(...) 的 CELL_POLICY 那一行，STD_CELL / VACUUM_AXIS_POLICY 原样保留：
  · STD_CELL="primitive_standard" 在 primitive 下无效，但项目一旦设 standard 就自动生效；
  · VACUUM_AXIS_POLICY="rotate" 管的是 2D 真空轴，与取胞无关，保持原行为。

用法（放在 taskflow 仓库根目录）：
    python3 unify_cell_default_primitive.py
特性：幂等、逐文件 .bak 备份、锚点唯一才落盘、改后 py_compile、失败回滚。

⚠ 前置：先应用 add_cell_stepconf.py，否则 elastic/ke/kl 将失去标准取向且无法在
   step.conf 里恢复（写 CELL_POLICY 会被判未知键报错）。本脚本会检查该前置是否就位。
"""
import os
import sys
import shutil
import py_compile

HERE = os.path.dirname(os.path.abspath(__file__))
RELAX = os.path.join(HERE, "skill", "_common", "opt", "relax_common.py")

MARKER = "默认原胞（四技能统一）"     # 幂等标记

NEW_LINE = ('    CELL_POLICY="primitive",        # 默认原胞（四技能统一）；'
            '需惯用晶轴取向(C_ij/输运张量)时，在该项目 step.conf 设 CELL_POLICY=standard\n')

# (相对路径, 旧行)。旧行必须在该文件恰好出现 1 次。
FILES = [
    ("skill/elastic/gen_step1_std_opt.py",
     '    CELL_POLICY="standard",         # 弹性张量定义在惯用晶轴对齐的笛卡尔系里\n'),
    ("skill/ke/step1_opt/gen_step1_std_opt.py",
     '    CELL_POLICY="standard",\n'),
    ("skill/kl/gen_step1_std_opt.py",
     '    CELL_POLICY="standard",\n'),
]


def check_prereq():
    """add_cell_stepconf.py 是否已应用（relax_common 里有 apply_cell_params）。"""
    try:
        with open(RELAX, "r", encoding="utf-8") as fh:
            return "def apply_cell_params(" in fh.read()
    except OSError:
        return False


def patch_file(rel, old):
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
    new_text = text.replace(old, NEW_LINE, 1)
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
    return "patched", "CELL_POLICY -> primitive（备份：%s）" % os.path.basename(bak)


def main():
    print("前置检查：add_cell_stepconf.py ", end="")
    if check_prereq():
        print("已应用 ✓")
    else:
        print("尚未应用 ✗")
        print("  ⚠ 请先运行 add_cell_stepconf.py 再执行本脚本，否则 elastic/ke/kl")
        print("    将失去标准取向且无法用 step.conf 恢复。已中止，未改动任何文件。")
        return 2

    print()
    rc, n = 0, 0
    for rel, old in FILES:
        status, msg = patch_file(rel, old)
        icon = {"patched": "✓", "already": "•", "skip": "–", "error": "✗"}[status]
        print("%s %s\n    %s" % (icon, rel, msg))
        if status == "patched":
            n += 1
        if status == "error":
            rc = 1

    print()
    if n:
        print("完成：%d 个技能默认已改为 primitive（band 本就是 primitive）。" % n)
        print("四技能默认现在统一为原胞。需要标准取向的项目：")
        print("    tf -tt elastic -p <材料> -j <步骤> conf --set params.CELL_POLICY=standard")
    elif rc == 0:
        print("无需改动（都已是 primitive）。")
    return rc


if __name__ == "__main__":
    sys.exit(main())
