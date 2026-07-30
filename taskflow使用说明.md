# taskflow (tf) 使用说明

**当前版本 1.0**（版本号自 1.0 起重新计数，与 `tf -V` 一致；文中不再逐条标注历史版本号）。

VASP 多材料·多步骤·**多任务类型**流水线管理框架（SLURM）。单文件 Python，**零第三方依赖**（内置迷你 YAML 解析器，装了 PyYAML 会优先用），超算端零安装、零状态文件。

## 安装

推荐版本化布局（详见"目录结构与版本管理"一节）：

```bash
mkdir -p ~/taskflow/versions/v1.0 ~/.local/bin
cp tf ~/taskflow/versions/v1.0/tf && chmod +x ~/taskflow/versions/v1.0/tf
cp tf.example.yaml ~/taskflow/tf.yaml
ln -sf ~/taskflow/versions/v1.0/tf ~/.local/bin/tf
tf --version
```

## 核心概念

- **任务类型（tt）**：一类计算 = 一套步骤流水线 = 一个技能。当前配置：能带 `band`、弹性常数 `elastic`；自定义新类型只需在配置 `task_types:` 下加一段。步骤数量不限。
- **project（-p）**：材料项目，如 `C20/qHPC20`。
- **job（-j）**：项目里的一个步骤，可写步骤全名 / label / 序号，**必须配 -p**。序号是**逻辑步骤号**：1=弛豫（三段式时指首段 step1a，b/c 段用 label 如 `S1b_cell`）、2=静态、3=WAVECAR、4=HSE。
- **命名规则**：同一类型下项目名不允许重复（启动即报错）；不同类型下允许同名（`C20/qHPC20` 可以同时跑 band 和 elastic）。`-p` 不带 `-tt` 时跨类型解析，唯一即用，重名会提示补 `-tt`。
- **本地模式（v3）**：输入文件（POSCAR 等）以本地项目目录为准，超算只做计算服务，目录树 = `work_dir + 项目相对路径`。类型配置写 `local_root` 即启用；只写 `root` 则是 v2 远端模式，两者可混用。

## 命令

```
tf [ROOT]                        状态总表（全部类型，带 tt 列）
tf -tt band                      只看某类型
tf -tt band -p MAT status        单材料详情
tf [-tt TT] [-p MAT] start       开始：输入没生成先 gen 再提交；无 -p = 推进全部
tf [-tt TT] [-p MAT] stop        取消作业。取消的步骤打 scancel 标记
                                  （本地材料目录 .tf_scancel.json）：状态列显示
                                  scancel，auto_advance 和批量 start 都不会再动它。
                                  显式重跑：-p MAT start（保留文件直接重交）/retry/rerun，
                                  或跨材料 -status scancel start（retry/rerun）；
                                  重交成功/rerun/clean 后标记自动清除，
                                  步骤出现新作业或已完成时标记也会自愈
tf [-tt TT] [-p MAT] retry       用现有输入文件重交（在超算手改 INCAR/KPOINTS 后用它，
                                  tf 不动超算上的文件，直接 sbatch 提交）
tf -p A B retry                  同时操作多个项目（也支持 -p A,B 逗号分隔；
                                  start/stop/rerun/clean/status/dir/fetch 同样适用）
tf [-tt TT] [-p MAT] rerun       删除旧的生成文件 → gen 重新生成 → 提交
tf -j STEP rerun                 跨材料只重做该步骤（gen 脚本改动后一键修复全部材料；
                                  自动跳过 done 的和前序未完成的，加 -f 可强制）
tf -j STEP start/stop/retry/clean  同理：-j 不带 -p = 对全部材料只操作该步骤
tf -x A,B ...                    任何命令加 -x 跳过指定项目（逗号分隔，全名或 basename）
tf -status ST ...                只保留含指定状态步骤的材料，对任意命令生效：
                                  tf -status scancel          只看被 stop 取消的
                                  tf -status scancel start    把它们全部重跑（保留文件重交）
                                  tf -status error retry      重交全部失败步骤
                                  状态词 done/running/pd/error/waiting/scancel，逗号分隔
tf [-p MAT] [-j STEP] clean       只删不建回到 PREP：无 -p=全部材料（本地+超算只留 POSCAR）；
                                  -p C20=该体系全部材料；-p -j=单个步骤目录。
                                  多技能：-tt elastic clean 只清 elastic 的产物并从项目配置
                                  移除 elastic 段（band 段和配置目录保留；
                                  本技能是最后一个段才整目录删 project_setting）
tf -tt TT dir                    输出类型根目录路径
tf -p MAT [-j STEP] dir          输出材料/步骤在超算上的目录路径（只输出路径，便于拼接命令）
tf [-p MAT] fetch                手动强制拉回结果（status 时已自动保存完成的步骤到 result/，
                                  项目 setting.yaml 里 auto_fetch: false 可关闭）。
                                  按 result/<step>/.tf_fetched 戳记判"已抓取"，
                                  不再每次重拉；步骤重提交后自动清戳重拉，
                                  tf fetch 手动拉不受戳记限制（结果不完整时就用它强制重拉）
tf -p A,B hpc 集群名              指定项目跑哪台超算：材料级写 project_setting/hpc.yaml；
tf -tt TT -p A,B hpc 集群名        技能级写 材料/<技能>/hpc.yaml（只改该技能，优先级最高）。
                                  必须搭配 -p，只动指定项目、老项目不变；只影响之后提交的作业

自动化开关（写在全局 tf.yaml 顶层）：
  auto_advance: true             status 查看时自动提交可开始的步骤（gen+提交一条龙，
                                  流水线算完自动接下一步；error 不自动重试，留给人/agent 判断；
                                  项目 setting.yaml 里 auto_advance: false 可单独关闭；
                                  可用 tf auto on/off 一键切换，不用手编辑）
tf init                          批量初始化：当前目录下所有项目生成 project_setting/
tf -p MAT init                   只初始化该项目（如 -p C20/qHPC20 → C20/project_setting）
tf -p MAT -j STEP init           只生成该步骤输入文件（gen），不提交——提交前可先检查
tf watch [-i 秒]                 监控模式（前台）：每 interval 秒（默认 300）自动
                                  重新采集 → auto-fetch → auto-advance；
                                  状态有变化才打印总表，否则一行心跳；Ctrl+C 退出。
                                  每轮自动检测配置文件改动并重载
                                  （tf.yaml、project_setting/*.yaml、材料/技能的
                                  hpc.yaml）——改配置或换 tf 版本后不用重启监控；
                                  新配置有误时警告并沿用旧配置，修好下轮自动再试
tf watch -d                      后台监控（推荐）：不占终端，日志/pid 固定在
                                  tf.yaml 所在目录（.tf_watch.log，tail -f 查看）；
                                  tf watch --stop 任意目录可停止
tf watch --install / --uninstall crontab 保活：每 10 分钟检查，监控死了自动
                                  拉起（重启/WSL 关闭后自动恢复），不会重复启动
tf json / tf config              JSON 输出 / 打印示例配置
```

