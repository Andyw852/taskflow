#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""gen_step6_kappa.py —— BTE 晶格热导率，提交计算节点（step6_kappa）。

从 step5_fc 拷 fc2/fc3/phono3py_disp.yaml/BORN，按 kl_params 的 MESH 组 BTE 命令，
渲染提交模板 → submit.sh，tf 提交到计算节点。成功后把 κ 张量写进 kappa_summary.json
并落 KAPPA_DONE（marker 判据）。
求解器（step.conf 的 SOLVER）：
  phono3py : phono3py-load --br（完整支持 findiff/alm + NAC，默认）
  shengbte : 写 ShengBTE CONTROL（复用参考引擎例程）。注意 fc3→ShengBTE 导出仅
             random/hiphive 路线可靠，findiff 的 compact fc3 无稳定导出口——solver=shengbte
             建议配 METHOD=alm，且需在集群装好 ShengBTE、把 exe 填进 step.conf。
产出目录：step6_kappa/
"""
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import kl_common as kc
import stepconf

OUTDIR = "step6_kappa"
STEP   = "step6_kappa"
FC_DIR = "step5_fc"

SPEC = {
    "FUNC":        ("pbesol", "str"),  # 全局 step.conf 带入，本步不用
    "SOLVER":       ("phono3py", "str"),  # phono3py | shengbte
    "MESH_OVERRIDE": (None,     "str"),   # 空=用 step4 写入 kl_params 的 MESH
    "T_MIN":        (100,       "int"),
    "T_MAX":        (800,       "int"),
    "T_STEP":       (100,       "int"),
    "ISOTOPE":      (True,      "bool"),
    "SCALEBROAD":   (0.1,       "float"), # shengbte 展宽
    "SHENGBTE_EXE": ("ShengBTE", "str"),
}

# phono3py 跑完后就地抽 κ 到 kappa_summary.json 的小脚本（在计算节点 conda 环境里执行）
_EXTRACT = (
    "python - <<'PY'\n"
    "import glob,json,h5py,numpy as np\n"
    "fs=sorted(glob.glob('kappa-m*.hdf5'))\n"
    "d={'KAPPA_DONE':bool(fs)}\n"
    "if fs:\n"
    "    with h5py.File(fs[-1],'r') as f:\n"
    "        T=np.array(f['temperature']); K=np.array(f['kappa'])\n"
    "        d['file']=fs[-1]; d['temperatures']=T.tolist()\n"
    "        d['kappa_xx_yy_zz']=[[float(K[i,0]),float(K[i,1]),float(K[i,2])] for i in range(len(T))]\n"
    "json.dump(d,open('kappa_summary.json','w'),ensure_ascii=False,indent=2)\n"
    "print('KAPPA_DONE' if fs else 'NO_KAPPA')\n"
    "PY")


def build_phono3py_cmd(mesh, ts, isotope, use_nac):
    p3 = ('phono3py-load phono3py_disp.yaml --br --mesh %s --ts="%s"%s%s'
          % (mesh, ts, " --isotope" if isotope else "", " --nac" if use_nac else ""))
    return "%s 2>&1 | tee phono3py_kappa.log\n%s" % (p3, _EXTRACT)


def write_shengbte_control(cwd, out, conf, mesh, use_nac):
    """复用参考引擎写 CONTROL；fc 导出留给用户/后续（findiff compact fc3 无稳定导出口）。"""
    try:
        import lattice_kappa as lk
        from ase.io import read as ase_read
    except Exception as e:
        sys.exit("[ERROR] shengbte 需要 lattice_kappa/ase：%s" % e)
    atoms = ase_read(str(out / "POSCAR"), format="vasp")
    params = kc.read_kl_params(out / kc.KL_PARAMS)
    sc = [int(x) for x in (params.get("SUPERCELL") or "2 2 2").split()]
    C = {"kappa_mesh": [int(x) for x in mesh.split()],
         "kappa_t_min": conf["T_MIN"], "kappa_t_max": conf["T_MAX"],
         "kappa_t_step": conf["T_STEP"], "kappa_scalebroad": conf["SCALEBROAD"],
         "kappa_isotope": conf["ISOTOPE"], "kappa_convergence": True}
    lk._write_shengbte_control(C, atoms, sc, out / "CONTROL", use_nac)
    print("[OK] ShengBTE CONTROL 已写出")
    print("[WARN] 还需 FORCE_CONSTANTS_2ND/3RD（ShengBTE 格式）。findiff 的 compact fc3 "
          "无稳定导出口，请用 METHOD=alm + hiphive 导出，或改 SOLVER=phono3py。")


def main():
    cwd = Path.cwd()
    out = cwd / OUTDIR
    out.mkdir(exist_ok=True)
    conf = stepconf.load(SPEC, STEP)
    fcd = cwd / FC_DIR
    if not fcd.is_dir():
        sys.exit("[ERROR] 找不到 step5_fc")

    for f in ("fc2.hdf5", "fc3.hdf5", "phono3py_disp.yaml"):
        if not (fcd / f).is_file():
            sys.exit("[ERROR] %s 缺 %s（step5 力常数没建成）" % (fcd, f))
        shutil.copyfile(fcd / f, out / f)
    for f in ("BORN", "POSCAR", kc.KL_PARAMS):
        if (fcd / f).is_file():
            shutil.copyfile(fcd / f, out / f)
    use_nac = (out / "BORN").is_file()

    # 稳定性闸：step5 判过虚频才该到这
    ps = fcd / "phonon_summary.json"
    if ps.is_file():
        import json
        try:
            if not json.loads(ps.read_text()).get("stable", True):
                sys.exit("[ERROR] step5 判定声子谱有虚频（不稳定），热导率无物理意义，已中止。")
        except Exception:
            pass

    params = kc.read_kl_params(out / kc.KL_PARAMS)
    mesh = conf["MESH_OVERRIDE"] or params.get("MESH") or "20 20 20"
    ts = " ".join(str(t) for t in range(conf["T_MIN"], conf["T_MAX"] + 1, conf["T_STEP"]))
    solver = str(conf["SOLVER"]).lower()
    print("[..] 求解器=%s mesh=%s 温度=%s K NAC=%s" % (solver, mesh, ts, use_nac))

    here = Path(__file__).resolve().parent
    if solver == "phono3py":
        cmd = build_phono3py_cmd(mesh, ts, conf["ISOTOPE"], use_nac)
        tpl = kc.resolve_submit(here, "3d", "submit_p3py")   # 单节点，无 2D/3D 之分
        kc.write_submit(tpl, out / "submit.sh",
                        {"JOBNAME": kc.new_jobname(cwd, "S6kappa"), "P3PY_CMD": cmd})
    elif solver == "shengbte":
        write_shengbte_control(cwd, out, conf, mesh, use_nac)
        tpl = kc.resolve_submit(here, "3d", "submit_shengbte")
        kc.write_submit(tpl, out / "submit.sh",
                        {"JOBNAME": kc.new_jobname(cwd, "S6kappa"),
                         "SHENGBTE_EXE": conf["SHENGBTE_EXE"]})
    else:
        sys.exit("[ERROR] SOLVER 只允许 phono3py / shengbte")
    kc.apply_submit_overrides(out / "submit.sh", conf)
    print("[DONE] %s：submit.sh 就绪，提交后计算节点出 κ，写 kappa_summary.json(KAPPA_DONE)"
          % OUTDIR)


if __name__ == "__main__":
    main()
