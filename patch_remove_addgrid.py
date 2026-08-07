#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
patch_remove_addgrid.py —— 技能池里所有 ADDGRID = .TRUE. 全部去掉

依据：
  * VASP 的默认值本来就是 ADDGRID = .FALSE.。
  * VASP wiki 对它的现行表述是"有时能改善力的精度，不过用户反馈相当矛盾，
    并不确定是否真的有用"，并且明确写过"请不要把这个标签当作你所有计算的
    默认设置"。
  * Materials Project 的输入校验器直接把 ADDGRID=False 列为硬性要求，
    理由是它会影响输出的力，开了就与 MP 数据不兼容。
  * 机制上，那个支持网格点数是细网格的 8 倍，傅里叶插值会带来截断振荡，
    用于增广密度的傅里叶平滑还可能让实空间出现负密度。

顺带填一个坑：ADDGRID 会改变 CHGCAR 的网格。ke 的 step1（2D 模板写死
.FALSE.）与 step6_elastic（gen 注入 .TRUE.）本来不一致，想在两步之间
复用 CHGCAR 时会撞上网格不匹配。统一去掉之后就没这个问题了。

本补丁处理四处 .TRUE.：
    skill/elastic/gen_step2_elastic.py          incar_set 里的注入
    skill/ke/step6_elastic/gen_step2_elastic.py 同上（独立副本）
    skill/kl/templates/step4_disp/incar_force_2d.tpl
    skill/kl/templates/step4_disp/incar_force_3d.tpl   （含表头注释里的提及）

已经写成 .FALSE. 的模板【不动】——它们显式记录了这个决定，值保留下来
比删掉更有信息量。想把它们也一并删掉加 --strip-false。

⚠️ kl 的 step4_disp 要单独想一下：那是位移超胞取力的步骤，历史上正是
"开 ADDGRID 降低力噪声"这个说法的主要适用场景。去掉之后力常数会有微小
变化，已经算过的 kl 结果与新结果不再严格可比。那一步已经有 EDIFF=1E-8
+ LREAL=.FALSE. + PREC=Accurate + ISYM=0，力的质量有保障，所以我认为
去掉是站得住的；但这是个判断，不是纯粹的 bug 修复。只想改弹性那两处就加
--skip-kl。

用法（taskflow 包根目录）：
    python3 patch_remove_addgrid.py --dry-run
    python3 patch_remove_addgrid.py
    python3 patch_remove_addgrid.py --skip-kl      # 只动弹性的两份 gen
    python3 patch_remove_addgrid.py --strip-false  # 连 .FALSE. 的行也删

打完记得重推脚本：
    tf -tt ke -p <材料> -j 6 rerun --from-skill
    tf -tt kl -p <材料> -j 4 rerun --from-skill    （若动了 kl）

