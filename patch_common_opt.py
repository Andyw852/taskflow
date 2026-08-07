#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
patch_common_opt.py —— skill/_common/ 按【公共步骤】分目录（取代 patch_common_layout.py）

上一版 patch_common_layout.py 按"功能模块"切成 relax/ dim/ check/ conf/，
分错了。正确的粒度是【公共步骤】：现在 _common/ 里的全部内容——七个 .py
加 templates/ 里的两个 0D 模板——服务的都是同一个东西，step1 结构优化。
band / elastic / ke / kl 四个技能复用的就是这一个步骤。

所以：

    _common/
      README.md              （不动）
      opt/                   ← 公共"结构优化"步骤，全部家当都在这
        relax_common.py      checks_relax.py
        dim_common.py        mol_common.py
        check_common.py      stepconf.py
        templates/
          incar_0d.tpl       submit_jzzn_vaspstd_0d.tpl

以后再有公共步骤（比如公共的 elastic / dielect），就是 _common/elastic/、
_common/dielect/，各自带自己的 templates/，互不干扰。

配套改 tf 的资源查找链（否则移完就找不到文件）：
  原来兜底到  <pool>/<tdir>、<pool>
  现在补上    <pool>/*/、<pool>/*/<tdir>
  —— 第二条是关键：templates 现在在 _common/opt/templates/ 而不是
     _common/templates/，不加这一条 incar_0d.tpl 就丢了。
另外把 _dim_mod 的搜索基目录也加上公共池（它原来只在技能目录里 glob
两层，而 dim_common.py 只有 _common 一份，所以这个函数一直返回 None）。

本脚本能识别并接管上一版 patch_common_layout.py 的结果：如果发现
relax/ dim/ check/ conf/ 那套布局，会先归拢再重排，不用手工还原。

用法（taskflow 包根目录）：
    python3 patch_common_opt.py --dry-run
    python3 patch_common_opt.py
    python3 patch_common_opt.py --revert
