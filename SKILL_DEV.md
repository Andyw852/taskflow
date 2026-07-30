# taskflow 技能开发规范（SKILL_DEV）

> 本文件是 taskflow 技能的**唯一契约**。照本文写出的技能目录，放进 `skill/` 即可被 `tf` 自动发现，**不需要修改 tf 主程序的任何一行**。
>
> 本文件可以整份喂给 AI 让它生成技能。文末第 11 节有现成的提示词模板。

---

## 1. 心智模型：谁负责什么

```
本地（你的机器）                          超算（登录节点 + 计算节点）
┌──────────────────────────┐             ┌──────────────────────────────┐
│ tf 主程序                 │             │                              │
│  · 读 skill.yaml 装配流水线 │  ssh 推送   │ 材料目录/                     │
│  · 决定「下一步该干什么」    │ ─────────► │   ├── POSCAR                 │
│  · 提交 / 取消 / 重跑       │            │   ├── gen_stepN_xxx.py       │
│  · 拉回结果                │            │   ├── dim_common.py, *.tpl   │
│                          │            │   └── stepN_xxx/             │
│ skill/<技能>/             │            │        ├── INCAR KPOINTS     │
│  ├ skill.yaml  ← 流水线声明 │            │        ├── POTCAR POSCAR     │
│  ├ gen_*.py    ← 造输入     │            │        ├── submit.sh         │
│  ├ checks.py   ← 判完成     │  ssh 执行   │        └── OUTCAR ...        │
│  └ *.tpl       ← INCAR/提交 │ ─────────► │                              │
└──────────────────────────┘             └──────────────────────────────┘
```

三件事必须分清：

| 角色 | 在哪跑 | 干什么 |
|---|---|---|
| `skill.yaml` | 本地被 tf 解析 | **声明**有哪些步骤、每步用哪个 gen 脚本、用什么判据判完成 |
| `gen_*.py` | 超算登录节点，cwd = **材料目录** | **造**出 `<步骤名>/` 目录及其中的 INCAR/KPOINTS/POTCAR/POSCAR/submit.sh |
| 判据（`check:`） | 超算登录节点，在 tf 下发的采集器里 | **判断**某个步骤目录算完没有、结果对不对 |

tf 自己**不懂任何物理**。它只会：建目录 → 推文件 → 跑 gen → sbatch → 按判据看状态 → 拉结果。所有 VASP 知识都在技能里。

---

## 2. 目录结构

### ⚠️ 硬规则：技能目录必须自包含

**一个技能运行所需的全部文件，必须都在它自己的目录里。**
不许引用别的技能目录，不许依赖任何公共目录（本项目**没有** `skill/_common/`）。
公共库（`dim_common.py`、`check_common.py`）和提交模板一律**各技能各存一份副本**——
这是刻意选择的 vendoring：技能之间完全隔离，改一个不会影响另一个，目录整个拷走就能用。

```
skill/<技能名>/
├── skill.yaml                 必需。技能清单
├── gen_step1_xxx.py           必需。每个计算步骤一个（也可一个脚本 --stage 复用）
├── gen_step2_xxx.py
├── checks.py                  可选。本技能私有的完成判据
├── dim_common.py              维度判定/模板解析库。用到就复制一份进来
├── check_common.py            步骤自检/重投库。用到就复制一份进来
├── step1_check_and_resubmit.py   每个计算步骤一个（agent 诊断用）
├── incar_2d.tpl / incar_3d.tpl        INCAR 模板
├── submit_std_2d.tpl / submit_std_3d.tpl   提交脚本模板（**逻辑名**，见 §6）
└── README.md                  可选。给人看的说明
```

技能名 = 目录名 = `-tt` 的短名（如 `tf -tt kl start`）。用小写字母、数字、连字符。

### 模板放哪：`template_layout`

模板文件（`*.tpl`）可以摊在技能根目录下（默认，向后兼容），也可以收进 `templates/`。
清单里用 `template_layout` 选：