**零输入全自动（推荐配置）**：tf.yaml 里写 `auto_advance: true` + `auto_watch: true`，再执行一次 `tf watch --install`——之后**不需要敲任何命令、不需要手动挂监控**：监控死了任何 tf 命令顺带拉起（auto_watch），重启/WSL 关闭后 crontab 保活拉起（--install）。想彻底关掉后台监控：`auto_watch: false` + `tf watch --stop` + `tf watch --uninstall`。WSL 注意：保活依赖 WSL 里的 cron 服务在跑（`sudo service cron start`；wsl.conf 开 systemd 则自动）。Windows 侧更稳的替代：任务计划程序加"登录时运行" `wsl -e bash -lc "tf watch -d"`。

状态总表每个项目**两行**：第一行是各步骤状态词，第二行是 job 实况（已去掉总体 Status 列）。

- 状态词：`done` 完成 / `running` 运行中 / `pd` 排队 / `error` 未通过判据 / `waiting` 未开始（输入未生成、就绪待交、被前序阻塞都算）/ `scancel` 被 tf stop 取消（打标记，auto 不会重跑，显式重跑后自动清除）
- 第二行：running → `节点 任务号 已跑时长`（如 `cu41 3569183 0:42:11`）；pd → `任务号 (原因)`；scancel → `已取消(原任务号)`；其余 `-`
- `hpc` 列 = 该项目使用的超算；`dim` 列 = 2D/3D 判定

选项：`-tt` 类型、`-p` 材料（完整名 `C20/qHPC20` 或唯一 basename `qHPC20`；多个用逗号分隔或空格跟在后面）、`-j`/`-job` 步骤（全名/label/序号；配 `-p` = 该材料的该步骤，start/stop/retry/rerun/clean 可不带 `-p` = 全部材料只操作该步骤）、`-x` 跳过指定项目、` -status` 按步骤状态过滤材料、`-c` 配置、`--host`、`-u` squeue 用户、`-f` 强制（先取消再交）、`-y` 免确认。帮助：`tf -h` 或 `tf help`（含常用示例）。

SLURM 作业名：提交时统一改为 `材料-任务类型-步骤label`（如 `qHPC20-band-S1a_ion`），覆盖 submit.sh 里原有的 `--job-name`/`-J`，squeue 里一眼对应项目。

新增材料：把带 POSCAR 的目录放进项目根（如 `C20/qHPC20new/`），`tf` 状态表末尾会提示"发现新材料目录未初始化"；`tf init` 是增量的——只给新材料生成 `project_setting/`，已初始化的自动跳过。init 后 `tf start` 开始；配了 `auto_advance: true` 则下次 `tf` 自动开算。

## 状态符号

`OK` 完成 · `R@cu12` 运行中（@后节点列表） · `PD(QOSMaxJobsPerUserLimit)` 排队（括号内原因） · `FAIL` 未通过判据（附诊断） · `TODO` 输入就绪 · `PREP` 输入未生成 · `----` 被前一步阻塞

## 配置：全局 tf.yaml + 项目配置 tf_\<项目名\>.yaml

**配置跟着项目走**。全局 `~/taskflow/tf.yaml` 只登记项目根和公共骨架；每个项目自带一份配置，放在自己的 `project_setting/` 下：