回滚：<文件名>.bak.<时间戳>
"""
import argparse
import os
import re
import shutil
import sys
import time

TS = time.strftime("%Y%m%d-%H%M%S")

GEN_EDITS = [
    ("skill/elastic/gen_step2_elastic.py",
     '        "ADDGRID": ".TRUE.",\n',
     '        # patch_remove_addgrid：ADDGRID 已去掉（VASP 默认 .FALSE.，\n'
     '        # 官方称用户反馈矛盾，MP 校验器要求必须 False；它还会改变\n'
     '        # CHGCAR 网格，导致与 step1 之间无法复用电荷密度）\n'),
    ("skill/ke/step6_elastic/gen_step2_elastic.py",
     '        "ADDGRID": ".TRUE.",\n',
     '        # patch_remove_addgrid：ADDGRID 已去掉（VASP 默认 .FALSE.，\n'
     '        # 官方称用户反馈矛盾，MP 校验器要求必须 False；它还会改变\n'
     '        # CHGCAR 网格，导致与 step1 之间无法复用电荷密度）\n'),
]

KL_EDITS = [
    ("skill/kl/templates/step4_disp/incar_force_2d.tpl",),
    ("skill/kl/templates/step4_disp/incar_force_3d.tpl",),
]

KL_HEADER_OLD = "# LREAL=.FALSE.（倒空间投影，力无噪声）、EDIFF=1E-8、ADDGRID、PREC=Accurate。\n"
KL_HEADER_NEW = "# LREAL=.FALSE.（倒空间投影，力无噪声）、EDIFF=1E-8、PREC=Accurate。\n"
KL_LINE_OLD = "ADDGRID = .TRUE.\n"


def write(p, txt, args):
    if args.dry_run:
        print("  + [dry] %s" % p)
        return
    bak = "%s.bak.%s" % (p, TS)
    if not os.path.exists(bak):
        shutil.copy2(p, bak)
    with open(p, "w", encoding="utf-8", newline="\n") as f:
        f.write(txt)
    print("  + %s" % p)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--skip-kl", action="store_true")
    ap.add_argument("--strip-false", action="store_true")
    ap.add_argument("--root", default=".")
    args = ap.parse_args()
    root = os.path.abspath(args.root)
    skill = os.path.join(root, "skill")
    if not os.path.isdir(skill):
        sys.exit("[ERROR] 请在 taskflow 包根目录运行")

    fails = []

    print("=== gen 脚本里注入的 ADDGRID=.TRUE. ===")
    for rel, old, new in GEN_EDITS:
        p = os.path.join(root, rel)
        if not os.path.isfile(p):
            fails.append("找不到 %s" % p)
            continue
        txt = open(p, encoding="utf-8").read()
        if "patch_remove_addgrid" in txt:
            print("  . %s（已打过）" % p)
            continue
        if txt.count(old) != 1:
            fails.append("%s：ADDGRID 锚点匹配 %d 次" % (p, txt.count(old)))
            continue
        write(p, txt.replace(old, new), args)

    if args.skip_kl:
        print("=== kl 位移取力模板：--skip-kl，跳过 ===")
    else:
        print("=== kl step4_disp 模板 ===")
        for (rel,) in KL_EDITS:
            p = os.path.join(root, rel)
            if not os.path.isfile(p):
                fails.append("找不到 %s" % p)
                continue
            txt = open(p, encoding="utf-8").read()
            if KL_LINE_OLD not in txt:
                print("  . %s（没有 ADDGRID=.TRUE.）" % p)
                continue
            txt = txt.replace(KL_LINE_OLD, "", 1)
            txt = txt.replace(KL_HEADER_OLD, KL_HEADER_NEW, 1)
            write(p, txt, args)

    if args.strip_false:
        print("=== --strip-false：删掉显式的 ADDGRID = .FALSE. 行 ===")
        pat = re.compile(r"^[ \t]*ADDGRID[ \t]*=[ \t]*\.FALSE\..*\n", re.M)
        for dirpath, _dn, fns in os.walk(skill):
            for fn in fns:
                if not fn.endswith((".tpl", ".py")):
                    continue
                p = os.path.join(dirpath, fn)
                txt = open(p, encoding="utf-8", errors="ignore").read()
                new = pat.sub("", txt)
                if new != txt:
                    write(p, new, args)

    print("\n=== 剩余的 ADDGRID 出现处（供你核对）===")
    left = []
    for dirpath, _dn, fns in os.walk(skill):
        for fn in fns:
            if not fn.endswith((".tpl", ".py", ".md", ".yaml")):
                continue
            p = os.path.join(dirpath, fn)
            for i, ln in enumerate(
                    open(p, encoding="utf-8", errors="ignore"), 1):
                if "ADDGRID" in ln and ".bak." not in p:
                    left.append("%s:%d: %s" % (os.path.relpath(p, root),
                                               i, ln.rstrip()))
    for x in sorted(left):
        print("  " + x)
    if not left:
        print("  （没有了）")

    if fails:
        print("\n失败：")
        for x in fails:
            print("  ! %s" % x)
        return 1
    if not args.dry_run:
        print("\n备份后缀 .bak.%s" % TS)
        print("重推：tf -tt ke -p <材料> -j 6 rerun --from-skill")
    return 0


if __name__ == "__main__":
    sys.exit(main())