**`shared`（缺省）——所有步骤共用一套模板**

```
skill/band/
├── skill.yaml            template_layout: shared
├── gen_step*.py          脚本仍平铺在根目录
├── dim_common.py
└── templates/
    ├── incar_2d.tpl  incar_3d.tpl
    └── submit_jzzn_vaspstd_2d.tpl  ...
```

**`per_step` ——每个步骤一个目录，只放该步骤要的模板**

```
skill/elastic/
├── skill.yaml            template_layout: per_step
├── gen_step*.py
├── dim_common.py
└── templates/
    ├── step1_std_opt/    incar_2d.tpl incar_3d.tpl submit_jzzn_vaspstd_{2d,3d}.tpl
    └── step2_elastic/    submit_jzzn_vaspstd_{2d,3d}.tpl
```

子目录名 = `steps[].name`，必须逐字相同。

查找顺序（都保留末尾的平铺兜底）：

| 布局 | 顺序 |
|---|---|
| `shared` | `templates/<文件>` → `<技能根>/<文件>` |
| `per_step` | `templates/<步骤名>/<文件>` → `templates/<文件>` → `<技能根>/<文件>` |

`per_step` 的中间一层是**公共回落**：真正所有步骤都一样的文件（`dim_common.py`、
某个通用 INCAR 底板）放 `templates/` 根或技能根目录，不用每个步骤目录复制一份。

`template_dir: 别的名字` 可改目录名，一般不用。

> ⚠️ `per_step` 布局下 `tf init` **不会**把模板复制进 `project_setting/` ——
> 那里一份会盖住所有步骤，破坏按步骤隔离。要按项目改某步的模板，
> 放 `材料/<技能>/` 下（优先级仍高于技能目录）。

只放**实际用得到**的文件：`elastic` 全程 `vasp_std`，就不放 `submit_ncl_*.tpl`；
纯 3D 技能不放 `incar_2d.tpl`。不用的模板放进来只会让 `tf init` 报无意义的警告。

### 步骤之间也要隔离

依赖清单**写在每个步骤上**（步骤级 `gen_need`），不要写在类型顶层——
每一步只推送自己真正需要的文件：

```yaml
steps:
  - {name: step1_std_opt, ...,
     gen_need: [dim_common.py, check_common.py, step1_check_and_resubmit.py,
                incar_2d.tpl, incar_3d.tpl, submit_std_2d.tpl, submit_std_3d.tpl]}
  - {name: step2_elastic, ...,
     gen_need: [dim_common.py, check_common.py, step2_check_and_resubmit.py,
                submit_std_2d.tpl, submit_std_3d.tpl]}   # 不需要 incar 模板
  - {name: step3_postprocess, ..., gen_need: []}          # 什么都不推
```

⚠️ **步骤级 `gen_need` 会完全替代类型级清单，并且跳过提交模板的自动补推。**
所以每一步都必须把提交模板逻辑名（`submit_std_2d.tpl` 等）**列全**，
漏写时老材料靠远端残留文件掩盖，新材料（空目录）会直接报「找不到模板」。

---

## 3. `skill.yaml` 完整字段

```yaml
schema: 1                  # 必需。清单格式版本，当前固定 1
name: kl                   # 可选。类型 key，缺省 = 目录名
desc: 晶格热导率            # 必需。状态表和帮助里显示的中文名
version: "0.1"             # 可选。技能自身版本，tf skills 会显示
enabled: true              # 可选。false = 不装载（默认 true）

defaults:                  # 可选。站点相关缺省值，用户在 tf.yaml 里覆盖
  hpc: jzzn                #   默认集群（对应 setting/<name>.yaml）
  skill_subdir: true       #   true = 材料目录下建 <技能名>/ 子目录（新技能一律 true）
  # work_dir: ...          #   一般不写，让用户在 tf.yaml 里配

gen_need: [...]            # 可选。类型级依赖文件（gen 前推到材料目录，已存在按 md5 比对）
aux_files: [...]           # 可选。辅助脚本（同上，只补不覆盖）

steps:                     # 必需。顺序即流水线顺序
  - {seq: 1, name: step1_relax, label: S1_opt, check: outcar_relax,
     gen: "lattice_kappa.py --stage relax", contcar_to_poscar: true}

optional_steps:            # 可选。可开关的步骤组，见 §7
  plot_steps:
    default: true
    steps: [...]

checks: checks.py          # 可选。私有判据文件名（缺省就找 checks.py）
requires:                  # 可选。人读为主
  python: [numpy, phonopy]
  exe: [ShengBTE]
```