```yaml
# ~/taskflow/tf.yaml（全局，几乎不用改）
host: jzzn                 # 默认 ssh 别名（项目 hpc.yaml 可覆盖）
project_roots:             # 项目根列表：扫描其下 project_setting/tf_*.yaml（含一层子目录）
  - /home/wangchao/Fullerene_Network
task_types:                # 公共骨架（可选）：项目配置同 key 类型自动继承缺省字段
  band:
    desc: 能带计算
    work_dir: /public/home/wangchao/Fullerene_Network/fullerene_network/test
    skill_dir: skill/band
    hpc: jzzn
    gen_need: [incar.tpl, submit_std.tpl]
    steps:
      - {name: step1a_PBE_opt, label: S1a_ion, stage: a, check: relax_skip,
         group: S1_relax, gen: "gen_step1_PBE_opt.py --stage a", contcar_to_poscar: true}
      - {name: step1b_PBE_opt, label: S1b_cell, stage: b, check: relax_skip,
         group: S1_relax, gen: "gen_step1_PBE_opt.py --stage b", contcar_to_poscar: true}
      - {name: step1c_PBE_opt, label: S1c_fine, stage: c, check: relax_skip,
         group: S1_relax, gen: "gen_step1_PBE_opt.py --stage c", contcar_to_poscar: true}
      - ...
```

```yaml
# ~/Fullerene_Network/C20/project_setting/tf_C20.yaml（项目配置，tf -p qHPC20 init 生成）
task_types:
  band:
    work_dir: /public/home/wangchao/...   # 只写与全局不同的字段，其余自动继承
```

项目配置规则：

- **命名**：`tf_<项目名>.yaml`（如 `tf_C20.yaml`、`tf_Fullerenebd.yaml`），**全局唯一，禁止重复**——两个项目放同名文件会直接报错并列出两个路径。
- **local_root 推荐写 `".."`**（= 体系根，如 Fullerene_Network）：材料名带 `C20/` 前缀，超算目录 = `work_dir/C20/qHPC20`，与本地目录树一致。缺省 = project_setting 父目录（材料名 `qHPC20`，超算 = `work_dir/qHPC20`）。多个项目配置都写 `".."` 时同名材料自动归属各自 project_setting 的段，不会重复。
- **字段继承**：没写的字段（steps/skill_dir/hpc/gen_need/work_dir）自动继承全局 tf.yaml 同 key 类型；写了就覆盖。
- **分段合并**：多个项目配置定义同一个类型 key（如都是 `band:`），= 该类型的多个分段，各自发现材料，表格里合并显示；同一类型内项目名仍不允许重复。
- **用了项目配置，全局就不要写 local_root**（否则全局段和项目段重复发现 → 重名报错）。
- 新增项目 = 在项目目录放好 POSCAR，跑 `tf init`（或 `tf init 项目名`），project_setting 就绪后立即可管理，不用动全局配置。
- 旧版远端模式仍支持：类型里只写 `root`（超算目录）不写 `local_root` 即可。

### 2D/3D 自动判定（skill/band 新版脚本）

- gen 脚本按 POSCAR 真空层自动判 2D/3D（阈值 8 Å），选 `incar_2d/3d.tpl`、`submit_std_2d/3d.tpl`、`submit_ncl_2d/3d.tpl`（`resolve_tpl` 回退无后缀旧名），判定结果写进步骤目录 `workflow_method.txt` 的 `DIM=`，后续步骤自动继承。
- 表格 **dim 列**显示判定结果（`-` = 尚未生成）；`tf -p X status` 详情也有 Dim 行。
- 类型配置对应改为：`gen_need: [dim_common.py, incar_2d.tpl, incar_3d.tpl, submit_std_2d.tpl, submit_std_3d.tpl, submit_ncl_2d.tpl, submit_ncl_3d.tpl]`；submit 逻辑名经 `hpc.yaml` 的 template_map 映射（默认 jzzn 四套：`submit_jzzn_vaspstd_2d/3d.tpl`、`submit_jzzn_vaspncl_2d/3d.tpl`）。
- **aux_files**（类型级，可选）：随生成一并推送到材料目录的辅助脚本，只补不覆盖。band 默认推 `check_common.py + stepN_check_and_resubmit.py`——这是给 agent 的深度诊断工具（`--check-only` 只读用，退出码 0=converged/10=not_converged/20=running/30=重启超限/40=error）；**重投一律用 tf retry/rerun**，不要让 agent 用它们真重投。
- 步骤目录名以 gen 脚本为准：`step1a/b/c_PBE_opt / step2_PBE_static / step3_PBE_WAVECAR / step4_HSE_band`（配置里的 `name` 必须一致；单段模式是 `step1_PBE_opt`）。

### 三段式弛豫

`gen_step1_PBE_opt.py` 的 `RELAX_STAGES = "auto"` 时，弛豫拆成三段，对应 tf.yaml 里三个步骤：

| 段 | 目录 | 作用 | INCAR 要点 |
|----|------|------|-----------|
| a | `step1a_PBE_opt` | 固定胞弛豫原子 | ISIF=2, IBRION=2, EDIFFG=-0.02, NSW=200（2D 无 IOPTCELL） |
| b | `step1b_PBE_opt` | 放开晶胞 CG | ISIF=3, IBRION=2, EDIFFG=-0.01, NSW=200 |
| c | `step1c_PBE_opt` | 准牛顿收尾 | ISIF=3, IBRION=1, EDIFFG=-0.001, NSW=100 |

