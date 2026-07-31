# ke（电子热导率）技能 —— 安装说明

**你已经装好的**（前面几步做过了，不用重来）：
`apply_patch.py`（技能插件化）已打进 tf；band / elastic 已重组成模板布局。

**本包新增**：patch2/3/4（模板布局 + 扇出 + 分组源目录）、ke 技能全套文件。

---

## 一、这个压缩包怎么用

包里只有一个文件夹 `放到_taskflow根目录/`，把**里面所有文件**复制到
`~/software/taskflow/`（和 setup_ke.sh 同级）即可：

```bash
# 假设压缩包解压在 ~/下载/
cp ~/下载/放到_taskflow根目录/* ~/software/taskflow/
cd ~/software/taskflow
```

放好之后，`~/software/taskflow/` 下会多出这些文件（都在根目录，安装脚本会自动
把它们分发到 skill/ke/ 的各个子目录，你不用手动摆放）：

```
apply_patch2.py  apply_patch3.py  apply_patch4.py    ← tf 补丁
setup_ke.sh  place_ke_files.sh                       ← 安装脚本
skill.yaml                                           ← ke 清单
SKILL_DEV.md                                         ← 技能开发规范（存档用）
ke_common.py                                         ← ke 公共库
gen_step5_uniform.py  gen_step6_wave.py  gen_step8_dielect.py
gen_step9_deform.py   gen_step9b_deform_read.py  gen_step10_amset.py
incar_uniform_{2d,3d}.tpl  incar_dfpt_{2d,3d}.tpl  incar_deform_{2d,3d}.tpl
submit_amset.tpl
```

---

## 二、安装（按顺序，每步都有验证）

### 1. 打三个补丁

```bash
cd ~/software/taskflow
cp versions/v1.0/tf versions/v1.0/tf.bak_before_ke     # 备份
python3 apply_patch2.py versions/v1.0/tf -o versions/v1.0/tf   # 模板目录布局
python3 apply_patch3.py versions/v1.0/tf -o versions/v1.0/tf   # 扇出步骤
python3 apply_patch4.py versions/v1.0/tf -o versions/v1.0/tf   # 分组源目录
tf skills && tf     # 关卡：band/elastic 状态与现在完全一致
```

> 若你之前已经打过 patch2 / patch3，脚本会提示“已经打过本补丁”，跳过即可。
> patch4 是新的，一定要打。

### 2. 装配 ke 前半段（复用 band / elastic）

```bash
bash setup_ke.sh
```

它从 band、elastic 复制出结构优化 / 带隙 / 弹性常数三段，改好 2 处目录名常量，
建好分组目录树。

### 3. 分发 ke 新文件

```bash
bash place_ke_files.sh
```

把 6 个新 gen 脚本、6 个 INCAR 模板、ke_common.py 放进 skill/ke/ 的对应子目录，
并打印每个文件的落点。

### 4. 放清单、打开技能

```bash
cp skill.yaml skill/ke/skill.yaml
sed -i 's/enabled: false/enabled: true/' skill/ke/skill.yaml
tf skills           # 关卡：应看到 ke，12 步
```

### 5. 配 work_dir

编辑 `setting/tf.yaml`，`task_types:` 下加：

```yaml
  ke:
    work_dir: /public/home/wangchao/Fullerene_Network/work
```

---

## 三、安装后的 skill/ke/ 长这样

```
skill/ke/
├── skill.yaml
├── step1_opt/                gen_step1_std_opt.py + incar/submit 模板（复用 elastic）
├── bandgap/                  ← 带隙大步骤（复用 band 全套）
│   ├── step2_static/
│   ├── step3_wavecar/
│   ├── step4_hse/
│   └── step4_plot/
├── step5_uniform/            gen_step5_uniform.py + incar_uniform_{2d,3d}.tpl + ke_common.py
├── step6_wave/               gen_step6_wave.py + submit_amset.tpl
├── step7_elastic/            gen_step2_elastic.py（复用 elastic，IBRION=6）
├── step8_dielect/            gen_step8_dielect.py + incar_dfpt_{2d,3d}.tpl + ke_common.py
├── deform/                   ← 形变势大步骤
│   ├── step9_deform/         gen_step9_deform.py + incar_deform_{2d,3d}.tpl + ke_common.py
│   └── step9b_read/          gen_step9b_deform_read.py
└── step10_amset/             gen_step10_amset.py + submit_amset.tpl
```

超算上和本地 result 里的**计算目录仍是平的**（step1_std_opt/、step2_PBE_static/…），
不受源目录分组影响 —— 这是 patch4 的 src 机制在起作用。

---

## 四、12 个步骤

| seq | 计算目录 | label | 说明 |
|----|---------|-------|------|
| 1 | step1_std_opt | S1_opt | 结构优化（复用 elastic，2D/3D 通用）|
| 2 | step2_PBE_static | S2_static | 带隙段：PBE 静态 ┐ |
| 2.1 | step3_PBE_WAVECAR | S2.1_wave | WAVECAR │ 可选组 |
| 2.2 | step4_HSE_band | S2.2_HSE | HSE06 能带 │ bandgap_steps |
| 2.3 | step4_band_plot | S2.3_gap | 取带隙 ┘ 默认开 |
| 3 | step5_uniform | S3_uniform | 密网格自洽 → WAVECAR |
| 4 | step6_wave | S4_wave | amset wave → wavefunction.h5 |
| 5 | step8_dielect | S5_dielect | DFPT 介电 → ε∞, ε₀ |
| 6 | step7_elastic | S6_elastic | 弹性常数（IBRION=6）|
| 7 | step9_deform | S7_deform | 形变势单点（扇出）|
| 7.1 | step9b_deform_read | S7.1_read | amset deform read → deformation.h5 |
| 8 | step10_amset | S8_kappa | amset run → κ_e |

带隙不想自算：在项目配置写 `bandgap_steps: false`，再在
`project_setting/setting.yaml` 写 `bandgap: <值>`。

---

## 五、跑之前必看的可改参数

每个 gen 脚本开头都有「可改参数区」。重点几个：

- **gen_step5_uniform.py**：`KSPACING = "0.03"`（AMSET 密网格）
- **gen_step10_amset.py**：
  - `DOPING = "-1e21:-1e17:5, 1e17:1e21:5"`（n+p 型各 5 点）
  - `TEMPERATURES = "100:900:9"`（100–900 K，每 100 K）
  - `MANUAL_ELASTIC = None`（留 None = 从 step7_elastic/OUTCAR 自动解析；
    或填标量 GPa / 6×6 列表手动指定）
  - `SCATTERING = ["ACD", "IMP", "POP"]`
- **submit_amset.tpl**：conda 环境 amset_clean、分区、核数

---

## 六、先单步验证再全跑

```bash
cd ~/Fullerene_Network/<某体系>          # 含材料目录的上级
tf -tt ke init                           # 给材料挂 ke 段
tf -tt ke -p <材料> -j 1 init            # 只生成 step1，人工检查 INCAR/KPOINTS
tf -tt ke -p <材料> -j 1 dir             # 拿远端路径，ssh 过去看
tf -tt ke -p <材料> start                # 确认无误后开跑
```

---

## 七、回滚

```bash
cp versions/v1.0/tf.bak_before_ke versions/v1.0/tf
```

skill/ke/ 目录留着不影响 —— 打回旧 tf 后它不认识这个技能，等于没有。