### `steps[]` 每一条的字段

| 字段 | 必需 | 说明 |
|---|---|---|
| `name` | ✅ | **步骤目录名**，必须和 gen 脚本实际创建的目录**一模一样** |
| `label` | ✅ | 状态表列头，≤ 10 字符，形如 `S2_static` |
| `seq` | 推荐 | `run_steps` / `-j` 用的序号。多段合并成一步（如三段弛豫）就共用同一个 seq；画图步用小数 `3.1` |
| `check` | ✅ | 完成判据名，见 §5 |
| `gen` | ✅ | gen 脚本名，可带参数：`"gen_x.py --stage a"`。可用占位符 `{mat} {matdir} {root} {step} {tt}` |
| `gen_need` | | **步骤级**依赖清单。写了就**完全替代**类型级 `gen_need`+`aux_files`，并跳过提交模板自动补推 |
| `run` | | `gen` = 只在登录节点跑 gen 脚本、**不提交 SLURM**（后处理/画图步用） |
| `group` | | 多个步骤在状态表合并成一列（如三段弛豫都写 `group: S1_relax`） |
| `contcar_to_poscar` | | `true` = `retry` 续跑前先把 CONTCAR 盖回 POSCAR（弛豫步用） |
| `submit` | | 提交脚本文件名，缺省 `submit.sh`（tf 也会兜底找 `sub.sh/job.sh/run.sh/sub.slurm`） |
| `fanout` | | 扇出步骤：步骤目录下每个匹配子目录是一个独立作业，见 §7.5。值是 glob，如 `"deform-*"` |
| `fetch_all` | | `true` = 完成后整目录拉回本地 `result/`（画图/后处理步用） |
| `marker` / `done_marker` / `phrase` / `pressure_tol` / `stage` / … | | 判据参数，见 §5 |
| 任意自定义键 | | **会原样传给判据函数的 `sc`**，这是自定义判据取参数的方式 |

> ⚠️ `name` 必须和 gen 脚本里写的目录常量一致。这是 90% 的「步骤永远 PREP」问题的根因。

---

## 4. 状态语义

tf 对每个步骤只有这几种状态，由「目录存不存在 / squeue 里有没有作业 / 判据过没过」三者决定：

| 状态 | 含义 | 触发条件 |
|---|---|---|
| `PREP` | 输入未生成 | 步骤目录不存在 |
| `TODO` | 已生成待提交 | 目录在、没作业、判据不过 |
| `R` / `PD` | 运行中 / 排队 | squeue 里该目录有作业 |
| `OK` | 完成 | 判据返回 `True` |
| `FAIL` | 算完了但判据不过 | 无作业 + 判据 `False`，`diag` 给原因 |
| `WAIT` | 被前序步骤阻塞 | 前一步没 OK |

所以**判据的质量决定整个流水线好不好用**。判据返回的第二个值（诊断文本）会直接显示给人和 agent 看，要写成可行动的句子（"力已收敛但压强 12.3 kB > 5 kB → cp CONTCAR POSCAR 再跑一轮"），不要只写 "failed"。

---

## 5. 内置判据（`check:` 可选值）