- **结构接力由 gen 脚本完成**：a ← 材料 POSCAR，b ← `step1a/CONTCAR`，c ← `step1b/CONTCAR`；前一段 CONTCAR 不在会直接报错，不拿旧结构瞎跑。tf 按步骤顺序依次推进（a done → b → c），无需手动干预。
- **变段数（`check: relax_skip`）**：收敛感知判据——**a 收敛则 b/c 自动跳过，b 收敛则 c 跳过，优化好就进 step2**（step2 的 `STEP1_DIR="auto"` 自动找最后有 CONTCAR 的段）。a/b "跑过"即算 done（不收敛是常态，自然流转下一段）；c 是收敛总闸：跑了没收敛显示 **error** 并附空转诊断，retry 续跑即可。**旧单段 `step1_PBE_opt/` 已收敛的老材料三段全部自动跳过，不需要任何迁移操作。**
- **段间放行闸门（防空转）**：a/b 跑完未收敛时先体检轨迹（读 OSZICAR），**病态轨迹不放行下一段**——能量甩飞（thrown）、电子步撞 NELM（electronic）、大幅振荡（|dE| ≥ osc_tol）→ 本段直接 **error** 并附对策，tf retry 本段（自动 cp CONTCAR POSCAR 续跑）；小幅振荡/停滞/NSW 用尽但仍在下降 → 正常放行，下一段换算法自然收尾。带病结构不会一路震荡烧到 c 段。
- **S1_relax 合并列（`group: S1_relax`）**：三段在状态总表合并成一列总览（done/running/pd/error/waiting），第二行显示走到哪一段；各段明细看 `tf -p MAT status`。同 group 的任意步骤都能这样合并，`-j` 仍按原名/label 指具体段。
- **gen 字段可带参数**：`gen: "gen_step1_PBE_opt.py --stage a"`，脚本名后内容原样传给脚本。
- **step2 自动接结构**：`gen_step2_static.py` 的 `STEP1_DIR = "auto"` 按 c → b → a → 旧单目录顺序找最后一个有 CONTCAR 的，不用手动改。
- **想回单段**（`RELAX_STAGES = "single"`）：tf.yaml 的三条 step1a/b/c 换成一条 `- {name: step1_PBE_opt, label: S1_opt, check: outcar_relax, gen: gen_step1_PBE_opt.py, contcar_to_poscar: true}`。
- EDIFFG 逐段收紧（-0.02 → -0.01 → -0.001）：前两段不必死磕力，进入下一段吸引域即可；`retry` 某段时 `contcar_to_poscar` 会先 `cp CONTCAR POSCAR` 续跑（NSW 用尽显救）。

### 弛豫空转诊断

弛豫步未收敛时，状态不再只报 `force not converged`——tf 读 OSZICAR（每步几十字节，很便宜；必要时读 INCAR 拿 NSW/NELM）给出判定和对策：

- `progressing`：仍在正常下降（步数少时不下结论）
- `oscillating` 小幅：已在极小值附近 → 换 IBRION=1 收尾；大幅：两组自由度打架 → 先跑阶段 a 固定胞
- `thrown`：单步能量暴涨（CG 线搜索甩飞结构）→ 先跑阶段 a，或 POTIM 调 0.1
- `electronic`：电子循环撞 NELM，力不可信 → 调大 NELM 或放宽 EDIFF，别继续弛豫
- `stalled`：能量不动但力没到判据 → IBRION=1 收尾
- `nsw`：还在往下走但步数用完 → `cp CONTCAR POSCAR` 续跑（retry 自动做）

判据默认值（`RELAX_DIAG_DEFAULTS`）：window=8（看末几步）、osc_tol=5e-3 eV、stall_tol=1e-4 eV、jump_tol=0.5 eV、min_steps=6。某步骤要改判据，在该步骤配置里加 `relax_diag`：

```yaml
      - {name: step1c_PBE_opt, ..., relax_diag: {window: 10, osc_tol: 0.003}}
```

### project_setting/（就近优先）

本地模式下，从材料目录向上找最近的 `project_setting/`（如 `C20/project_setting` 对其下所有材料生效，`C20/qHPC20/project_setting` 可再覆盖单个材料）。用 `tf -p qHPC20 init` 生成，含：

- **setting.yaml**（路径与结果，占位符 `{matdir} {mat} {root}`）：
  ```yaml
  base_dir: "{matdir}"              # 项目基准目录
  result_dir: "{matdir}/result"     # fetch 拉回位置（result/<step>/）
  log_dir: "{matdir}/log"           # tf 操作日志 tf.log
  work_dir: /public/home/...        # 可覆盖类型的超算工作根
  fetch_files: [INCAR, POSCAR, POTCAR, KPOINTS, KPOINTS_OPT, kpath.json, submit.sh, OUTCAR, CONTCAR, EIGENVAL, vasprun.xml, queue.out]
  ```
  `fetch_files` 可扩展——不同体系要留的输出不同，往里加文件名即可。
