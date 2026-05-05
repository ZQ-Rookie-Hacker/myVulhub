#!/bin/bash

set -e

APP_NAME="myVulhub"
APP_DIR="/opt/$APP_NAME"
VENV_DIR="$APP_DIR/venv"
SERVICE_FILE="/etc/systemd/system/$APP_NAME.service"
PORT=5000
LOG_DIR="/var/log/$APP_NAME"
VULHUB_PATH="${VULHUB_PATH:-/opt/vulhub}"

# 创建日志函数
log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1"
}

# 错误处理函数
error_exit() {
    log "错误: $1"
    exit 1
}

# 检查命令执行结果
check_command() {
    if [ $? -ne 0 ]; then
        error_exit "$1"
    fi
}

log "=========================================="
log "开始部署 $APP_NAME"
log "=========================================="

# 检查权限
if [ "$EUID" -ne 0 ]; then
    error_exit "请使用 root 权限运行此脚本"
fi

# 检查系统类型
if [ -f /etc/os-release ]; then
    . /etc/os-release
    OS=$ID
    VERSION=$VERSION_ID
    log "检测到系统: $OS $VERSION"
else
    log "警告: 无法检测系统类型，继续执行..."
fi

log "检查系统依赖..."

# 检查 Python3
if ! command -v python3 >/dev/null 2>&1; then
    log "未安装 python3，正在安装..."
    case $OS in
        ubuntu|debian)
            apt-get update && apt-get install -y python3 python3-venv python3-pip
            ;;
        centos|rhel|fedora)
            yum install -y python3 python3-venv || dnf install -y python3 python3-venv
            ;;
        *)
            error_exit "不支持的系统类型，请手动安装 Python3"
            ;;
    esac
    check_command "Python3 安装失败"
fi

# 检查 Docker
if ! command -v docker >/dev/null 2>&1; then
    error_exit "未安装 Docker，请先安装 Docker"
fi

# 检查 Docker Compose
log "检查 Docker Compose..."
if command -v docker-compose >/dev/null 2>&1; then
    COMPOSE_CMD="docker-compose"
    log "找到 docker-compose 命令"
elif command -v docker compose >/dev/null 2>&1; then
    COMPOSE_CMD="docker compose"
    log "找到 docker compose 命令"
else
    error_exit "未安装 docker-compose，请先安装 Docker Compose"
fi

# 检查是否已存在部署（必须在创建目录前处理）
if [ -f "$SERVICE_FILE" ]; then
    log "警告: 发现已存在的部署，将进行覆盖安装"
    log "停止现有服务..."
    if systemctl is-active --quiet "$APP_NAME" 2>/dev/null; then
        systemctl stop "$APP_NAME" || log "停止服务失败（可能服务未运行）"
    fi
    if systemctl is-enabled --quiet "$APP_NAME" 2>/dev/null; then
        systemctl disable "$APP_NAME" || log "禁用服务失败"
    fi
fi

# 备份现有文件（在创建新目录前执行）
if [ -d "$APP_DIR" ] && [ "$(ls -A "$APP_DIR" 2>/dev/null)" ]; then
    BACKUP_DIR="/tmp/${APP_NAME}_backup_$(date +%Y%m%d_%H%M%S)"
    log "创建备份: $BACKUP_DIR"
    cp -r "$APP_DIR" "$BACKUP_DIR" || log "备份失败，继续执行..."
fi

log "创建应用目录..."
mkdir -p "$APP_DIR" || error_exit "无法创建应用目录"
mkdir -p "$LOG_DIR" || error_exit "无法创建日志目录"

log "复制应用文件..."
# 检查 rsync 是否存在，如果不存在则使用 cp
if command -v rsync >/dev/null 2>&1; then
    rsync -av \
        --exclude='.git' \
        --exclude='venv' \
        --exclude='.env' \
        --exclude='*.swp' \
        --exclude='*.swo' \
        --exclude='__pycache__' \
        --exclude='*.pyc' \
        --exclude='*.log' \
        --exclude='deploy.sh' \
        --exclude='uninstall.sh' \
        . "$APP_DIR/" || error_exit "文件复制失败"
