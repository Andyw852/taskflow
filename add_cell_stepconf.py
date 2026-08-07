#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
add_cell_stepconf.py —— 让"取胞策略"可由 step.conf 覆盖（所有技能通用，含护栏）

改的是公共池 skill/_common/opt/relax_common.py（band/elastic/ke/kl 都走它），
所以一处补丁、四技能同时生效，各技能 skill.yaml / gen_step1_*.py 一行都不用改。

做了三件事 + 护栏：
  1) CONF_SPEC 里登记 CELL_POLICY / STD_CELL / VACUUM_AXIS_POLICY
     （否则在 step.conf 里写这些键会被 stepconf 判为"未知键"直接报错）；
  2) 新增 apply_cell_params()：step.conf 显式值 > 技能 R.run 默认，含合法值校验；
  3) main() 里把"弛豫阶段解析 + 读 step.conf + 应用晶胞覆盖"提到 ensure_cell() 之前
     （否则覆盖发生在改胞之后就晚了），并去掉后面重复的 resolve_stage / global FUNC；
  护栏：偏离技能默认时高声告警（晶胞与下游能带/弹性/AMSET 强耦合，但不阻断），
        并把最终生效的晶胞策略写进 workflow_method.txt 留痕。

优先级、合法值：
  CELL_POLICY = primitive | standard | none
  STD_CELL    = primitive_standard | conventional   （仅 CELL_POLICY=standard 生效）
  VACUUM_AXIS_POLICY = error | rotate               （仅 2D 生效）
  step.conf 不写这些键时，完全沿用各技能原有默认，行为不变。

用法（放在 taskflow 仓库根目录）：
    python3 add_cell_stepconf.py
特性：幂等、改前 .bak 备份、全部锚点命中才落盘、改后 py_compile 校验、失败回滚。
"""
import os
import sys
import shutil
import py_compile

HERE = os.path.dirname(os.path.abspath(__file__))
TARGET = os.path.join(HERE, "skill", "_common", "opt", "relax_common.py")
MARKER = "def apply_cell_params("     # 幂等标记

# 每个补丁是 (说明, 旧串, 新串)。旧串必须在文件中恰好出现 1 次。
EDITS = [
    (
        "CONF_SPEC 登记晶胞键",
        'CONF_SPEC = {\n'
        '    "FUNC": (FUNC_DEFAULT, "str"),\n'
        '    "STALL_MINUTES": (60, "int"),        # run_relax.sh 看门狗阈值\n',
        'CONF_SPEC = {\n'
        '    "FUNC": (FUNC_DEFAULT, "str"),\n'
        '    # 晶胞策略：step.conf 可覆盖技能默认（默认 None = 不设置，用技能 R.run 默认）。\n'
        '    #   CELL_POLICY: primitive | standard | none\n'
        '    #   STD_CELL:    primitive_standard | conventional （仅 CELL_POLICY=standard 生效）\n'
        '    #   VACUUM_AXIS_POLICY: error | rotate （仅 2D 生效）\n'
        '    "CELL_POLICY": (None, "str"),\n'
        '    "STD_CELL": (None, "str"),\n'
        '    "VACUUM_AXIS_POLICY": (None, "str"),\n'
        '    "STALL_MINUTES": (60, "int"),        # run_relax.sh 看门狗阈值\n',
    ),
    (
        "新增 apply_cell_params()",
        'def apply_step_params():\n'
        '    """把 step.conf 里本模块自己要用的键落到全局量（MOL_* 由 mol_common 取用）。"""\n'
        '    v = STEP_PARAMS.get("STALL_MINUTES")\n'
        '    if v is not None:\n'
        '        globals()["STALL_MIN"] = int(v)\n',
        'def apply_step_params():\n'
        '    """把 step.conf 里本模块自己要用的键落到全局量（MOL_* 由 mol_common 取用）。"""\n'
        '    v = STEP_PARAMS.get("STALL_MINUTES")\n'
        '    if v is not None:\n'
        '        globals()["STALL_MIN"] = int(v)\n'
        '\n'
        '\n'
        '# step.conf 可覆盖的晶胞键 -> 合法值集合\n'
        '_CELL_KEYS = {\n'
        '    "CELL_POLICY": {"primitive", "standard", "none"},\n'
        '    "STD_CELL": {"primitive_standard", "conventional"},\n'
        '    "VACUUM_AXIS_POLICY": {"error", "rotate"},\n'
        '}\n'
        '\n'
        '\n'
        'def apply_cell_params():\n'
        '    """step.conf 覆盖晶胞策略（CELL_POLICY / STD_CELL / VACUUM_AXIS_POLICY），\n'
        '    含合法值校验与护栏告警；返回一行 provenance（无论是否覆盖都返回，供留痕）。\n'
        '\n'
        '    优先级：step.conf 显式值 > 技能 R.run 默认。必须在 ensure_cell() 之前调用。\n'
        '    晶胞与下游步骤强耦合，偏离技能默认时高声告警，但不阻断（尊重用户判断）。"""\n'
        '    g = globals()\n'
        '    skill_default = {k: g[k] for k in _CELL_KEYS}\n'
        '    changed = []\n'
        '    for key, allowed in _CELL_KEYS.items():\n'
        '        v = STEP_PARAMS.get(key)\n'
        '        if not v:                     # None（未设置）或空串 -> 用技能默认\n'
        '            continue\n'
        '        v = str(v).strip().lower()\n'
        '        if v not in allowed:\n'
        '            sys.exit("[ERROR] step.conf 的 %s=%r 非法，只允许：%s"\n'
        '                     % (key, v, ", ".join(sorted(allowed))))\n'
        '        if v != str(g[key]).strip().lower():\n'
        '            g[key] = v\n'
        '            changed.append((key, skill_default[key], v))\n'
        '    if changed:\n'
        '        print("[!!] 晶胞策略被 step.conf 覆盖（偏离本技能默认）：")\n'
        '        for k, old, new in changed:\n'
        '            print("     %s: 技能默认 %r -> step.conf %r" % (k, old, new))\n'
        '        print("     警告：晶胞取向/原胞化与下游步骤强耦合——")\n'
        '        print("       · 能带：高对称路径定义在原胞倒空间，改成 standard/none 可能错标路径；")\n'
        '        print("       · 弹性：C_ij 定义在标准取向，改成 primitive/none 会得到旋转过的张量；")\n'
        '        print("       · AMSET/电子热导：需少原子原胞做密网格插值，改成 none(超胞) 会折叠 BZ。")\n'
        '        print("     仅在你明确知道后果时使用；最终生效值已写入 %s。" % METHOD_FILE)\n'
        '    src = "step.conf 覆盖" if changed else "技能默认"\n'
        '    return ("CELL_POLICY=%s STD_CELL=%s VACUUM_AXIS_POLICY=%s (%s)"\n'
        '            % (g["CELL_POLICY"], g["STD_CELL"], g["VACUUM_AXIS_POLICY"], src))\n',
    ),
    (
        "main(): 改胞前解析 stage + 读 step.conf + 应用晶胞覆盖",
        '    prim_note = ensure_cell(cwd / "POSCAR")\n'
        '\n'
        '    # ---- 维度判定 + 按维度选模板（2D/3D 各一套，缺失回退到无后缀旧名）----\n',
        '    # ---- 弛豫阶段先解析（与 FUNC 共用同一 step 名读 step.conf）----\n'
        '    global FUNC\n'
        '    stage, outdir_name, src_poscar = resolve_stage(cwd)\n'
        '    # ---- 晶胞策略：step.conf 可覆盖技能默认（护栏 + provenance），必须在改胞前 ----\n'
        '    load_step_params(outdir_name)\n'
        '    cell_note = apply_cell_params()\n'
        '    prim_note = ensure_cell(cwd / "POSCAR")\n'
        '\n'
        '    # ---- 维度判定 + 按维度选模板（2D/3D 各一套，缺失回退到无后缀旧名）----\n',
    ),
    (
        "main(): 去掉重复的 stage / global FUNC",
        '    # ---- 泛函：step.conf 说了算（见文件顶部 FUNC_DEFAULT 的说明）----\n'
        '    global FUNC\n'
        '    stage, outdir_name, src_poscar = resolve_stage(cwd)\n'
        '    FUNC, func_src = resolve_func(incar_tpl, outdir_name)\n',
        '    # ---- 泛函：step.conf 说了算（stage / step.conf 已在改胞前解析）----\n'
        '    FUNC, func_src = resolve_func(incar_tpl, outdir_name)\n',
    ),
    (
        "main(): 把生效晶胞写进 workflow_method.txt",
        '    write_method_file(outdir / METHOD_FILE, label, formula, prim_note,\n'
        '                      mag_line=f"MAG={\'magnetic\' if magnetic else \'nonmag\'}",\n'
        '                      dim_line=f"DIM={dim.upper()}")\n',
        '    cell_prov = cell_note if not prim_note else (cell_note + "\\n" + prim_note)\n'
        '    write_method_file(outdir / METHOD_FILE, label, formula, cell_prov,\n'
        '                      mag_line=f"MAG={\'magnetic\' if magnetic else \'nonmag\'}",\n'
        '                      dim_line=f"DIM={dim.upper()}")\n',
    ),
]


