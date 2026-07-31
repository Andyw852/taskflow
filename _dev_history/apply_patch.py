#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""apply_patch.py —— 把技能插件化改造打进 tf 主程序。

用法：
    python3 apply_patch.py <原始 tf 路径> [-o 输出路径]

默认输出 <原始 tf>.patched，不动原文件。每处改动前都做唯一性断言，
锚点对不上就直接报错退出，不会写出半成品。可重复运行（已打过会跳过）。
"""
import argparse
import os
import re
import sys

APPLIED_MARK = "SKILL_MANIFEST = \"skill.yaml\""

# ---------------------------------------------------------------------------
# P0  内置 YAML 解析器支持跨行的 [] / {}
# ---------------------------------------------------------------------------
P0_HELPER = '''def _flow_depth(s, depth=0):
    """统计一行结束时未闭合的 [ / { 层数；跳过引号内内容和行尾注释。"""
    q = None
    for ch in s:
        if q:
            if ch == q:
                q = None
        elif ch in "\\"'":
            q = ch
        elif ch == "#" and depth == 0:
            break
        elif ch in "[{":
            depth += 1
        elif ch in "]}":
            depth = max(0, depth - 1)
    return depth


'''

P0_ANCHOR = '''        indent = len(s) - len(s.lstrip(" "))
        stripped = s.strip()
'''

P0_NEW = P0_ANCHOR + '''        d = _flow_depth(stripped)          # v1.2：跨行的 [] / {} 拼成一行
        while d > 0 and i < len(raw_lines):
            nxt = _yaml_strip_comment(raw_lines[i]).strip()
            i += 1
            if not nxt:
                continue
            stripped = stripped.rstrip() + " " + nxt
            d = _flow_depth(nxt, d)
'''

# ---------------------------------------------------------------------------
# P1  技能注册表（整段插入到 load_config 之后）
# ---------------------------------------------------------------------------
P1_ANCHOR = "def scan_project_configs(roots):"

P1_BLOCK = r'''# ===========================================================================
# 技能注册表（v1.2）—— 新增/删除技能 = 新建/删除一个技能目录，主程序不动
#
# 技能 = 目录 + 目录里的 skill.yaml（可选 checks.py）。tf 扫描技能搜索路径，
# 把每个 skill.yaml 解析成 task_types 骨架；全局 tf.yaml / 项目 tf_<项目>.yaml
# 只写站点相关覆盖（work_dir、hpc、run_steps、开关…），不用再抄 steps。
# 优先级（后者覆盖前者）：skill.yaml < 全局 tf.yaml < 项目配置
# ===========================================================================
SKILL_MANIFEST = "skill.yaml"
SKILL_SCHEMA_MAX = 1

# 这些键从清单顶层直接进类型骨架；其余顶层键只是元信息
_MANIFEST_TYPE_KEYS = ("desc", "steps", "optional_steps", "gen_need", "aux_files",
                       "gen_dir", "plot_steps", "run_steps", "dir_name",
                       "skill_subdir", "hpc", "work_dir", "root")


def skill_search_dirs(cfg):
    """技能搜索路径，靠前优先（同名技能先命中者生效）。"""
    pkg_root = os.path.normpath(os.path.join(
        os.path.dirname(os.path.realpath(__file__)), "..", ".."))
    cdir = cfg.get("_config_dir") or ""
    cands = ["./skill"]
    cands += [os.path.expanduser(str(p)) for p in (cfg.get("skill_paths") or [])]
    if cdir:
        cands += [os.path.join(cdir, "skill"),
                  os.path.normpath(os.path.join(cdir, "..", "skill"))]
    cands += [os.path.join(pkg_root, "skill"), os.path.expanduser("~/.tf/skill")]
    out, seen = [], set()
    for d in cands:
        rd = os.path.realpath(d)
        if rd not in seen and os.path.isdir(rd):
            seen.add(rd)
            out.append(rd)
    return out


def _load_manifest(path):
    """解析单个 skill.yaml；返回 (key, 骨架) 或 (None, 原因)。"""
    try:
        with open(path, encoding="utf-8") as f:
            text = f.read()
    except OSError as e:
        return None, "读取失败：%s" % e
    try:
        try:
            import yaml
            man = yaml.safe_load(text) or {}
        except ImportError:
            man = _mini_yaml(text) or {}
    except Exception as e:
        return None, "解析失败：%s" % e
    if not isinstance(man, dict):
        return None, "顶层不是字典"
    try:
        schema = int(man.get("schema") or 1)
    except (TypeError, ValueError):
        return None, "schema 不是整数"
    if schema > SKILL_SCHEMA_MAX:
        return None, ("schema %d 高于本版 tf 支持的 %d，请升级 tf"
                      % (schema, SKILL_SCHEMA_MAX))
    sdir = os.path.dirname(os.path.realpath(path))
    key = str(man.get("name") or os.path.basename(sdir)).strip()
    if not key:
        return None, "缺少 name"
    if man.get("enabled") is False:
        return None, "__disabled__"
    skel = dict(man.get("defaults") or {})
    for k in _MANIFEST_TYPE_KEYS:
        if k in man and man[k] is not None:
            skel[k] = man[k]
    if not skel.get("steps"):
        return None, "没有 steps"
    skel["skill_dir"] = sdir               # 绝对路径，find_asset 直接可用
    skel.setdefault("desc", key)
    skel["_skill_manifest"] = path
    skel["_skill_version"] = man.get("version")
    skel["_skill_requires"] = man.get("requires") or {}
    chk = man.get("checks", "checks.py")
    cp = os.path.join(sdir, str(chk)) if chk else None
    skel["_skill_checks"] = cp if (cp and os.path.isfile(cp)) else None
    return key, skel


def discover_skills(cfg, verbose=False):
    """扫描所有搜索路径，返回 {key: 骨架}；靠前路径优先，同名不覆盖。"""
    found, bad = {}, []
    for base in skill_search_dirs(cfg):
        for mp in sorted(glob.glob(os.path.join(base, "*", SKILL_MANIFEST))):
            key, skel = _load_manifest(mp)
            if key is None:
                if skel != "__disabled__":
                    bad.append((mp, skel))
                continue
            if key in found:
                continue
            found[key] = skel
    if bad and verbose:
        for mp, why in bad:
            sys.stderr.write("警告：技能清单 %s 已忽略（%s）\n" % (mp, why))
    return found


def _merge_type(skel, over):
    """技能骨架 + 用户覆盖。标量/列表整体覆盖，一层字典递归合并；
    用户显式写 steps 就完全接管（保留手改逃生口）。"""
    out = dict(skel)
    for k, v in (over or {}).items():
        if v is None:
            continue
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            m = dict(out[k])
            m.update(v)
            out[k] = m
        else:
            out[k] = v
    return out


def apply_skills(cfg, verbose=False):
    """把发现到的技能并进 cfg['task_types']；已有同名段作为覆盖层。
    必须在 merge_project_configs 之前调用（项目段要叠在骨架之上）。"""
    skills = discover_skills(cfg, verbose=verbose)
    white = cfg.get("enabled_skills")
    black = set(cfg.get("disabled_skills") or [])
    tt = dict(cfg.get("task_types") or {})
    for key, skel in skills.items():
        if white and key not in white:
            continue
        if key in black:
            tt.pop(key, None)
            continue
        tt[key] = _merge_type(skel, tt.get(key) or {})
    for key in black:      # 黑名单也能关掉纯 tf.yaml 定义的类型
        tt.pop(key, None)
    cfg["task_types"] = tt
    cfg["_skills"] = skills
    return cfg


def expand_optional_steps(t):
    """可选步骤组展开（取代写死的 PLOT_STEP_DEFS / _inject_plot_steps）。
    optional_steps.<开关名>.{default, steps[]}；步骤里的 after 是锚点名前缀，
    命中则插在最后一个匹配项之后，锚点不存在就不注入。
    先按名字剔除再插入，顺带修掉「段之间浅拷贝共享 steps 列表」的老问题。"""
    steps = t.get("steps")
    if not isinstance(steps, list):
        return
    steps = list(steps)
    for flag, spec in (t.get("optional_steps") or {}).items():
        spec = spec or {}
        defs = spec.get("steps") or []
        names = {d.get("name") for d in defs}
        steps = [s for s in steps if s.get("name") not in names]
        if t.get(flag, spec.get("default", True)) is False:
            continue
        for d in defs:
            anchor = d.get("after")
            d2 = {k: v for k, v in d.items() if k != "after"}
            pos = None
            if anchor:
                for i, s in enumerate(steps):
                    if str(s.get("name", "")).startswith(str(anchor)):
                        pos = i
                if pos is None:
                    continue
            steps.insert(pos + 1 if pos is not None else len(steps), d2)
    t["steps"] = steps


def step_seq(s):
    """步骤序号：优先清单里的 seq，缺省从 stepN 名字推。"""
    if s.get("seq") is not None:
        return str(s["seq"])
    m = re.match(r"step(\d+)", str(s.get("name", "")))
    return m.group(1) if m else None


def skill_checks_for(cfg, keys):
    """收集这些技能的私有判据源码 {key: 源码}，随采集器 payload 下发。"""
    out = {}
    for k in keys:
        if k in out:
            continue
        p = ((cfg.get("_skills") or {}).get(k) or {}).get("_skill_checks")
        if not p:
            continue
        try:
            with open(p, encoding="utf-8") as f:
                out[k] = f.read()
        except OSError as e:
            sys.exit("错误：技能 %s 的判据文件 %s 读取失败（%s）。" % (k, p, e))
    return out


def cmd_skills(cfg, tt=None):
    """tf skills —— 列出已发现的技能。"""
    skills = cfg.get("_skills") or discover_skills(cfg, verbose=True)
    if not skills:
        print("没有发现任何技能清单（skill/*/skill.yaml）。搜索路径：")
        for d in skill_search_dirs(cfg):
            print("  " + d)
        return 0
    black = set(cfg.get("disabled_skills") or [])
    white = cfg.get("enabled_skills")
    print("%-10s %-8s %-6s %-6s %s" % ("技能", "版本", "步骤", "状态", "清单"))
    for k in sorted(skills):
        if tt and k != tt:
            continue
        s = skills[k]
        st = "关闭" if (k in black or (white and k not in white)) else "启用"
        print("%-10s %-8s %-6d %-6s %s"
              % (k, s.get("_skill_version") or "-", len(s.get("steps") or []),
                 st, s.get("_skill_manifest")))
    print("\n搜索路径（靠前优先）：")
    for d in skill_search_dirs(cfg):
        print("  " + d)
    return 0


'''

# ---------------------------------------------------------------------------
# P2  main() 里挂上 apply_skills
# ---------------------------------------------------------------------------
P2_ANCHOR = '''    cfg["_config_path"] = cfg_path
    cfg = merge_project_configs(cfg)'''
P2_NEW = '''    cfg["_config_path"] = cfg_path
    cfg = apply_skills(cfg, verbose=True)   # v1.2：先装配 skill/*/skill.yaml
    if cmd == "skills":
        return cmd_skills(cfg, tt=a.tt)
    cfg = merge_project_configs(cfg)'''

# ---------------------------------------------------------------------------
# P3  删掉写死的能带画图注入
# ---------------------------------------------------------------------------
P3_CALL_OLD = '        _inject_plot_steps(t)   # v3.21：注入能带画图步骤（plot_steps: false 关闭）'
P3_CALL_NEW = '        expand_optional_steps(t)   # v1.2：按技能清单展开可选步骤组'

# ---------------------------------------------------------------------------
# P4  run_steps 序号匹配通用化
# ---------------------------------------------------------------------------
P4_OLD = '''    def match(s, tok):
        name = str(s.get("name", ""))
        ts = str(tok).strip()
        if ts in ("3.1", "4.1"):   # yaml 里 3.1 可能是浮点，统一转字符串
            return name == "step%s_band_plot" % ts[0]
        if ts.isdigit():
            # step1..step4；三段式弛豫的 step1a/b/c 前缀同为 step1，一并归入序号 1
            return name.startswith("step%d" % int(ts)) and "band_plot" not in name
        return ts == name or ts == str(s.get("label", ""))'''

P4_NEW = '''    def match(s, tok):
        ts = str(tok).strip()
        if ts == str(s.get("name", "")) or ts == str(s.get("label", "")):
            return True
        sq = step_seq(s)           # v1.2：序号来自清单的 seq，不再认 band_plot
        if sq is None:
            return False
        try:
            return float(ts) == float(sq)
        except ValueError:
            return False'''

# ---------------------------------------------------------------------------
# P5  步骤参数下发：白名单 → 黑名单（技能自定义判据参数才能传到远端）
# ---------------------------------------------------------------------------
P5_OLD = '''            for k in ("stage", "relax_diag", "phrase", "pressure_tol",
                      "done_marker"):
                if s.get(k) is not None:
                    sd[k] = s[k]'''

P5_NEW = '''            # v1.2：改成黑名单——这些键 tf 本地自己消费，其余（含技能私有
            # 判据参数，如 kappa_rtol）一律透传给远端采集器，加技能不用改这里
            for k, v in s.items():
                if k in _LOCAL_ONLY_STEP_KEYS or k in sd or v is None:
                    continue
                sd[k] = v'''

P5_CONST = '''# 这些步骤键由 tf 本地消费，不下发给远端采集器；其余键一律透传
_LOCAL_ONLY_STEP_KEYS = {"gen", "gen_need", "aux_files", "run", "group", "seq",
                         "contcar_to_poscar", "fetch_all", "fetch_files", "after"}


def collect_v3_batch(cfg, segs):'''

# ---------------------------------------------------------------------------
# P6  采集器 payload 带上技能判据 + 远端注册
# ---------------------------------------------------------------------------
P6_OLD = '''def collect(cfg, types, host="__default__"):
    payload = base64.b64encode(
        json.dumps({"user": cfg.get("user"), "types": types}).encode()).decode()'''

P6_NEW = '''def collect(cfg, types, host="__default__"):
    # v1.2：把本次涉及技能的 checks.py 源码一起打包，远端注册成判据
    extra = skill_checks_for(cfg, [td.get("key") for td in types])
    payload = base64.b64encode(
        json.dumps({"user": cfg.get("user"), "types": types,
                    "extra_checks": extra}).encode()).decode()'''

P6_REMOTE_OLD = '''    _t1 = _time.time()
    types = [collect_type(t, jobs_by_dir) for t in cfg["types"]]'''

P6_REMOTE_NEW = '''    # 技能私有判据：源码随 payload 下发，在这里注册进 CHECKERS
    for _sk, _src in (cfg.get("extra_checks") or {}).items():
        _ns = dict(globals())
        try:
            exec(compile(_src, "<skill:%s>" % _sk, "exec"), _ns)
        except Exception as _e:
            sys.exit("技能 %s 的 checks.py 执行失败：%s" % (_sk, _e))
        for _n, _f in (_ns.get("CHECKERS") or {}).items():
            if _n in CHECKERS:
                sys.exit("技能 %s 的判据名 %s 与已有判据冲突，请改名。" % (_sk, _n))
            CHECKERS[_n] = _f

    _t1 = _time.time()
    types = [collect_type(t, jobs_by_dir) for t in cfg["types"]]'''

# ---------------------------------------------------------------------------
# P7  命令表加 skills；帮助文本补一行
# ---------------------------------------------------------------------------
P7_OLD = '''    commands = {"status", "start", "stop", "retry", "rerun", "json", "config",
                "dir", "fetch", "init", "clean", "watch", "help", "auto",
                "adopt", "migrate-subdir", "hpc"}'''
P7_NEW = '''    commands = {"status", "start", "stop", "retry", "rerun", "json", "config",
                "dir", "fetch", "init", "clean", "watch", "help", "auto",
                "adopt", "migrate-subdir", "hpc", "skills"}'''

# ---------------------------------------------------------------------------
# P8  EXAMPLE_CONFIG 去掉内联的 band 步骤定义
# ---------------------------------------------------------------------------
P8_START = "# 全局 task_types（可选）：作为公共骨架"
P8_END = "\n# 老模式也支持：类型里写 root"
P8_NEW = '''# task_types：只写站点相关覆盖。技能的 steps / gen_need / aux_files 由
# skill/<技能>/skill.yaml 自描述，tf 启动时自动发现（tf skills 查看），
# 这里不用再抄一遍。key 就是 -tt 用的短名，等于技能名。
task_types:
  band:
    work_dir: /public/home/wangchao/Fullerene_Network/work
                           # 超算工作根：远端目录 = work_dir + 材料相对路径
    # hpc: jzzn            # 覆盖清单里的默认集群
    # plot_steps: false    # 关掉该技能清单里 optional_steps 的画图步骤组
    # run_steps: [1, 2]    # 只跑部分步骤（序号 = 清单里的 seq）
    # steps: [...]         # 逃生口：写了就完全接管清单里的步骤定义
  elastic:
    work_dir: /public/home/wangchao/Fullerene_Network/work

# 技能开关与搜索路径（都可选）
# enabled_skills: [band, elastic]     # 白名单，写了就只启用这些
# disabled_skills: [kl]               # 黑名单
# skill_paths: [~/my-tf-skills]       # 追加技能搜索路径
'''

PATCHES = [
    ("P0a 内置 YAML：_flow_depth 助手", "def _mini_yaml(text):",
     P0_HELPER + "def _mini_yaml(text):", "insert"),
    ("P0b 内置 YAML：跨行 [] {}", P0_ANCHOR, P0_NEW, "replace"),
    ("P1  技能注册表", P1_ANCHOR, P1_BLOCK + P1_ANCHOR, "insert"),
    ("P2  main() 装配技能", P2_ANCHOR, P2_NEW, "replace"),
    ("P3  可选步骤组取代画图注入", P3_CALL_OLD, P3_CALL_NEW, "replace"),
    ("P4  run_steps 序号通用化", P4_OLD, P4_NEW, "replace"),
    ("P5a 步骤键黑名单常量", "def collect_v3_batch(cfg, segs):", P5_CONST, "replace"),
    ("P5b 步骤参数透传", P5_OLD, P5_NEW, "replace"),
    ("P6a 采集器 payload 带判据", P6_OLD, P6_NEW, "replace"),
    ("P6b 远端注册技能判据", P6_REMOTE_OLD, P6_REMOTE_NEW, "replace"),
    ("P7  skills 子命令", P7_OLD, P7_NEW, "replace"),
]


def strip_plot_defs(src):
    """删掉 PLOT_STEP_DEFS 常量和 _inject_plot_steps 函数整体。"""
    i = src.find("# 能带画图步骤（v3.21）")
    j = src.find("PLOT_STEP_DEFS = [")
    if i < 0 or j < 0:
        return src, False
    k = src.find("def _filter_run_steps(t):")
    if k < 0:
        return src, False
    src = src[:i] + src[k:]
    a = src.find("def _inject_plot_steps(t):")
    b = src.find("def get_types(cfg", a if a > 0 else 0)
    if a < 0 or b < 0:
        return src, False
    return src[:a] + src[b:], True


def trim_example_config(src):
    i = src.find(P8_START)
    j = src.find(P8_END)
    if i < 0 or j < 0 or j < i:
        return src, False
    return src[:i] + P8_NEW + src[j:], True


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("tf")
    ap.add_argument("-o", "--out")
    a = ap.parse_args()
    with open(a.tf, encoding="utf-8") as f:
        src = f.read()
    if APPLIED_MARK in src:
        sys.exit("该 tf 已经打过补丁（检测到技能注册表），无需重复执行。")

    for name, old, new, mode in PATCHES:
        n = src.count(old)
        if n != 1:
            sys.exit("失败：%s 的锚点在源码中出现 %d 次（应为 1 次）。\n锚点：%s"
                     % (name, n, old.splitlines()[0][:70]))
        src = src.replace(old, new, 1)
        print("  ok  " + name)

    src, ok = strip_plot_defs(src)
    print(("  ok  " if ok else " FAIL ") + "P3b 删除 PLOT_STEP_DEFS / _inject_plot_steps")
    if not ok:
        sys.exit(1)
    src, ok = trim_example_config(src)
    print(("  ok  " if ok else " FAIL ") + "P8  EXAMPLE_CONFIG 瘦身")
    if not ok:
        sys.exit(1)

    out = a.out or (a.tf + ".patched")
    with open(out, "w", encoding="utf-8") as f:
        f.write(src)
    os.chmod(out, 0o755)
    print("\n已写出 %s（%d 行）" % (out, src.count("\n") + 1))


if __name__ == "__main__":
    main()
