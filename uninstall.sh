#!/bin/bash

set -e

APP_NAME="myVulhub"
APP_DIR="/opt/$APP_NAME"
SERVICE_FILE="/etc/systemd/system/$APP_NAME.service"
LOG_DIR="/var/log/$APP_NAME"

# 创建日志函数
log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1"
}

# 错误处理函数
error_exit() {
    log "错误: $1"
    exit 1
}

log "=========================================="
log "开始卸载 $APP_NAME"
log "=========================================="

# 检查权限
if [ "$EUID" -ne 0 ]; then
    error_exit "请使用 root 权限运行此脚本"
fi

# 交互式确认
read -p "确定要完全卸载 $APP_NAME 吗？此操作不可逆！(y/N): " -n 1 -r
echo
if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    log "取消卸载"
    exit 0
fi

# 二次确认
read -p "再次确认：这将删除所有数据，包括配置和日志！(yes/NO): " -n 3 -r
echo
if [[ ! $REPLY =~ ^[Yy][Ee][Ss]$ ]]; then
    log "取消卸载"
    exit 0
fi

log "停止并禁用服务..."

# 停止服务
if systemctl is-active --quiet "$APP_NAME" 2>/dev/null; then
    log "停止服务..."
    systemctl stop "$APP_NAME" || log "停止服务失败（可能服务未运行）"
else
    log "服务未运行"
fi

# 禁用服务
if systemctl is-enabled --quiet "$APP_NAME" 2>/dev/null; then
    log "禁用服务..."
    systemctl disable "$APP_NAME" || log "禁用服务失败"
else
    log "服务未启用"
fi

log "删除 systemd 服务文件..."
if [ -f "$SERVICE_FILE" ]; then
    log "删除服务文件: $SERVICE_FILE"
    rm -f "$SERVICE_FILE" || error_exit "无法删除服务文件"
    systemctl daemon-reload || log "systemd 重载失败"
    systemctl reset-failed || log "重置失败状态失败"
else
    log "服务文件不存在: $SERVICE_FILE"
fi

log "删除应用目录..."
if [ -d "$APP_DIR" ]; then
    log "删除应用目录: $APP_DIR"
    # 检查目录大小，避免误删
    dir_size=$(du -sh "$APP_DIR" 2>/dev/null | cut -f1)
    log "目录大小: $dir_size"
    rm -rf "$APP_DIR" || error_exit "无法删除应用目录"
else
    log "应用目录不存在: $APP_DIR"
fi

log "删除日志目录..."
if [ -d "$LOG_DIR" ]; then
    log "删除日志目录: $LOG_DIR"
    rm -rf "$LOG_DIR" || error_exit "无法删除日志目录"
else
    log "日志目录不存在: $LOG_DIR"
fi

log "删除用户缓存文件..."
# 删除root用户缓存
if [ -f "/root/.myVulhub_cache.json" ]; then
    rm -f "/root/.myVulhub_cache.json" || log "无法删除root用户缓存"
fi

# 删除其他用户缓存
for user_home in /home/*; do
    if [ -f "$user_home/.myVulhub_cache.json" ]; then
        rm -f "$user_home/.myVulhub_cache.json" || log "无法删除$user_home用户缓存"
    fi
done

# 删除临时备份文件
log "清理临时备份文件..."
rm -f /tmp/myvulhub_backup_* 2>/dev/null || true

log "清理可能的残留进程..."
# 优雅地终止相关进程
pkill -f "myVulhub" 2>/dev/null || true
pkill -f "app.py" 2>/dev/null || true

# 等待进程结束
sleep 2

# 强制终止（如果必要）
pkill -9 -f "myVulhub" 2>/dev/null || true
pkill -9 -f "app.py" 2>/dev/null || true

log "验证卸载结果..."
# 检查是否还有残留文件
remaining_files=0
if [ -d "$APP_DIR" ]; then
    log "警告: 应用目录仍然存在: $APP_DIR"
    remaining_files=$((remaining_files + 1))
fi

if [ -f "$SERVICE_FILE" ]; then
    log "警告: 服务文件仍然存在: $SERVICE_FILE"
    remaining_files=$((remaining_files + 1))
fi

if [ -d "$LOG_DIR" ]; then
    log "警告: 日志目录仍然存在: $LOG_DIR"
    remaining_files=$((remaining_files + 1))
fi

if [ $remaining_files -eq 0 ]; then
    log "=========================================="
    log "卸载完成！"
    log "=========================================="
    log "$APP_NAME 已从系统中完全移除"
    log "所有相关文件和配置已清理"
    log "=========================================="
else
    log "=========================================="
    log "卸载完成，但发现 $remaining_files 个残留文件"
    log "=========================================="
    log "建议手动检查并清理残留文件"
    log "=========================================="
fi

# 最后检查
log "最终状态检查:"
log "服务状态: $(systemctl is-active $APP_NAME 2>/dev/null || echo '未找到')"
log "服务启用状态: $(systemctl is-enabled $APP_NAME 2>/dev/null || echo '未找到')"
log "目录存在性:"
log "  $APP_DIR: $([ -d "$APP_DIR" ] && echo '存在' || echo '不存在')"
log "  $SERVICE_FILE: $([ -f "$SERVICE_FILE" ] && echo '存在' || echo '不存在')"
log "  $LOG_DIR: $([ -d "$LOG_DIR" ] && echo '存在' || echo '不存在')"