| 判据 | 判定逻辑 | 可调参数（写在该 step 里） |
|---|---|---|
| `outcar` | OUTCAR 尾部含 `General timing and accounting informations` | — |
| `outcar_relax` | 上面 + 含 `reached required accuracy` + 末次 `external pressure` 绝对值 ≤ 阈值；不过时附弛豫空转诊断 | `phrase`（默认 `reached required accuracy`）、`pressure_tol`（默认 5.0 kB） |
| `relax_skip` | 收敛感知的多段弛豫判据：a 收敛则 b/c 自动跳过，c 是总闸 | `stage`（`a`/`b`/`c`）、`relax_diag` |
| `wavecar` | WAVECAR 存在且 ≥ 阈值 | `wavecar_min`（默认 1 MB） |
| `eigenval` | EIGENVAL 存在；有 KPOINTS_OPT 时还要有 vasprun.xml | — |
| `marker` | **通用判据**：`marker: "文件名:要找的字符串"` | `marker`（必填） |
| `plot` | `done_marker` 指定的文件存在，或目录里有任意 `.png` | `done_marker` |

**先用 `marker`**。绝大多数「某文件里出现某行就算完」的需求都不用写代码：

```yaml
- {name: step2_elastic, check: marker, marker: "OUTCAR:TOTAL ELASTIC MODULI", ...}
- {name: step3_fc2,     check: marker, marker: "FORCE_CONSTANTS_2ND:",         ...}
```

`marker` 不够用（要读数值、要比较、要跨文件）才写 `checks.py`。

### 弛豫空转诊断 `relax_diag`

`outcar_relax` / `relax_skip` 未收敛时会读 OSZICAR 给判定：`progressing`（正常下降）/ `oscillating`（末段振荡）/ `thrown`（线搜索甩飞）/ `electronic`（撞 NELM）/ `stalled`（停滞）/ `nsw`（步数用完）。默认参数 `{window: 8, osc_tol: 5e-3, stall_tol: 1e-4, jump_tol: 0.5, min_steps: 6}`，某步想改就写 `relax_diag: {window: 10, osc_tol: 0.003}`。

---

## 6. `gen_*.py` 契约

**运行环境**：超算登录节点，`cwd = 材料目录`，命令是 `python <脚本名> <你在 gen: 里写的参数>`。

**必须做的事**：

1. 创建 `<步骤名>/` 目录（名字必须等于 `skill.yaml` 里的 `name`）。
2. 在其中生成 VASP 输入：`POSCAR`（从上一步 CONTCAR 接力）、`INCAR`、`KPOINTS`、`POTCAR`、`submit.sh`。
3. 出错就 `sys.exit("[ERROR] ...")`，非零退出码 → tf 报 gen 失败并把 stderr 原样呈给用户。
4. 结构接力要**显式**：前一步的 CONTCAR 不存在就报错退出，**绝不能拿旧结构默默往下算**。

**可以依赖的东西**（tf 会自动推到材料目录）：

- `gen_need` / `aux_files` 里列的所有文件，与 gen 脚本同目录（`Path(__file__).parent`）
- `dim_common.py` 常用 API：
  - `resolve_dim(method_file, struct_path)` → `"2d"` / `"3d"`（按真空层厚度判定，阈值 8 Å）
  - `resolve_tpl(base_dir, "submit_std", dim)` → 按维度选 `submit_std_2d.tpl` / `submit_std_3d.tpl`，找不到回退无后缀旧名
  - `validate_poscar(path)`、`force_kz1(kpoints_path)`、`filter_kpath_2d(...)`

**模板逻辑名机制**（换超算不用改技能）：技能里只写**逻辑名** `submit_std_2d.tpl`、`submit_std_3d.tpl`、`submit_ncl_2d.tpl`、`submit_ncl_3d.tpl`；实际文件名由 `setting/<集群>.yaml` 的 `template_map` 映射（如 `submit_std_3d.tpl → submit_jzzn_vaspstd_3d.tpl`）。tf 推送时按逻辑名落地，gen 脚本按逻辑名读。模板里的 `{{JOBNAME}}` 由 gen 脚本替换。

**`run: gen` 的步骤**（后处理/画图）：同样在登录节点跑，但 tf **不提交 SLURM**，跑完就按 `check: plot` + `done_marker` 判完成。所以这类脚本要自己算完并写出产物文件，且不能太重（登录节点跑得动）。