- **hpc.yaml**（超算与模板映射）：
  ```yaml
  name: jzzn              # 表格 hpc 列显示名
  ssh_host: jzzn          # 实际 ssh 别名（换超算改这里）
  template_map:           # 逻辑名 → 实际模板文件（gen 需要的 submit_std.tpl 用谁满足）
    submit_std.tpl: submit_jzzn_vaspstd.tpl
    submit_ncl.tpl: submit_jzzn_vaspncl.tpl
  ```
  项目没有 hpc.yaml 时回退到 taskflow 包内 `setting/<hpc>.yaml`（默认 jzzn）。**换超算 = 改项目里这份 hpc.yaml**（如 `submit_hf_vaspstd.tpl`），不动 skill 里的通用脚本。

资源查找链（gen_need 的每个文件）：`project_setting/逻辑名` → `project_setting/映射名` → `skill/逻辑名` → `skill/映射名` → `gen_dir`（远端兜底）。推送到超算时文件名始终是逻辑名，gen 脚本不用改。

**check 判据**：`outcar_relax`（力收敛+压力，参数 `phrase`/`pressure_tol`）、`outcar`（正常结束）、`wavecar`（参数 `wavecar_min`）、`eigenval`、`marker`（参数 `marker: "文件:文本"`，如 `kappa.dat:END`）。

**gen**：单个 `.py` 文件名 → 材料根目录用 `python` 跑（缺文件自动从 `gen_dir` 复制）；带空格的完整命令 → 原样执行，支持占位符 `{mat} {matdir} {root} {step} {tt}`。

**gen_need**：gen 脚本需要的模板/依赖文件列表（如 `incar.tpl`、`submit_std.tpl`）。gen 运行前，tf 会把这些文件补齐到材料目录（已存在则跳过，不会覆盖你手改过的文件）；来源优先级：`skill_dir`（本地推送）> `gen_dir`（超算复制），都缺时报错。类型级和步骤级可混用（合并生效）。

**零配置**：不写 `task_types`，直接顶层 `root:`（+ 可选 `steps:`），或用 `tf /path` —— 单类型，tt 列显示 `-`。自动发现有 POSCAR 或有 INCAR 步骤子目录的目录。

### 能带画图步骤

step3/step4 算完后，tf 自动追加两个**画图步骤**：`S3.1_plot`（step3_band_plot/）和 `S4.1_plot`（step4_band_plot/）。

- **不提交 SLURM**：在材料目录直接运行 `gen_step3.1/4.1_plot_band.py`，生成 band.png、band.dat、band_summary.json 等
- **状态词与计算步骤不同**：`completed` / `not started` / `error`（无 running/pd）
- **前序守卫**：S3 done 才会跑 S3.1_plot，S4 done 才会跑 S4.1_plot；配 `auto_advance: true` 或挂 `tf watch -d` 可全自动
- **产物自动拉回**：整目录拉回本地 `result/stepN_band_plot/`（fetch_all）
- **失败重画**：`tf -p X -j S4.1_plot retry`（保留现目录）或 `rerun`（删了重画）

**开关**（默认开）：在 `tf_<项目名>.yaml` 的类型里写：

```yaml
task_types:
  band:
    plot_steps: false   # 关掉这两步；不写或 true = 开启
```

### 配置新特性（tf.yaml）

**位置**：`~/software/taskflow/tf.yaml` 或 `~/software/taskflow/setting/tf.yaml` 均可（当前目录 ./tf.yaml 优先级最高）。

**多 -j**：`tf -j S3.1_plot S4.1_plot start`（空格分隔）或 `-j A,B`（逗号），跨材料批量操作多个步骤。

**bd → band**：类型名改为 `band`。全局 tf.yaml 和项目里所有 `tf_*.yaml` 要同步，批量改：

```bash
sed -i 's/^  bd:/  band:/' ~/Fullerene_Network/*/*/project_setting/tf_*.yaml
```

改名后作业名变为 `材料-band-步骤`（如 qHPC20-band-S1a_ion）。**skill 目录也改名 `skill/band`，不再用缩写 bd**（本地 `mv ~/software/taskflow/skill/bd ~/software/taskflow/skill/band`，全局 tf.yaml 的 `skill_dir` 同步改成 `skill/band`；项目配置缺省继承全局，不用改）。

**hpc 内联**：`hpc:` 可以写成字典，把 `setting/jzzn.yaml` 的内容原样缩进粘贴进去，之后 jzzn.yaml 可删；写字符串则仍引用 setting/<名字>.yaml。

**run_steps 步骤子集**（类型配置，全局或项目级均可）：

```yaml
task_types:
  band:
    run_steps: [1]              # 只跑第 1 步（三段式弛豫时 = step1a/b/c 三段全含）
    # run_steps: [1, 2]         # 弛豫 + 静态
    # run_steps: [1, 2, 3, 3.1] # 弛豫、静态、WAVECAR + PBE 能带画图
    # run_steps: [S1a_ion]      # 只跑弛豫 a 段（单段用步骤名/label）
```

