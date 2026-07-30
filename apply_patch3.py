#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""apply_patch3.py —— 扇出步骤（v1.4）。

一个步骤目录下有 N 个子目录，每个子目录一份独立输入 + 独立 submit.sh，
各自 sbatch。清单里写：

    - {seq: 7, name: step7_deform, label: S7_deform, check: outcar,
       fanout: "deform-*", gen: gen_step7_deform.py, ...}

行为：
  提交  每个匹配子目录各 sbatch 一次；retry 只补没完成的那些
  状态  全部子目录判据都过才算 done；跑的时候显示 "7/13 done 5R 1PD"
  停止  scancel 该步骤的全部 jobid（代表 jobid 自动展开）
  重来  rerun 删掉整个步骤目录，连同所有子目录

前置：已打过 apply_patch.py 和 apply_patch2.py。

    python3 apply_patch3.py <tf 路径> [-o 输出路径]
"""
import argparse
import os
import sys

PRE1 = 'SKILL_MANIFEST = "skill.yaml"'
PRE2 = "def _skill_asset_dirs("
APPLIED = "def remote_sbatch_fanout("

# ---------------------------------------------------------------------------
# P1  采集器：扇出步骤的状态聚合
# ---------------------------------------------------------------------------
P1_OLD = '''            j = jobs_by_dir.get(d)
            f["job"] = j
            if sc.get("check") == "plot":'''

P1_NEW = '''            j = jobs_by_dir.get(d)
            f["job"] = j
            if sc.get("fanout"):
                # v1.4 扇出步骤：步骤目录下每个子目录 = 一个独立作业。
                # done 要求全部子目录判据都过；has_* 取子目录的并集，
                # 这样 step_state 的 PREP/TODO/FAIL 三态判断照常成立。
                subs = sorted((p for p in glob.glob(
                    os.path.join(d, str(sc["fanout"]))) if os.path.isdir(p)),
                    key=natkey)
                ck = CHECKERS.get(sc.get("check", "outcar"), ck_outcar)
                fj, ndone, todo = [], 0, []
                for p in subs:
                    jp = jobs_by_dir.get(p)
                    okp = ck(p, sc)[0]
                    if okp:
                        ndone += 1
                    if jp:
                        fj.append(jp)
                    elif not okp:
                        todo.append(os.path.basename(p))
                n = len(subs)
                f["fanout"] = str(sc["fanout"])   # 回填 glob，本地提交要用
                f["subs"] = [os.path.basename(p) for p in subs]
                f["fan_jobids"] = [x["id"] for x in fj]
                f["fan_todo"] = todo          # 没作业也没完成 → 待提交/失败
                f["fan_done"] = ndone
                f["has_incar"] = any(os.path.isfile(os.path.join(p, "INCAR"))
                                     for p in subs)
                f["has_outcar"] = any(os.path.isfile(os.path.join(p, "OUTCAR"))
                                      for p in subs)
                f["has_slurm_out"] = any(glob.glob(os.path.join(p, "slurm-*.out"))
                                         for p in subs)
                if fj:
                    nr = sum(1 for x in fj if x.get("state") in ("R", "CG", "CF"))
                    npd = sum(1 for x in fj if x.get("state") == "PD")
                    f["job"] = dict(fj[0])
                    f["job"]["info"] = "%d/%d %dR %dPD" % (ndone, n, nr, npd)
                    f["job"]["state"] = "R" if nr else "PD"
                    f["done"] = False
                    f["diag"] = ""     # 进度已在 label 里（R@3/5 2R 0PD），不重复
                elif not n:
                    f["done"], f["diag"] = False, "dir missing"
                else:
                    f["done"] = (ndone == n)
                    f["diag"] = ("%d/%d" % (ndone, n) if f["done"] else
                                 "%d/%d 完成；未完成 %s" %
                                 (ndone, n, ",".join(todo[:4]) +
                                  ("…" if len(todo) > 4 else "")))
            elif sc.get("check") == "plot":'''

# ---------------------------------------------------------------------------
# P2  本地：扇出提交
# ---------------------------------------------------------------------------
P2_OLD = "def remote_sbatch(cfg, s, jobname=None):"

P2_NEW = '''FAN_JOBIDS = {}   # 代表 jobid → 该扇出步骤的全部 jobid（scancel 时展开）


def remote_sbatch_fanout(cfg, s, jobname=None):
    """扇出步骤：步骤目录下每个匹配子目录各自 sbatch 一次。

    s["fan_todo"] 非空时只提交这些子目录（retry 只补没完成的）；
    为空或缺失时提交全部（首次 gen 之后就是这条路）。
    返回 (是否成功, 输出, 逗号分隔的全部 jobid)。
    """
    pat = str(s.get("fanout"))
    only = s.get("fan_todo") or None
    cands = [s["submit"]] + [c for c in ("submit.sh", "sub.sh", "job.sh",
                                         "run.sh", "sub.slurm")
                             if c != s["submit"]]
    jn = re.sub(r"[^A-Za-z0-9_.-]", "_", str(jobname or ""))
    ln = ["cd %s || exit 1" % shlex.quote(s["dir"]), "rc=0",
          "ONLY=%s" % (shlex.quote(" ".join(only)) if only else "''"),
          "for d in %s; do" % pat,
          '  [ -d "$d" ] || continue',
          '  if [ -n "$ONLY" ]; then',
          '    case " $ONLY " in *" $d "*) ;; *) continue ;; esac',
          '  fi',
          '  ( cd "$d" || exit 1',
          '    f=""',
          '    for c in %s; do [ -f "$c" ] && f="$c" && break; done' % " ".join(cands),
          '    [ -z "$f" ] && f=$(ls *.sub *.slurm 2>/dev/null | head -1)',
          '    if [ -z "$f" ]; then',
          '      echo "ERROR: $d 里找不到提交脚本" >&2; exit 1',
          '    fi']
    if jn:
        ln.append('    sed -i -e "s/^#SBATCH[[:space:]]\\\\+--job-name=.*/'
                  '#SBATCH --job-name=%s-$d/" -e "s/^#SBATCH[[:space:]]\\\\+-J'
                  '[[:space:]].*/#SBATCH --job-name=%s-$d/" "$f" '
                  '2>/dev/null || true' % (jn, jn))
    ln += ['    sbatch "$f" ) || rc=1',
           "done",
           "exit $rc"]
    rc, out = run_remote(cfg, sh_b64("\\n".join(ln)),
                         host=s.get("_host") or "__default__")
    jids = re.findall(r"Submitted batch job\\s+(\\d+)", out or "")
    return (rc == 0 and bool(jids)), out, (",".join(jids) if jids else None)


def remote_sbatch(cfg, s, jobname=None):
    if s.get("fanout"):                       # v1.4
        return remote_sbatch_fanout(cfg, s, jobname=jobname)'''

# ---------------------------------------------------------------------------
# P3  本地：scancel 展开扇出步骤的全部 jobid
# ---------------------------------------------------------------------------
P3_OLD = '''def remote_scancel(cfg, jobids, host="__default__"):
    if not jobids:
        return True, ""'''
P3_NEW = '''def remote_scancel(cfg, jobids, host="__default__"):
    ids = []                                  # v1.4：代表 jobid → 全部 jobid
    for x in (jobids or []):
        for y in FAN_JOBIDS.get(str(x), [str(x)]):
            if y not in ids:
                ids.append(y)
    jobids = ids
    if not jobids:
        return True, ""'''

# ---------------------------------------------------------------------------
# P4  annotate 时登记扇出 jobid（scancel 之前一定跑过）
# ---------------------------------------------------------------------------
P4_OLD = '''                s["label_txt"], s["kind"] = step_state(s, blocked)'''
P4_NEW = '''                if s.get("fan_jobids"):        # v1.4
                    FAN_JOBIDS[str(s["fan_jobids"][0])] = \\
                        [str(x) for x in s["fan_jobids"]]
                s["label_txt"], s["kind"] = step_state(s, blocked)'''

PATCHES = [
    ("P1  采集器：扇出状态聚合", P1_OLD, P1_NEW),
    ("P2  本地：扇出提交", P2_OLD, P2_NEW),
    ("P3  本地：scancel 展开", P3_OLD, P3_NEW),
    ("P4  annotate 登记扇出 jobid", P4_OLD, P4_NEW),
]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("tf")
    ap.add_argument("-o", "--out")
    a = ap.parse_args()
    src = open(a.tf, encoding="utf-8").read()
    for mark, why in ((PRE1, "apply_patch.py"), (PRE2, "apply_patch2.py")):
        if mark not in src:
            sys.exit("失败：这个 tf 还没打过 %s。" % why)
    if APPLIED in src:
        sys.exit("该 tf 已经打过本补丁，无需重复执行。")

    for name, old, new in PATCHES:
        n = src.count(old)
        if n != 1:
            sys.exit("失败：%s 的锚点出现 %d 次（应为 1 次）。\n锚点：%s"
                     % (name, n, old.splitlines()[0][:70]))
        src = src.replace(old, new, 1)
        print("  ok  " + name)

    out = a.out or (a.tf + ".patched3")
    with open(out, "w", encoding="utf-8") as f:
        f.write(src)
    os.chmod(out, 0o755)
    print("\n已写出 %s（%d 行）" % (out, src.count("\n") + 1))


if __name__ == "__main__":
    main()