---

## 7. 可选步骤组 `optional_steps`

用来表达「这几步默认加上，但可以一键关掉」（能带画图就是这么来的）：

```yaml
optional_steps:
  plot_steps:                    # 键名 = 开关名，用户写 plot_steps: false 关闭
    default: true
    steps:
      - {seq: 3.1, name: step3_band_plot, label: S3.1_plot,
         after: step3_PBE,       # 锚点：插在名字以此开头的最后一个步骤之后
         gen: "gen_step3.1_plot_band.py", check: plot, run: gen,
         gen_need: [], done_marker: band_summary.json, fetch_all: true}
```

- `after` 是**步骤名前缀**。锚点在本技能里不存在 → 该条自动不注入（不会报错）。
- 一个技能可以有多个开关组，键名自取。
- 用户在 `tf.yaml` 或项目 `tf_<项目>.yaml` 里写 `<开关名>: false` 即关闭。

`run_steps` 是另一个正交机制（用户侧）：`run_steps: [1, 2, 3.1]` 只跑列出的步骤，元素匹配 `seq`、`name` 或 `label`。**所以每个步骤都写 `seq` 很重要**，否则用户只能敲全名。

---

## 7.5 扇出步骤 `fanout`：一步下面 N 个并行作业

有些计算天然是「同一步骤、N 份独立输入、各跑各的」——形变势的 13 个应变、
phono3py 的 N 个位移。tf 默认「一步 = 一个目录 = 一次 sbatch」，这类步骤用
`fanout` 声明：

```yaml
- {seq: 7, name: step7_deform, label: S7_deform, check: outcar,
   fanout: "deform-*",              # glob，相对步骤目录
   gen: gen_step7_deform.py, fetch_all: true}
```

gen 脚本负责在步骤目录下造出这些子目录，**每个子目录一份完整输入 + 自己的
`submit.sh`**：

```
step7_deform/
├── deform-01/   POSCAR INCAR KPOINTS POTCAR submit.sh
├── deform-02/   ...
└── deform-12/   ...
```

之后 tf 全自动：

| 操作 | 行为 |
|---|---|
| `start` | 每个匹配子目录各 `sbatch` 一次，作业名自动加子目录后缀 |
| 状态 | 全部子目录判据都过才算 `done`；跑的时候显示 `3/5 2R 0PD` |
| 失败 | 任一子目录没过 → 整步 `error`，诊断列出是哪几个：`3/5 完成；未完成 deform-04,deform-05` |
| `retry` | **只补没完成的那些**，已算好的不动 |
| `stop` | scancel 该步骤的全部作业 |
| `rerun` | 删掉整个步骤目录（含所有子目录）重来 |

判据（`check:`）作用在**每个子目录**上，不是步骤目录。所以 `check: outcar`
的含义是「每个子目录的 OUTCAR 都要完整」。

注意事项：

- 子目录名要能被 glob 稳定匹配，且不要和别的东西撞（`deform-*` 而不是 `*`）
- gen 脚本要**幂等**：重跑时已有子目录不要清空已算好的结果
- `fetch_all: true` 会把整个步骤目录（含全部子目录）拉回本地，形变势这类
  产物多的步骤建议改用 `fetch_files` 只拉汇总产物

## 8. `checks.py` 判据插件契约

只有在 `marker` 判据不够用时才写。**这是整套机制里约束最强的地方，务必逐条遵守**：

```python
# -*- coding: utf-8 -*-
"""skill/<技能>/checks.py"""

def ck_kappa_conv(d, sc):
    """d  = 该步骤在超算上的绝对目录
       sc = 该步骤的配置字典（skill.yaml 里同一条 step 的所有键都在这）
       返回 (是否完成: bool, 诊断文本: str)"""
    p = os.path.join(d, "BTE.KappaTensorVsT_CONV")
    if not os.path.isfile(p):
        return False, "BTE.KappaTensorVsT_CONV missing"
    rows = [ln.split() for ln in tail_text(p, 200000).splitlines() if ln.strip()]
    if not rows:
        return False, "结果文件为空"
    last = [float(x) for x in rows[-1]]
    return True, "kappa@%.0fK = %.2f W/mK" % (last[0], last[1])


CHECKERS = {"kappa_conv": ck_kappa_conv}    # ← 必须有这一行
```

