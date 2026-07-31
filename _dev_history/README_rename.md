# 带隙段改名 + 合并列 —— 安装

前提：patch5 已打（你已经做了），ke 技能已装。

## 步骤

```bash
cd ~/software/taskflow
# 1. 若还没打 patch5，先打（已打会提示跳过）
python3 apply_patch5.py versions/v1.0/tf -o versions/v1.0/tf

# 2. 改带隙段的计算目录名（改 4 个 gen 脚本的目录常量）
bash rename_bandgap.sh

# 3. 换新清单（子步嵌套 + group 合并列 + HSE 可选）
cp skill.yaml skill/ke/skill.yaml

# 4. 之前 clean 删了各材料的 ke 配置，重新给 Mg2C60 初始化
tf -tt ke -p Mg2C60 clean -y        # 先清掉 Mg2C60 残留（scancel 状态）
tf -tt ke -p Mg2C60 init
tf -tt ke -p Mg2C60 status          # 竖排看，应是 9 列合并后的步骤
```

## 效果

- 状态表带隙 4 子步合并成 **S2_bandgap 一列**（12 列 → 9 列）
- 计算目录：`step2_bandgap/step2.1_static`、`step2.2_wave`、`step2.3_hse`、`step2.4_gap`
- 深度可调（在 project_setting/tf_Mg2C60_ke.yaml 的 ke: 段写）：
    bandgap_hse: false     只到 PBE 带隙（跳过 HSE，省一步）
    bandgap_steps: false   完全不算带隙（手填 setting.yaml 的 bandgap）
  泛函 pbe / pbesol 由 step1 结构优化继承，不用单独设。

## 注意

宽表：日常用 `tf -tt ke -p <材料> status`（竖排，不超宽）。
总表还想更窄，我可以再加 --brief（只显示活跃步+进度），需要说一声。
