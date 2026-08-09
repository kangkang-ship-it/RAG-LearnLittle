#!/usr/bin/env bash
# ============================================================
# MySQL 备份脚本（生产风险分析·高优先级 6）
#
# 用法:
#   bash scripts/manual/mysql_backup.sh                    # 备份到 ./backups/mysql
#   bash scripts/manual/mysql_backup.sh /path/to/dir       # 自定义备份目录
#
# 特性:
#   - 从 .env 自动读取 MYSQL_HOST/PORT/USER/PASSWORD/DATABASE
#   - mysqldump --single-transaction（InnoDB 一致性快照，不锁表）
#   - gzip 压缩，保留最近 14 份，旧备份自动清理
#
# 恢复演练（重要: 备份无价值，能恢复才有价值）:
#   gunzip -c backups/mysql/raglearn_YYYYmmdd_HHMMSS.sql.gz | mysql --default-character-set=utf8mb4 -h localhost -u root -p raglearn
#   （Windows 管道导入必须加 --default-character-set=utf8mb4，否则中文数据报转义错误）
#   演练建议: 每月在测试库恢复一次并抽查数据完整性
#
# 定时执行:
#   Linux: crontab -e 添加  "30 2 * * * cd /path/to/project && bash scripts/manual/mysql_backup.sh"
#   Windows: 任务计划程序 → 新建任务 → 操作指向 Git Bash: "C:\Program Files\Git\bin\bash.exe" -lc "cd /c/Users/xxx/RagLearnCode && bash scripts/manual/mysql_backup.sh"
#   Docker: 在 mysql 容器外执行本脚本（需宿主机装 mysql 客户端），或另起定时容器挂载数据卷
# ============================================================
set -euo pipefail

BACKUP_DIR="${1:-./backups/mysql}"
KEEP="${MYSQL_BACKUP_KEEP:-14}"

# ---- 从 .env 读取 MySQL 配置（不 source，避免内联注释/特殊字符问题）----
if [ -f .env ]; then
  get_env() { grep -E "^$1=" .env | head -1 | cut -d= -f2- | tr -d ' \r' || true; }
  MYSQL_HOST=$(get_env MYSQL_HOST);   [ -n "$MYSQL_HOST" ]   || MYSQL_HOST=localhost
  MYSQL_PORT=$(get_env MYSQL_PORT);   [ -n "$MYSQL_PORT" ]   || MYSQL_PORT=3306
  MYSQL_USER=$(get_env MYSQL_USER);   [ -n "$MYSQL_USER" ]   || MYSQL_USER=root
  MYSQL_PASSWORD=$(get_env MYSQL_PASSWORD)
  MYSQL_DATABASE=$(get_env MYSQL_DATABASE); [ -n "$MYSQL_DATABASE" ] || MYSQL_DATABASE=raglearn
fi

# ---- 定位 mysqldump ----
DUMP=""
if command -v mysqldump >/dev/null 2>&1; then
  DUMP=mysqldump
elif [ -n "${MYSQL_HOME:-}" ] && [ -x "$MYSQL_HOME/bin/mysqldump" ]; then
  DUMP="$MYSQL_HOME/bin/mysqldump"
else
  echo "错误: 未找到 mysqldump（请安装 MySQL 客户端并加入 PATH）" >&2
  exit 1
fi

# ---- 执行备份 ----
mkdir -p "$BACKUP_DIR"
STAMP=$(date +%Y%m%d_%H%M%S)
OUT="$BACKUP_DIR/${MYSQL_DATABASE}_${STAMP}.sql.gz"

echo "开始备份: ${MYSQL_DATABASE}@${MYSQL_HOST}:${MYSQL_PORT} → ${OUT}"
# MYSQL_PWD 环境变量传密码（避免密码出现在进程列表）
if ! MYSQL_PWD="$MYSQL_PASSWORD" "$DUMP" \
    -h"$MYSQL_HOST" -P"$MYSQL_PORT" -u"$MYSQL_USER" \
    --single-transaction --routines --triggers \
    --default-character-set=utf8mb4 \
    "$MYSQL_DATABASE" | gzip > "$OUT"; then
  echo "备份失败!" >&2
  rm -f "$OUT"
  exit 1
fi

SIZE=$(du -h "$OUT" | cut -f1)
echo "备份完成: $OUT ($SIZE)"

# ---- 清理旧备份（保留最近 KEEP 份）----
COUNT=$(ls -1t "$BACKUP_DIR"/*.sql.gz 2>/dev/null | wc -l)
if [ "$COUNT" -gt "$KEEP" ]; then
  ls -1t "$BACKUP_DIR"/*.sql.gz | tail -n "$((COUNT - KEEP))" | xargs -r rm -f
  echo "已清理旧备份，保留最近 ${KEEP} 份"
fi