**硬约束**：

1. 这个文件的源码会被 tf 读出来、base64 塞进采集器、在**超算登录节点 `exec` 执行**。
2. **只能用标准库**。不能 `import numpy`、不能 `import pymatgen`。
3. **不能有顶层副作用**：除了 `def` 和 `CHECKERS = {...}`，不要有 print、文件读写、`import` 之外的语句。
4. **不要写 `import os` 等**——采集器已经在全局命名空间提供了：
   `os` `re` `json` `glob` `subprocess`，以及
   `tail_text(path, nbytes=1000000)`（读文件尾部）、
   `read_oszicar_ionic(d)`（OSZICAR 离子步能量）、
   `relax_diagnose(d, cfg)`（弛豫空转诊断）。
   直接用即可；写了 `import os` 也不报错，但没必要。
5. **判据要能在 1 秒内返回**。它对每个材料的每个步骤都要跑一遍，不能扫全文件、不能起子进程算东西。
6. **判据名不能和内置判据重名**（`outcar`/`marker`/`plot`/…），重名 tf 会直接报错退出。
7. 判据参数从 `sc` 取（`sc.get("kappa_rtol", 0.01)`），参数写在 `skill.yaml` 那条 step 上，tf 会自动透传到远端。

---

## 9. 用户侧配置（技能作者要知道的）

技能装好后，用户在全局 `tf.yaml` 里只需要：

```yaml
task_types:
  kl:
    work_dir: /public/home/xxx/work     # 超算工作根，这个必须用户配
    # hpc: tianhe                       # 覆盖清单里的默认集群
    # plot_steps: false                 # 关掉可选步骤组
    # run_steps: [1, 2]                 # 只跑部分步骤
```

**不要在技能清单里写 `work_dir` 的具体路径**，那是站点信息，留给用户。

---

## 10. 自检清单

写完一个技能，按顺序过这几关：

```bash
# 1. 清单能被解析、技能能被发现
tf skills
#    应看到你的技能，版本、步骤数、清单路径都对

# 2. 步骤表能正确展开（含 optional_steps）
tf -tt <技能名>
#    列头 = 你的 label，顺序 = 你的 steps 顺序

# 3. 挂到一个测试材料上（纯本地，不连超算）
cd <含 POSCAR 的材料的上级目录>
tf -tt <技能名> init

# 4. 只生成第一步输入、不提交，人工检查 INCAR/KPOINTS/POTCAR
tf -tt <技能名> -p <材料> -j 1 init
tf -tt <技能名> -p <材料> dir     # 拿到远端路径，ssh 过去看

# 5. 真跑
tf -tt <技能名> -p <材料> start
```

逐条对照：

- [ ] **目录自包含**：`gen_need` / `aux_files` 里列的每个文件都实实在在躺在本技能目录下，
      没有一个是靠别的技能目录或公共目录提供的（`ls skill/<技能名>/` 逐条对照清单）
