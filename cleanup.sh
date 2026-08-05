#!/usr/bin/env bash
# =====================================================================
# cleanup.sh —— taskflow 仓库瘦身（默认只看不动）
#
#   bash cleanup.sh ~/software/taskflow            # 预览（不改任何东西）
#   bash cleanup.sh ~/software/taskflow --go       # 真正执行
#   bash cleanup.sh ~/software/taskflow --go --after-smoke
#                                                  # 冒烟测试通过后，再清本次迁移的备份
#
# 原则：**不删，只归档**。所有东西移到 <仓库>/_attic_<日期>/ 保持原有相对路径，
# 确认无碍之后你自己 rm -rf 那个目录即可。
#
# 分四类：
#   A 根目录的陈旧副本   skill.yaml / gen_step1_PBE_opt.py / stepconf.py / step.conf
#     —— tf 只从 <搜索根>/*/skill.yaml 发现技能、只从技能目录找 gen 脚本，
#        根目录这几份是早期开发遗留，不会被加载
#   B 已经用过的补丁文件 tf.patch / skill_band.patch / tf_shared_checks.patch
#   C versions/v1.0 的历史 tf 备份，保留最近 KEEP_TF 个
#   D 本次迁移产生的备份（.bak_0dpool_* / *.bak_stage2）——只有加 --after-smoke 才动
# =====================================================================
set -euo pipefail

KEEP_TF=2                      # versions/v1.0 里保留几个最近的 tf 备份

TF="${1:-}"
GO=""; AFTER=""
for a in "${@:2}"; do
    [ "$a" = "--go" ] && GO=1
    [ "$a" = "--after-smoke" ] && AFTER=1
done
if [ -z "$TF" ] || [ ! -f "$TF/versions/v1.0/tf" ]; then
    echo "用法: bash cleanup.sh <taskflow 仓库根目录> [--go] [--after-smoke]"
    exit 1
fi
TF="$(cd "$TF" && pwd)"
ATTIC="$TF/_attic_$(date +%Y%m%d)"
TOTAL=0

if [ -d "$TF/.git" ]; then
    echo "== 检测到 git 仓库。建议先确认工作区已提交（改动都能找回来）："
    echo "     cd $TF && git status --short | head"
    echo
fi

stash () {   # <相对路径> <说明>
    local rel="$1" note="${2:-}"
    [ -e "$TF/$rel" ] || return 0
    local sz; sz=$(du -sk "$TF/$rel" 2>/dev/null | cut -f1)
    TOTAL=$((TOTAL + sz))
    printf "   %-52s %6s KB  %s\n" "$rel" "$sz" "$note"
    if [ -n "$GO" ]; then
        mkdir -p "$ATTIC/$(dirname "$rel")"
        mv "$TF/$rel" "$ATTIC/$rel"
    fi
}

echo "== A 根目录的陈旧副本（tf 不会加载它们）"
stash skill.yaml            "与 skill/band/skill.yaml 逐字节相同的旧副本"
stash gen_step1_PBE_opt.py  "迁移前的旧版本，现在真正生效的是 skill/band/ 下的薄壳"
stash stepconf.py           "与 skill/ 下的副本相同；公共池已有一份"
stash step.conf             "早期示例，项目的 step.conf 由 tf 三层合并生成"

echo "== B 已经用过的补丁文件"
stash tf.patch
stash skill_band.patch
stash tf_shared_checks.patch "本次共享 checks.py 的补丁，已应用"

echo "== C versions/v1.0 的历史 tf 备份（保留最近 $KEEP_TF 个）"
cd "$TF/versions/v1.0"
mapfile -t BAKS < <(ls -1t tf.bak* 2>/dev/null || true)
for i in "${!BAKS[@]}"; do
    if [ "$i" -lt "$KEEP_TF" ]; then
        printf "   保留 %s\n" "${BAKS[$i]}"
    else
        stash "versions/v1.0/${BAKS[$i]}"
    fi
done
cd "$TF"

if [ -n "$AFTER" ]; then
    echo "== D 本次迁移的备份（--after-smoke）"
    for d in .bak_0dpool_*; do
        [ -e "$d" ] && stash "$d" "apply.sh 的备份"
    done
    while IFS= read -r f; do
        stash "${f#./}" "stage2 的备份"
    done < <(find . -name '*.bak_stage2' -not -path './_attic_*' | sort)
else
    echo "== D 本次迁移的备份：先留着"
    echo "   .bak_0dpool_* 和 *.bak_stage2 是唯一的回滚手段，"
    echo "   等 tf 冒烟测试（老材料仍 done、新材料 gen 出 run_relax.sh）通过后，"
    echo "   再跑一次本脚本加 --after-smoke 归档它们。"
fi

echo
if [ -n "$GO" ]; then
    echo "== 已归档到 $ATTIC（共约 ${TOTAL} KB）"
    echo "   确认一切正常后：rm -rf $ATTIC"
else
    echo "== 预览完毕，共约 ${TOTAL} KB。加 --go 才真正移动。"
fi
echo "== 另外建议手动做的一件事："
echo "     mv $TF/taskflow-0d-pool ~/       # 部署包挪出仓库，别混在技能树里"