元素：序号 1/2/3/4（计算步骤；序号 1 覆盖 step1a/b/c）、3.1/4.1（画图步骤）、步骤名或 label。不写 = 全部步骤。项目级覆盖全局。

## 双技能（band + elastic）与新功能

### elastic 弹性常数技能

三步流水线（`skill/elastic/`）：

| 步骤 | label | 内容 | 完成判据 |
|---|---|---|---|
| step1_std_opt | S1_opt | 标准结构优化（pymatgen 标准化；2D 真空轴不在 c 时**自动 3-轮换到 c**（偶置换保持右手系，只改工作副本、项目 POSCAR 不动）；2D 自动面内约束 + `run_relax.sh` 两段弛豫；磁性/LMAXMIX/U 自动判定） | OUTCAR 收敛 |
| step2_elastic | S2_elastic | IBRION=6 / NFREE=4 有限形变（应力-应变法）；ISYM 自动：LDIPOL/LCALCPOL 体系强制 0，step1 显式设过则继承，否则补 2 | OUTCAR 含 `TOTAL ELASTIC MODULI` |
| step3_postprocess | S3_post | 登录节点本地后处理（不交 SLURM）：Cij 解析、Born 判据、2D→N/m 换算（C×L×0.1）、各向异性图 → `mechanical_properties.json` | done_marker 文件 |

部署：
1. `skill/elastic/` 整个目录放到 `~/software/taskflow/skill/` 下（与 `skill/band` 并列）；
2. 全局 tf.yaml 已带 `elastic:` 类型块——`work_dir` 与 band **同根**（技能子目录跟着项目走：`work/qHPC60/elastic/step1_std_opt/…`），一般不用改；
3. 给要算弹性的材料挂 elastic 段——在**本地材料目录**里执行（一键追加）：
   ```bash
   cd ~/Fullerene_Network/C20/qHPC20 && tf -tt elastic init
   # → 已追加 elastic 段 → project_setting/tf_qHPC20.yaml（字段全继承全局骨架）
   # → 已创建技能目录 elastic/（result/log 都在里面）
   ```
   已有 band 配置的项目会自动追加 `elastic:` 空段，原有内容不动；手工改也行（`task_types:` 下加一段 `elastic:`，和 `band:` 平级）。新材料直接 `tf -tt elastic -p <材料> init` 生成全套；
4. 超算登录节点需要 pymatgen（`pip install --user pymatgen`，2026 年起会自动带出核心包 pymatgen-core）与 matplotlib。Born 判据不稳定按"科学结果"处理：文件照出，状态显示 error 提醒人工看。

### 技能子目录 skill_subdir

类型配置 `skill_subdir: true` 后，该技能的计算放进材料目录下的技能子文件夹：

```
qHPC20/                          本地项目文件夹
├── POSCAR / project_setting/
├── band/                        band 技能（result/ 拉回的结果 + log/ 操作日志）
└── elastic/                     elastic 技能（同上）
超算 work/qHPC20/ 下同构：band/step1a_PBE_opt/…、elastic/step1_std_opt/…
——本地和超算都是"项目下面按技能分文件夹"，技能相关的东西都在对应文件夹里。
```

子目录名缺省 = 类型 key，可用 `dir_name: 名字` 改名。同一材料挂多个技能 = 项目配置里写多段（`band:` + `elastic:`），目录互不干扰。**elastic 默认已开**（新技能无历史）；**band 不要直接开**——现有平铺目录（`work/qHPC20/step1a_…`）会被当成新材料重算。用内置命令迁移：

```bash
tf -tt band migrate-subdir --dry-run   # 先看计划（哪些材料会迁、哪些跳过及原因）
tf -tt band migrate-subdir -y          # 执行：全部完成的材料自动迁
tf -tt band -p qHPC20 migrate-subdir   # 只迁指定材料（无在跑作业即可，不要求全完成）
```

命令做的事（每个材料）：超算上 `work/材料/step*` 整体 mv 进 `work/材料/band/`；本地 `result/`、`log/` mv 进 `材料/band/`；项目配置的 `band:` 段自动加 `skill_subdir: true`。迁完状态表随即按新路径采集，**仍是 done 不会重算**。有作业在跑的材料自动跳过（算完再迁）；体系级共享配置（多材料共用一个 project_setting）不会自动改，会提示手工加。之后 `tf -tt elastic init` 批量挂弹性即可。

### adopt 接管手工整理的目录

如果**人手工**把 POSCAR、project_setting、result、log 都搬进了 `材料/band/`（tf 的规矩是 POSCAR 和 project_setting 必须在材料根——所有技能共用；`band/` 里只放 band 的产物），不要用 migrate-subdir，用 adopt 一键接管：

```bash
tf auto off                      # 0. 先关自动提交（动目录期间防误提交）
tf -tt band adopt --dry-run      # 1. 先看计划
tf -tt band adopt -y             # 2. 执行接管
tf -tt band                      # 3. 核对：算好的 done，没算好的原样显示
tf auto on                       # 4. 恢复自动提交
```