"""
import argparse
import glob
import json
import os
import shutil
import sys
import time

TS = time.strftime("%Y%m%d-%H%M%S")
MARK = "patch_common_opt"
OLD_MARK = "patch_common_layout"
MANIFEST = ".layout_manifest.json"

OPT_DIR = "opt"
OPT_FILES = ["relax_common.py", "checks_relax.py", "dim_common.py",
             "mol_common.py", "check_common.py", "stepconf.py"]
OLD_SUBS = ["relax", "dim", "check", "conf"]

# --------------------------------------------------------------------------
# tf 资源查找链：两种起始状态都能打
# --------------------------------------------------------------------------
ASSET_ORIG = '''    pool = os.path.join(os.path.dirname(os.path.normpath(base)), COMMON_POOL_DIR)
    out.append(os.path.join(pool, tdir))
    out.append(pool)
'''

ASSET_FROM_LAYOUT = '''    pool = os.path.join(os.path.dirname(os.path.normpath(base)), COMMON_POOL_DIR)
    out.append(os.path.join(pool, tdir))
    out.append(pool)
    # patch_common_layout：_common/ 按模块分了子目录（relax/ dim/ check/ conf/），
    # 把它们也纳入查找链。gen_need 里仍然只写文件名，skill.yaml 不用改。
    try:
        out.extend(sorted(d for d in glob.glob(os.path.join(pool, "*"))
                          if os.path.isdir(d)
                          and os.path.basename(d) != tdir))
    except OSError:
        pass
'''

ASSET_NEW = '''    pool = os.path.join(os.path.dirname(os.path.normpath(base)), COMMON_POOL_DIR)
    out.append(os.path.join(pool, tdir))
    out.append(pool)
    # patch_common_opt：_common/ 按【公共步骤】分目录（opt/ 等），每个步骤目录
    # 自带 templates/。查找链补上 <pool>/*/ 和 <pool>/*/<tdir> 两级——后者是
    # 关键，0D 模板现在在 _common/opt/templates/ 而不是 _common/templates/。
    # gen_need 里仍然只写文件名，skill.yaml 一行都不用改。
    try:
        for _d in sorted(d for d in glob.glob(os.path.join(pool, "*"))
                         if os.path.isdir(d)):
            out.append(_d)
            out.append(os.path.join(_d, tdir))
    except OSError:
        pass
'''

DIM_ORIG = '''        hits = []
        for b in bases:
            hits = sorted(glob.glob(os.path.join(b, "dim_common.py"))
                          + glob.glob(os.path.join(b, "*", "dim_common.py"))
                          + glob.glob(os.path.join(b, "*", "*", "dim_common.py")))
            if hits:
                break
'''

DIM_NEW = '''        # patch_common_opt：技能目录里找不到时回落到公共池 _common/
        # （及其步骤子目录）。dim_common.py 现在只有 _common 一份，
        # 不加这一段的话这个函数永远返回 None。
        for b in list(bases):
            pool = os.path.join(os.path.dirname(os.path.normpath(b)),
                                COMMON_POOL_DIR)
            if pool not in bases:
                bases.append(pool)
        hits = []
        for b in bases:
            hits = sorted(glob.glob(os.path.join(b, "dim_common.py"))
                          + glob.glob(os.path.join(b, "*", "dim_common.py"))
                          + glob.glob(os.path.join(b, "*", "*", "dim_common.py")))
            if hits:
                break
'''

DIM_FROM_LAYOUT = DIM_NEW.replace("patch_common_opt", "patch_common_layout") \
                         .replace("（及其步骤子目录）", "（及其分类子目录）")


def patch_tf(root, args):
    vdir = os.path.join(root, "versions")
    if not os.path.isdir(vdir):
        return ["找不到 versions/"]
    fails = []
    for d in sorted(os.listdir(vdir)):
        p = os.path.join(vdir, d, "tf")
        if not os.path.isfile(p):
            continue
        txt = open(p, encoding="utf-8").read()
        if MARK in txt:
            print("  . %s（已打过）" % p)
            continue
        # 资源链：可能是原始状态，也可能是上一版改过的状态
        if txt.count(ASSET_FROM_LAYOUT) == 1:
            txt = txt.replace(ASSET_FROM_LAYOUT, ASSET_NEW)
        elif txt.count(ASSET_ORIG) == 1:
            txt = txt.replace(ASSET_ORIG, ASSET_NEW)
        else:
            fails.append("%s：_skill_asset_dirs 锚点认不出（既非原始也非上一版）" % p)
            continue
        # _dim_mod：上一版已经加过就不重复
        if OLD_MARK in txt and DIM_FROM_LAYOUT in txt:
            pass
        elif txt.count(DIM_ORIG) == 1:
            txt = txt.replace(DIM_ORIG, DIM_NEW)
        elif "COMMON_POOL_DIR" in txt and "bases.append(pool)" in txt:
            pass                       # 已有等效逻辑
        else:
            fails.append("%s：_dim_mod 锚点匹配失败" % p)
            continue
        if args.dry_run:
            print("  + [dry] %s" % p)
        else:
            bak = "%s.bak.%s" % (p, TS)
            if not os.path.exists(bak):
                shutil.copy2(p, bak)
            with open(p, "w", encoding="utf-8", newline="\n") as f:
                f.write(txt)
            print("  + %s（备份 %s）" % (p, os.path.basename(bak)))
    return fails


def consolidate_old(common, args):
    """把上一版 relax/ dim/ check/ conf/ 里的文件先捞回 _common/ 顶层。"""
    n = 0
    for sub in OLD_SUBS:
        d = os.path.join(common, sub)
        if not os.path.isdir(d):
            continue
        for fn in sorted(os.listdir(d)):
            src, dst = os.path.join(d, fn), os.path.join(common, fn)
            if args.dry_run:
                print("  ~ [dry] 归拢 %s/%s" % (sub, fn))
            else:
                shutil.move(src, dst)
            n += 1
        if not args.dry_run and not os.listdir(d):
            os.rmdir(d)
    if n:
        print("  ~ 已归拢上一版 patch_common_layout 的 %d 个文件" % n)
    return n


def do_move(common, args):
    fails, moves = [], []
    optdir = os.path.join(common, OPT_DIR)
    opttpl = os.path.join(optdir, "templates")

    for fn in OPT_FILES:
        src = os.path.join(common, fn)
        if not os.path.isfile(src):
            if os.path.isfile(os.path.join(optdir, fn)):
                continue                      # 已经在 opt/ 里
            fails.append("找不到 %s" % src)
            continue
        moves.append({"from": fn, "to": "%s/%s" % (OPT_DIR, fn)})
        if args.dry_run:
            print("  + [dry] %s -> %s/" % (fn, OPT_DIR))
        else:
            os.makedirs(optdir, exist_ok=True)
            shutil.move(src, os.path.join(optdir, fn))
            print("  + %s -> %s/" % (fn, OPT_DIR))

    old_tpl = os.path.join(common, "templates")
    if os.path.isdir(old_tpl):
        for fn in sorted(os.listdir(old_tpl)):
            moves.append({"from": "templates/%s" % fn,
                          "to": "%s/templates/%s" % (OPT_DIR, fn)})
            if args.dry_run:
                print("  + [dry] templates/%s -> %s/templates/" % (fn, OPT_DIR))
            else:
                os.makedirs(opttpl, exist_ok=True)
                shutil.move(os.path.join(old_tpl, fn),
                            os.path.join(opttpl, fn))
                print("  + templates/%s -> %s/templates/" % (fn, OPT_DIR))
        if not args.dry_run and os.path.isdir(old_tpl) and not os.listdir(old_tpl):
            os.rmdir(old_tpl)

    if moves and not args.dry_run:
        with open(os.path.join(common, MANIFEST), "w", encoding="utf-8") as f:
            json.dump({"created": TS, "layout": "per_step", "moves": moves},
                      f, indent=2, ensure_ascii=False)
    return fails


def do_revert(common):
    mp = os.path.join(common, MANIFEST)
    if not os.path.isfile(mp):
        sys.exit("[ERROR] 没有 %s，无从还原" % mp)
    man = json.load(open(mp, encoding="utf-8"))
    for mv in man["moves"]:
        src, dst = os.path.join(common, mv["to"]), os.path.join(common, mv["from"])
        if os.path.isfile(src):
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            shutil.move(src, dst)
            print("  < %s -> %s" % (mv["to"], mv["from"]))
    for d in sorted(glob.glob(os.path.join(common, "*")), reverse=True):
        if os.path.isdir(d) and not os.listdir(d):
            os.rmdir(d)
    os.remove(mp)
    print("已还原。tf 请用 versions/vX/tf.bak.* 覆盖回去。")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--revert", action="store_true")
    ap.add_argument("--root", default=".")
    args = ap.parse_args()
    root = os.path.abspath(args.root)
    common = os.path.join(root, "skill", "_common")
    if not os.path.isdir(common):
        sys.exit("[ERROR] 找不到 %s，请在 taskflow 包根目录运行" % common)

    if args.revert:
        do_revert(common)
        return 0

    print("=== 归拢并按公共步骤重排 _common/ ===")
    consolidate_old(common, args)
    fails = do_move(common, args)
    print("=== 改 tf 的资源查找链 ===")
    fails += patch_tf(root, args)

    if fails:
        print("需要注意：")
        for x in fails:
            print("  ! %s" % x)
        return 1
    if not args.dry_run:
        print("\n验证：tf skills && tf -tt ke -p <材料> -j 1 conf")
        print("还原：python3 patch_common_opt.py --revert"
              " + cp versions/v1.0/tf.bak.%s versions/v1.0/tf" % TS)
    return 0


if __name__ == "__main__":
    sys.exit(main())