- [ ] **依赖清单写在步骤级**，每一步都列全了提交模板逻辑名
- [ ] `skill.yaml` 的 `schema: 1`、`name`、`desc`、`steps` 齐全
- [ ] 每个 `steps[].name` 与 gen 脚本创建的目录名**逐字相同**
- [ ] 每个步骤有 `seq`、`label`（≤10 字符）、`check`、`gen`
- [ ] 判据优先用内置的；`marker` 的 `文件名:字符串` 确认在真实 OUTCAR 里出现过
- [ ] gen 脚本：cwd 是材料目录、结构接力找不到就报错退出、非零退出码有意义
- [ ] 提交模板只写逻辑名 `submit_std_2d.tpl` 等，不写 `submit_jzzn_*`
- [ ] 后处理/画图步写了 `run: gen` + `check: plot` + `done_marker` + `fetch_all: true`
- [ ] 扇出步骤：gen 脚本造的子目录名与 `fanout` 的 glob 对得上，每个子目录都有自己的 `submit.sh`
- [ ] 新技能 `defaults.skill_subdir: true`
- [ ] 若有 `checks.py`：只用标准库、无顶层副作用、判据名不与内置重名、秒级返回
- [ ] `tf skills` 里没有关于你这个技能的警告

---

## 11. 喂给 AI 的提示词模板

把本文件整份贴进去，然后追加：

```
上面是 taskflow 的技能开发规范。请按它生成一个新技能，要求如下：

【技能名】     <目录名，如 dielectric>
【中文描述】   <如 DFPT 介电常数计算>
【物理流程】   
  1. <第一步做什么，用什么 INCAR 关键字，判完成看什么>
  2. <第二步…>
  3. <…>
【已有素材】   
  - <贴出你已有的脚本 / INCAR 模板 / 参考的 skill/band 里的哪些文件>
【集群】       jzzn，提交模板逻辑名用 submit_std_2d.tpl / submit_std_3d.tpl
【维度】       需要 / 不需要 2D-3D 自动判定（需要就复用 dim_common.py）

请输出：
  1. skill/<技能名>/skill.yaml         —— 完整清单，每步都要有 seq/label/check/gen
  2. skill/<技能名>/gen_step*.py       —— 每个计算步骤一个，遵守 §6 契约
  3. skill/<技能名>/checks.py          —— 仅当内置判据（尤其 marker）不够用时才写，
                                         写了必须遵守 §8 的全部硬约束
  4. 一份 §10 自检清单的逐条核对结果

约束：
  - 不要修改 tf 主程序，不要要求我改 tf.yaml 里除 work_dir 以外的东西
  - **技能目录必须自包含**：不许引用 skill/ 下其它技能的文件，不许假设存在任何
    公共目录。需要 dim_common.py / check_common.py / 提交模板的话，明确告诉我
    「从 skill/band/ 复制哪几个文件到本技能目录」，不要写成跨目录引用
  - **依赖清单写在步骤级 gen_need**，不要写类型级；每一步都要列全提交模板逻辑名
  - 判据能用 marker 就用 marker，不要为了「显得完整」去写 checks.py
  - skill.yaml 里不要写具体的 work_dir 路径
  - defaults 里写 skill_subdir: true
  - gen 脚本不得在上一步 CONTCAR 缺失时静默使用旧结构
```

---

## 12. 常见坑

| 现象 | 原因 |
|---|---|
| 步骤永远 `PREP` | `steps[].name` ≠ gen 脚本创建的目录名 |
| 步骤永远 `FAIL` | 判据字符串在真实输出里根本不出现；先 `grep` 一遍真 OUTCAR 再写 `marker` |
| 新材料报「找不到模板」 | 只写了 `gen_need` 没包含提交模板逻辑名；类型级 `gen_need` 会自动补推四个逻辑名，但**步骤级 `gen_need` 会完全替代类型级并跳过自动补推**，得自己列全 |
| `tf skills` 里技能不出现 | 清单没有 `steps`、`enabled: false`、或被 `tf.yaml` 的 `disabled_skills` 关掉了；带 `-v` 看警告 |
| 自定义判据在本地测好好的，远端报错 | 用了非标准库，或有顶层副作用 |
| 判据拿不到参数 | 参数写在了错误的层级——必须写在 `steps[]` 的那一条里 |
| 状态表列宽爆炸 | `label` 太长，或没用 `group` 合并多段步骤 |
| 改了技能脚本远端没生效 | gen 脚本每次覆盖推送（本地改即生效）；但 `gen_need` 依赖文件按 md5 比对，改了内容会推，只改文件名不会 |