adopt 做两件事：① 本地修正——`band/POSCAR`、`band/project_setting` 挪回材料根，根上残留的 `result`/`log` 挪进 `band/`；② 自动接着做 migrate-subdir——远端 `step*` 移进 `band/`、项目配置开 `skill_subdir`。有作业在跑的材料跳过（算完再跑一次 adopt 即可）；缺 project_setting 的会提示先 `tf init`。接管后 rerun/retry/start 全部照常可用（如 `tf -tt band -p qHPC20 -j S4_HSE rerun -y`）。

### 不同技能跑不同超算：技能私有 hpc.yaml

`project_setting/hpc.yaml` 是**材料级共享**的——同一个材料的 band、elastic 默认都用它。如果某个技能要单独跑另一台超算，把 hpc.yaml 复制进技能子目录再改即可：

```bash
cp C20/qHPC20/project_setting/hpc.yaml C20/qHPC20/elastic/hpc.yaml
# 然后编辑 elastic/hpc.yaml：ssh_host、template_map、队列/分区等
```

优先级（字段级覆盖，只写要改的字段就行，没写的字段自动继承下一级）：

- hpc 字段：`材料/<技能>/hpc.yaml` ＞ `project_setting/hpc.yaml` ＞ 段级 `hpc:`（内联 dict 或包内 `setting/<名>.yaml`）
- 模板/依赖文件：`材料/<技能>/` ＞ `project_setting/` ＞ `skill/<技能>/`（`template_map` 按映射级合并，技能私有的映射赢同名项）

状态表的 hpc 列会按技能显示各自的集群名。注意 `材料/<技能>/hpc.yaml` 只在 skill_subdir 开启时有意义；`tf init` 挂技能时会打印这条提示。

### 用命令指定项目跑哪台超算：tf hpc

上一节的复制-编辑两步合成一条命令，支持一次指定多个项目；**只动 `-p` 显式指定的项目，没指定的老项目一律不变**：

```bash
tf -p qHPC20,qHPC24 hpc tianhe           # 材料级：写 project_setting/hpc.yaml（该材料所有技能生效）
tf -tt elastic -p qHPC20 hpc tianhe      # 技能级：写 elastic/hpc.yaml（只改 elastic，优先级最高）
tf hpc tianhe                            # ✗ 报错：hpc 必须搭配 -p 显式指定项目
```

- `<集群名>` 对应包内 `setting/<名>.yaml`（主配置，含 `name`/`ssh_host`/`template_map`）；名字打错会列出可用的集群名。
- 写入方式：主配置字段全量覆盖、目标 hpc.yaml 里额外字段保留；写完后自动按新配置检查 `template_map` 里的模板文件是否找得到，找不到会 ★警告（不阻断）。
- `-tt` 技能级要求该材料已开 skill_subdir；材料级要求已 `tf init`（有 project_setting/）。
- 切换只影响**之后**提交的作业；已在旧超算排队/算完的任务不受影响。

**接入一台新超算（两步）**：

1. 照 `setting/jzzn.yaml` 建 `setting/<名>.yaml`——`ssh_host` 填新集群的 ssh 别名，`template_map` 指向新模板文件名；
2. 把新集群的提交模板存到 `skill/<技能>/`（如 `skill/band/submit_<名>_vaspstd_3d.tpl`，2D 体系另备 `_2d.tpl`），其中 `#SBATCH --job-name=...` 必须写成 `#SBATCH --job-name={{JOBNAME}}`（`{{JOBNAME}}` 占位符由 tf 提交时替换），分区、module、vasp 路径按新集群实际填。

### auto 一键开关自动提交

```bash
tf auto          # 查看当前开关状态
tf auto off      # 关闭：status/watch 只看不提交（手动 start/retry/rerun 不受影响）
tf auto on       # 开启
```

直接改写全局 tf.yaml 的 `auto_advance` 行（没有则补在文件头），一次命令生效、不用手编辑；后台监控（auto_watch）不受影响。动目录、恢复备份、大批量调整前先 `off`，完事 `on`。

### 按技能批量开始 / 指定材料

```bash
tf -tt elastic start             # 开始 elastic 技能的全部材料
tf -tt elastic -p Ela1 start     # 只开始指定材料（可逗号多个 -p A,B）
tf -tt band start                # band 技能全部材料
```

### 隐藏已完成项目

`tf --hide-done`：状态表只显示未完成的项目（底部提示隐藏了几个）。全局 tf.yaml 写 `hide_done: true` 设为默认，`--show-done` 临时恢复显示。watch 循环同样遵守该配置。

### fetch --all 拉回全部文件

`tf fetch` 默认只拉 `fetch_files` 清单（INCAR/OUTCAR 等）；`tf fetch --all` 把每个步骤**整个目录**拉回。配合 `-tt` 只拉某个技能：`tf -tt elastic fetch --all`。elastic 的 S3_post 步骤产物文件名不固定，配置里已默认整目录拉（`fetch_all: true`），无需加 --all。

## 工作原理（无状态）

作业与步骤的对应关系来自 `squeue` 的工作目录（%Z），同名作业不混淆；scancel 后状态自动回落为文件判据，无状态残留。每次调用只 ssh 一次，同时采集所有任务类型。

## 给大语言模型用（agent 接入）

`tf` 按"LLM 工具"设计，三个接口约定：

