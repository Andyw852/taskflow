#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
patch_auto.py —— taskflow (tf) 自动化补丁
在 taskflow 包根目录下直接运行：  python3 patch_auto.py

做三件事：
  1. auto_advance 级联：一轮里把 run:gen 的本地即时步（画图/读取）连着推完，
     并立刻把新产物拉回 result/；碰到要交 SLURM 的步骤才停下等作业。
     另外，被"项目级 auto_advance: false"挡掉的材料会打一行提示。
  2. tf auto 支持技能级批量：
        tf -tt ke auto on          该技能下全部材料（并顺手打开全局开关）
        tf -tt ke -p A,B auto on   指定一个或多个材料
        tf -tt ke auto             只看当前开关状态
  3. 纯 tf（不带任何参数）只打印版本信息，不做任何采集/拉取/提交。
     状态请用  tf status（会 auto-fetch + auto-advance）；只读用 tf list。

可选：TF_AUTO_CASCADE=8 环境变量控制一轮最多级联几步（默认 8）。
回滚：把 versions/vX/tf.bak.<时间戳> 覆盖回 versions/vX/tf 即可。
"""
import os
import re
import shutil
import sys
import time

# --------------------------------------------------------------------------
# 1) auto_advance 级联 + 项目级跳过提示
# --------------------------------------------------------------------------
OLD_GATE = '''            st = (m.get("ps") or {}).get("setting") or {}
            if st.get("auto_advance") is False:
                continue
'''
NEW_GATE = '''            st = (m.get("ps") or {}).get("setting") or {}
            if st.get("auto_advance") is False:
                _skipped.append("%s[%s]" % (m["name"], m["tt"]))
                continue
'''

OLD_BODY = '''            s = m.get("active")
            if not s or s["kind"] not in ("TODO", "PREP"):
                continue
            sc = step_cfg(t, s["name"], m)
            do_submit(cfg, t, m, s, False, True, sc.get("contcar_to_poscar"),
                      "auto %s[%s|%s]" % (m["name"], m["tt"], s["label"]))
'''
NEW_BODY = '''            # --- patch_auto: 级联推进 ------------------------------------
            # 原实现每轮每材料只推一步。画图/读取这类 run:gen 的本地即时步
            # 几秒就完成，却要白等一整个 watch 周期才轮到下一步。这里改成：
            # 交了 SLURM 就停（等作业），本地即时步成功就接着往下推。
            _done_now = []
            for _ in range(_AUTO_CASCADE_MAX):
                s = m.get("active")
                if not s or s["kind"] not in ("TODO", "PREP"):
                    break
                sc = step_cfg(t, s["name"], m)
                _ok = do_submit(cfg, t, m, s, False, True,
                                sc.get("contcar_to_poscar"),
                                "auto %s[%s|%s]"
                                % (m["name"], m["tt"], s["label"]))
                if not _ok or sc.get("run") != "gen":
                    break
                # 即时步已产出 done_marker：就地标完成，把 active 挪到下一步
                s["done"], s["exists"] = True, True
                s["kind"], s["label_txt"] = "OK", "OK"
                if "diag" in s:
                    s["diag"] = "completed"
                _done_now.append(s["name"])
                m["active"] = next((x for x in m["steps"]
                                    if x["kind"] != "OK"), None)
            if _done_now and m.get("result_dir"):
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
            # --- patch_auto end ------------------------------------------
'''

OLD_AA_HEAD = '''def auto_advance(cfg, data):
'''
NEW_AA_HEAD = '''_AUTO_CASCADE_MAX = max(1, int(os.environ.get("TF_AUTO_CASCADE", "8") or 8))


def auto_advance(cfg, data):
'''

OLD_AA_GUARD = '''    if not cfg.get("auto_advance"):
        return
    for t in data["types"]:
        for m in t["materials"]:
'''
NEW_AA_GUARD = '''    if not cfg.get("auto_advance"):
        return
    _skipped = []
    for t in data["types"]:
        for m in t["materials"]:
'''

# auto_advance 末尾（紧跟其后的 cmd_step_init 定义）追加跳过提示
OLD_AA_TAIL = '''def cmd_step_init(cfg, data, proj, job, force):
'''
NEW_AA_TAIL = '''    if _skipped:
        print("auto-advance 跳过 %d 个（项目级 auto_advance: false）：%s"
              "  → tf -tt <技能> -p <材料> auto on"
              % (len(_skipped), ", ".join(_skipped[:6])
                 + ("…" if len(_skipped) > 6 else "")))


def cmd_step_init(cfg, data, proj, job, force):
'''

# --------------------------------------------------------------------------
# 2) tf -tt <技能> auto on|off —— 技能级批量
# --------------------------------------------------------------------------
OLD_DISPATCH = '''    if cmd == "auto":   # v1.5：一键开关 auto_advance（纯本地改 tf.yaml）
        _arg = mat_toks[0] if mat_toks else None
        if a.proj:      # v1.9.9：带 -p 就只改这些材料/技能的 setting.yaml
            sys.exit(cmd_auto_project(cfg, types, a.proj, a.tt, _arg))
        sys.exit(cmd_auto(cfg, _arg))
'''
NEW_DISPATCH = '''    if cmd == "auto":   # v1.5：一键开关 auto_advance（纯本地改 tf.yaml）
        _arg = mat_toks[0] if mat_toks else None
        if a.proj:      # v1.9.9：带 -p 就只改这些材料/技能的 setting.yaml
            sys.exit(cmd_auto_project(cfg, types, a.proj, a.tt, _arg))
        if a.tt:        # patch_auto：-tt 不带 -p = 该技能下全部材料
            sys.exit(cmd_auto_skill(cfg, types, a.tt, _arg))
        sys.exit(cmd_auto(cfg, _arg))
'''

OLD_HELPER_ANCHOR = '''def _proj_setting_path(lpath, tkey):
'''
NEW_HELPER_ANCHOR = '''def _skill_local_mats(cfg, types, tt):
    """patch_auto：列出该技能下本地已发现的材料名（纯本地，不连超算）。"""
    names, seen = [], set()
    for t0 in (types or []):
        if tt and t0.get("key") != tt:
            continue
        lr = t0.get("local_root")
        if not lr:
            continue
        try:
            _r, mats = discover_local(lr)
        except Exception:   # noqa: BLE001
            continue
        for mm in mats:
            if mm["name"] not in seen:
                seen.add(mm["name"])
                names.append(mm["name"])
    return names


def cmd_auto_skill(cfg, types, tt, arg):
    """patch_auto：tf -tt <技能> auto [on|off] —— 对该技能下全部材料批量
    开关项目级 auto_advance；on 时顺手把全局 tf.yaml 也打开。"""
    names = _skill_local_mats(cfg, types, tt)
    if not names:
        print("没有在技能 %s 下发现任何材料（检查 project_roots / local_root）。"
              % tt)
        return 1
    if arg is None:
        print("全局 auto_advance：%s"
              % ("开" if cfg.get("auto_advance") else "关"))
        return cmd_auto_project(cfg, types, ",".join(names), tt, None)
    if str(arg).strip().lower() in ("on", "1", "true", "开"):
        if not cfg.get("auto_advance"):
            cmd_auto(cfg, "on")          # 先开全局，避免下面误报"全局还是关的"
            cfg["auto_advance"] = True
    print("技能 %s：共 %d 个材料 → %s" % (tt, len(names), ", ".join(names)))
    return cmd_auto_project(cfg, types, ",".join(names), tt, arg)


def _proj_setting_path(lpath, tkey):
'''

# --------------------------------------------------------------------------
# 3) 纯 tf 只报版本
# --------------------------------------------------------------------------
OLD_ARGP = '''    p = argparse.ArgumentParser(prog="tf")
'''
NEW_ARGP = '''    if len(sys.argv) == 1:   # patch_auto：纯 tf = 只报版本，不采集/不提交
        print("taskflow (tf) version %s" % TF_VERSION)
        print("程序: %s" % os.path.realpath(__file__))
        print("")
        print("  tf list      只读总表（不拉取、不提交）")
        print("  tf status    刷新状态 + auto-fetch + auto-advance")
        print("  tf watch     后台监控（-i 秒，-d 放后台）")
        print("  tf -h        全部命令")
        return
    p = argparse.ArgumentParser(prog="tf")
'''

PATCHES = [
    ("auto_advance 常量", OLD_AA_HEAD, NEW_AA_HEAD),
    ("auto_advance 跳过统计", OLD_AA_GUARD, NEW_AA_GUARD),
    ("auto_advance 项目级门", OLD_GATE, NEW_GATE),
    ("auto_advance 级联主体", OLD_BODY, NEW_BODY),
    ("auto_advance 跳过提示", OLD_AA_TAIL, NEW_AA_TAIL),
    ("auto 技能级辅助函数", OLD_HELPER_ANCHOR, NEW_HELPER_ANCHOR),
    ("auto 命令分发", OLD_DISPATCH, NEW_DISPATCH),
    ("纯 tf 只报版本", OLD_ARGP, NEW_ARGP),
]

MARK = "patch_auto"


def find_tf(argv):
    if len(argv) > 1:
        return os.path.abspath(argv[1])
    here = os.getcwd()
    cands = []
    for root, dirs, files in os.walk(here):
        dirs[:] = [d for d in dirs if d not in (".git", "skill", "setting")]
        if "tf" in files and os.sep + "versions" + os.sep in root + os.sep:
            cands.append(os.path.join(root, "tf"))
    if not cands:
        p = os.path.join(here, "versions", "v1.0", "tf")
        if os.path.isfile(p):
            return p
    if len(cands) == 1:
        return cands[0]
    if len(cands) > 1:
        cands.sort()
        print("发现多个 tf，用最新的：%s" % cands[-1])
        return cands[-1]
    return None


def main():
    path = find_tf(sys.argv)
    if not path or not os.path.isfile(path):
        sys.exit("错误：没找到 versions/*/tf。请在 taskflow 包根下运行，"
                 "或显式指定：python3 patch_auto.py /path/to/versions/v1.0/tf")
    src = open(path, encoding="utf-8").read()

    if MARK in src:
        sys.exit("这个 tf 已经打过 patch_auto 补丁了，无需重复运行。\n"
                 "（要重打：先用 tf.bak.* 还原）")

    missing = [name for name, old, _ in PATCHES if src.count(old) != 1]
    if missing:
        sys.exit("错误：以下锚点没有唯一匹配，可能你的 tf 版本和补丁不符：\n  - "
                 + "\n  - ".join(missing)
                 + "\n补丁基于 GitHub Andyw852/taskflow @ d0bd8bb（TF_VERSION 1.0）。")

    out = src
    for _name, old, new in PATCHES:
        out = out.replace(old, new, 1)

    # 语法自检：编译不过就不落盘
    try:
        compile(out, path, "exec")
    except SyntaxError as e:
        sys.exit("错误：打完补丁后语法检查失败（%s 第 %s 行），已放弃写入。"
                 % (e.msg, e.lineno))

    bak = "%s.bak.%s" % (path, time.strftime("%Y%m%d-%H%M%S"))
    shutil.copy2(path, bak)
    mode = os.stat(path).st_mode
    with open(path, "w", encoding="utf-8") as f:
        f.write(out)
    os.chmod(path, mode)

    print("已打补丁：%s" % path)
    print("备份    ：%s" % bak)
    print("")
    print("自检：")
    print("  tf                     # 只应打印版本和命令提示")
    print("  tf -tt ke auto         # 看该技能各材料开关")
    print("  tf -tt ke auto on      # 全开（含全局）")
    print("  tf status              # 应连着推完 plot 类即时步")
    print("  tf watch -i 60 -d      # 后台监控")


if __name__ == "__main__":
    main()