else
    # cp 回退：排除无关文件
    shopt -s dotglob 2>/dev/null || true
    for item in *; do
        case "$item" in
            .git|venv|.env|__pycache__|deploy.sh|uninstall.sh) continue ;;
            *.swp|*.swo|*.pyc|*.log) continue ;;
        esac
        cp -r "$item" "$APP_DIR/" 2>/dev/null || true
    done
    shopt -u dotglob 2>/dev/null || true
fi

cd "$APP_DIR" || error_exit "无法切换到应用目录"

log "创建 Python 虚拟环境..."
python3 -m venv "$VENV_DIR" || error_exit "虚拟环境创建失败"

log "激活虚拟环境并安装依赖..."
source "$VENV_DIR/bin/activate" || error_exit "虚拟环境激活失败"
pip install --upgrade pip || error_exit "pip 升级失败"
pip install -r requirements.txt || error_exit "依赖安装失败"

log "设置环境变量..."
export VULHUB_PATH="${VULHUB_PATH:-/opt/vulhub}"

log "创建 systemd 服务文件..."
cat > "$SERVICE_FILE" << EOF
[Unit]
Description=MyVulHub Manager Web Service
Documentation=https://github.com/your-org/myvulhub
After=network.target docker.service
Requires=docker.service

[Service]
Type=simple
User=root
Group=root
WorkingDirectory=$APP_DIR
Environment="PATH=$VENV_DIR/bin"
Environment="VULHUB_PATH=${VULHUB_PATH:-/opt/vulhub}"
ExecStart=$VENV_DIR/bin/python run.py
ExecReload=/bin/kill -HUP \$MAINPID
Restart=on-failure
RestartSec=5
TimeoutStopSec=90
StandardOutput=journal
StandardError=journal
SyslogIdentifier=myvulhub

[Install]
WantedBy=multi-user.target
EOF

check_command "服务文件创建失败"

log "设置日志目录权限..."
chown -R root:root "$LOG_DIR" || log "权限设置失败"
chmod 755 "$LOG_DIR" || log "权限设置失败"

log "重载 systemd 配置..."
systemctl daemon-reload || error_exit "systemd 重载失败"

log "启用服务..."
systemctl enable "$APP_NAME" || error_exit "服务启用失败"

log "启动服务..."
systemctl start "$APP_NAME" || error_exit "服务启动失败"

log "等待服务启动..."
for i in {1..10}; do
    if systemctl is-active --quiet "$APP_NAME"; then
        break
    fi
    sleep 2
    log "等待服务启动... ($i/10)"
done

if systemctl is-active --quiet "$APP_NAME"; then
    log "=========================================="
    log "部署成功！"
    log "=========================================="
    log "服务状态: $(systemctl is-active $APP_NAME)"
    log "访问地址: http://$(hostname -I | awk '{print $1}' | cut -d' ' -f1):$PORT"
    log "日志文件: $LOG_DIR/app.log"
	    log ""
	    log "重要: 请克隆 vulhub 仓库（服务依赖此目录扫描环境）："
	    log "  git clone https://github.com/vulhub/vulhub.git $VULHUB_PATH"
	    log "  (可通过 Web 界面 /api/git-sync 接口同步更新)"
	    log ""
    log "管理命令:"
    log "  启动服务: systemctl start $APP_NAME"
    log "  停止服务: systemctl stop $APP_NAME"
    log "  重启服务: systemctl restart $APP_NAME"
    log "  查看状态: systemctl status $APP_NAME"
    log "  查看日志: journalctl -u $APP_NAME -f"
    log "  服务文件: $SERVICE_FILE"
    log "  应用目录: $APP_DIR"
	    log "  Vulhub目录: $VULHUB_PATH"
    log "=========================================="
    
    # 测试服务是否可访问
    log "测试服务是否可访问..."
    sleep 3
    if curl -s http://localhost:$PORT >/dev/null 2>&1; then
        log "服务测试通过！"
    else
        log "警告: 服务启动但无法通过HTTP访问，请检查端口配置"
    fi
else
    log "=========================================="
    log "部署失败，服务未正常启动"
    log "=========================================="
    log "请检查日志: journalctl -u $APP_NAME -n 50"
    log "或查看文件: $LOG_DIR/error.log"
    log "=========================================="
    exit 1
fi