def main():
    if not os.path.isfile(TARGET):
        print("✗ 找不到目标文件：%s" % TARGET)
        print("  请在 taskflow 仓库根目录运行本脚本。")
        return 2

    with open(TARGET, "r", encoding="utf-8") as fh:
        text = fh.read()

    if MARKER in text:
        print("• %s\n    已打过补丁（apply_cell_params 已存在），跳过。" % TARGET)
        return 0

    # 先在内存里全部替换；任一锚点缺失/不唯一就中止，绝不半途落盘
    new_text = text
    for desc, old, new in EDITS:
        n = new_text.count(old)
        if n != 1:
            print("✗ 锚点《%s》匹配 %d 次（应为 1）——未改动。" % (desc, n))
            print("  可能 relax_common.py 版本与本补丁不符，请人工核对。")
            return 1
        new_text = new_text.replace(old, new, 1)

    bak = TARGET + ".bak"
    if not os.path.exists(bak):
        shutil.copy2(TARGET, bak)
    with open(TARGET, "w", encoding="utf-8") as fh:
        fh.write(new_text)

    try:
        py_compile.compile(TARGET, doraise=True)
    except py_compile.PyCompileError as e:
        shutil.copy2(bak, TARGET)
        print("✗ 补丁后语法错误，已回滚：%s" % e)
        return 1

    print("✓ %s" % TARGET)
    print("    已应用 %d 处改动（备份：%s）。" % (len(EDITS), os.path.basename(bak)))
    print()
    print("现在可以在 step.conf 的 [params] 里控制晶胞了，例如：")
    print("    tf -tt band -p <材料> -j <步骤> conf --set params.CELL_POLICY=standard")
    print("    tf -tt ke   -p <材料> -j <步骤> conf --set params.CELL_POLICY=none")
    print("不写这些键时，各技能沿用原有默认（band=primitive，elastic/ke=standard），行为不变。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
