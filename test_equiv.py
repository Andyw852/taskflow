# -*- coding: utf-8 -*-
"""等价性验证：打补丁后的 tf + skill/*/skill.yaml == 原版 tf + 内联 tf.yaml

    python3 test_equiv.py <原版 tf> <补丁后 tf> <原版 tf.yaml> <瘦身 tf.yaml>

比较两条路径展开出的步骤表逐字段一致（忽略新增的 seq 字段）。
"""
import copy, os, sys


def load_tf(path):
    src = open(path, encoding="utf-8").read().rstrip()
    if src.endswith("main()"):
        src = src[:-6]
    g = {"__file__": os.path.realpath(path), "__name__": "tfmod"}
    exec(compile(src, os.path.basename(path), "exec"), g)
    return g


def norm(steps):
    return [{k: v for k, v in s.items() if k != "seq" and v is not None}
            for s in steps]


def main():
    old_tf, new_tf, old_yaml, new_yaml = sys.argv[1:5]

    g_old = load_tf(old_tf)
    cfg, _ = g_old["load_config"](old_yaml)
    old = {}
    for k, tc in (cfg.get("task_types") or {}).items():
        t = copy.deepcopy(tc); t["key"] = k
        g_old["_inject_plot_steps"](t)
        old[k] = norm(t["steps"])

    g_new = load_tf(new_tf)
    cfg2, path = g_new["load_config"](new_yaml)
    cfg2["_config_dir"] = os.path.dirname(os.path.realpath(path))
    g_new["apply_skills"](cfg2, verbose=True)
    new = {}
    for k, tc in (cfg2.get("task_types") or {}).items():
        t = copy.deepcopy(tc); t["key"] = k
        g_new["expand_optional_steps"](t)
        new[k] = norm(t["steps"])

    print("发现技能：", sorted(cfg2.get("_skills") or {}))
    ok = True
    for k in sorted(set(old) | set(new)):
        a, b = old.get(k), new.get(k)
        same = a == b
        ok &= same
        print("[%s] %-8s old=%s new=%s" % ("OK " if same else "DIFF", k,
                                           len(a or []), len(b or [])))
        if not same:
            for x, y in zip(a or [], b or []):
                if x != y:
                    print("   old:", x); print("   new:", y)

    t = copy.deepcopy(cfg2["task_types"]["band"]); t["plot_steps"] = False
    g_new["expand_optional_steps"](t)
    print("plot_steps: false ->", [s["name"] for s in t["steps"]])
    print("band.skill_dir =", cfg2["task_types"]["band"].get("skill_dir"))
    print("\n等价性：", "全部通过" if ok else "存在差异")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