1. **命令原子化**：`status/start/stop/retry/rerun/json`，参数 `-tt/-p/-j` 语义稳定，适合 agent 调用。
2. **`tf json`**：全量结构化状态（`types → materials → steps`，含 `kind/diag/job/action`），agent 的主要输入。
3. **退出码**：0 = 成功；非 0 = 失败或被拒绝（如步骤已有作业未加 `-f`、FAIL 步骤直接 `start`、取消确认被拒）。agent 据此判成败，不用猜文本。

配套文件 `tf-agent指令.md`：给 LLM 的完整接入规范（角色、安全铁律、命令参考、FAIL 诊断决策树、监控循环模板、汇报模板）。用法：

- **Kimi Claw**：内容贴进人设/SOUL 或长期记忆，按文档第七节建 30 分钟定时巡检任务；
- **Kimi Code / IDE agent**：改名 `AGENTS.md` 放项目根目录。

核心原则：agent 只做诊断、建议和经授权的操作；一切超算变更必须经过 `tf`，禁止 agent 直接拼 ssh/sbatch/scancel/rm。

## 目录结构与版本管理

推荐布局：所有 taskflow 文件收进一个独立目录，版本收进 `versions/`，技能脚本收进 `skill/`：

```
~/taskflow/                 # 软件包（程序 + 默认模板 + agent 设置，全部在这里）
├── versions/
│   ├── <旧版本>/tf         # 旧版本留档
│   └── v1.0/tf             # 当前版本主程序
├── setting/                # 默认模板（init 时复制给项目）
│   ├── tf_default.yaml     #   项目配置模板 → project_setting/tf_<项目名>.yaml
│   └── jzzn.yaml           #   默认超算配置 → project_setting/hpc.yaml（项目无 hpc.yaml 时回退用它）
├── skill/                  # 任务技能脚本（gen 脚本 + 模板，统一放 WSL）
│   ├── band/               #   能带类：gen_step1_PBE_opt.py、incar.tpl、submit_jzzn_vasp*.tpl...
│   ├── kl/                 #   晶格热导率类（建了之后放这里）
│   └── ke/                 #   电子热导率类
├── tf.yaml                 # 全局配置（host + project_roots + 公共骨架）
├── AGENTS.md               # 智能体设置（= tf-agent指令.md），只放这里，项目文件夹不放
└── （文档）

~/Fullerene_Network/        # 项目根（project_roots 登记）；这里只有项目文件夹，无其他文件
└── C20/
    ├── qHPC20/
    │   ├── POSCAR          # 输入文件在本地
    │   └── project_setting/    # 材料专用配置（tf init 生成，每个材料一份）
    │       ├── tf_qHPC20.yaml  #   材料配置（命名全局唯一；缺省继承全局/上级）
    │       ├── setting.yaml    #   路径/结果/日志/fetch 清单
    │       ├── hpc.yaml        #   超算 + 模板映射（换超算改它）
    │       └── submit_jzzn_vasp*.tpl   # 从 skill 复制的模板，可再改
    └── qTPC20-b/           # 同上结构
（就近优先：材料级 project_setting 优先；也可在 C20/ 建一份作全体系共享兜底，
 没有材料级配置的材料自动用它）

超算（jzzn）：只放 work_dir 计算目录树（tf 自动建），无需存放任何脚本
~/.local/bin/tf -> ~/taskflow/versions/v1.0/tf   # 软链接 = 当前生效版本
```

```bash
# 初次安装
mkdir -p ~/taskflow/versions/v1.0 ~/taskflow/setting ~/.local/bin
cp tf ~/taskflow/versions/v1.0/tf && chmod +x ~/taskflow/versions/v1.0/tf
cp tf.example.yaml ~/taskflow/tf.yaml      # 按项目编辑
ln -sf ~/taskflow/versions/v1.0/tf ~/.local/bin/tf
tf --version                               # 查看当前版本

# 以后升级（拿到新版 tf）
mkdir -p ~/taskflow/versions/v1.1
cp 新tf ~/taskflow/versions/v1.1/tf && chmod +x ~/taskflow/versions/v1.1/tf
ln -sf ~/taskflow/versions/v1.1/tf ~/.local/bin/tf   # 切换

# 出问题一键回滚
ln -sf ~/taskflow/versions/<旧版本>/tf ~/.local/bin/tf
```

要点：

- **配置只有一份**（`~/taskflow/tf.yaml`），`versions/vX.Y/` 和旧版 `vX.Y/` 平铺布局都能自动找到（程序解析自身真实路径后向上找 1~2 级），升级不用动配置。
- **skill_dir**：配置里 `skill_dir: skill/band`（相对 tf.yaml 所在目录，或绝对路径）。gen 需要的脚本/模板在材料目录缺失时，tf 从本地 skill 目录**经 ssh 推送**到超算（base64 编码，只补不覆盖），超算上无需再集中存放。`gen_dir` 保留为远端兜底。
- **setting/<hpc>.yaml**：包内默认超算配置；项目 `project_setting/hpc.yaml` 缺省时回退到它。新增一台超算就在这里加一份（如 `hf.yaml`），类型配置 `hpc: hf` 或项目 hpc.yaml 指过去。
- 版本目录名随意（`v1.0`、`2026-07` 都行），软链接指谁谁是当前版。
