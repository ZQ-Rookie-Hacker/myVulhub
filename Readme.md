# MyVulHub - 漏洞环境管理系统

[![License](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Version](https://img.shields.io/badge/version-1.0.0-green.svg)](VERSION)
[![Platform](https://img.shields.io/badge/platform-Linux%20%7C%20macOS%20%7C%20Windows-lightgrey.svg)](PLATFORM)

## 项目概述

MyVulHub 是一款基于 Web 界面的漏洞环境管理系统，专为渗透测试和安全研究设计。该系统提供了一站式的漏洞环境部署、管理和监控解决方案。

## 核心特性

### 功能模块
- **环境扫描**：自动扫描 Vulhub 目录中的漏洞环境
- **启停控制**：一键启动/停止漏洞环境
- **状态监控**：实时监控容器运行状态
- **镜像管理**：自动检测缺失镜像并提供拉取选项
- **文档集成**：内置环境说明文档和漏洞利用脚本
- **搜索过滤**：支持按分类、CVE、状态等条件过滤
- **分页展示**：支持大量环境的分页浏览
- **Git 同步**：支持从远程仓库同步 Vulhub 环境

### 技术架构
- **前端框架**：原生 JavaScript + HTML/CSS
- **后端框架**：Flask 2.x
- **容器技术**：Docker & Docker Compose
- **数据格式**：JSON API 接口
- **协议支持**：HTTP

## 系统要求

### 最低配置
- **CPU**：双核 2.0 GHz 或更高
- **内存**：4 GB RAM（推荐 8 GB）
- **存储**：20 GB 可用空间
- **操作系统**：Ubuntu 18.04+/CentOS 7+/Debian 10+/macOS 10.14+/Windows 10 WSL2

### 软件依赖
- **Python**：3.7 或更高版本
- **Docker**：20.10 或更高版本
- **Docker Compose**：2.0 或更高版本
- **Git**：2.0 或更高版本（可选，用于 Git 同步功能）

### 推荐环境
- **Ubuntu Server 20.04 LTS** 或 **CentOS Stream 8**
- **8 GB RAM** 或更高
- **SSD 存储**
- **千兆网络连接**

## 安装部署

### 快速部署
```bash
# 1. 克隆项目
git clone https://github.com/your-org/myvulhub.git
cd myvulhub

# 2. 授权脚本执行权限
chmod +x deploy.sh uninstall.sh

# 3. 执行部署（需要 root/sudo 权限）
sudo ./deploy.sh
```

### 自定义部署
```bash
# 设置自定义环境变量
export VULHUB_PATH="/opt/vulhub"
export MYVULHUB_PORT=5000

# 执行部署
sudo ./deploy.sh
```

### 手动部署
```bash
# 1. 创建系统目录
sudo mkdir -p /opt/myVulhub
sudo mkdir -p /var/log/myVulhub
sudo mkdir -p /opt/vulhub

# 2. 配置系统用户（推荐使用专用用户）
sudo useradd -r -s /bin/false myvulhub

# 3. 复制应用程序
sudo cp -r . /opt/myVulhub/
sudo chown -R myvulhub:myvulhub /opt/myVulhub

# 4. 创建 Python 虚拟环境
cd /opt/myVulhub
sudo -u myvulhub python3 -m venv venv
sudo -u myvulhub /opt/myVulhub/venv/bin/pip install -r requirements.txt

# 5. 配置 systemd 服务
sudo tee /etc/systemd/system/myVulhub.service > /dev/null <<EOF
[Unit]
Description=MyVulHub Vulnerability Environment Management System
Documentation=https://github.com/your-org/myvulhub
After=network.target docker.service
Requires=docker.service

[Service]
Type=simple
User=myvulhub
Group=myvulhub
WorkingDirectory=/opt/myVulhub
Environment="PATH=/opt/myVulhub/venv/bin"
Environment="VULHUB_PATH=/opt/vulhub"
Environment="FLASK_ENV=production"
ExecStart=/opt/myVulhub/venv/bin/python app.py
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

# 6. 启动服务
sudo systemctl daemon-reload
sudo systemctl enable myVulhub
sudo systemctl start myVulhub
```

## 系统配置

### 环境变量
| 变量名 | 默认值 | 说明 |
|--------|--------|------|
| `VULHUB_PATH` | `/opt/vulhub` | Vulhub 漏洞环境根目录 |
| `MYVULHUB_PORT` | `5000` | Web 服务端口 |
| `FLASK_ENV` | `production` | Flask 运行环境 |
| `PYTHONPATH` | `/opt/myVulhub` | Python 模块搜索路径 |

### 服务管理
```bash
# 启动服务
sudo systemctl start myVulhub

# 停止服务
sudo systemctl stop myVulhub

# 重启服务
sudo systemctl restart myVulhub

# 查看服务状态
sudo systemctl status myVulhub

# 启用开机自启
sudo systemctl enable myVulhub

# 禁用开机自启
sudo systemctl disable myVulhub

# 查看实时日志
sudo journalctl -u myVulhub -f

# 查看历史日志（最近100条）
sudo journalctl -u myVulhub -n 100
```

### 配置文件
- **服务配置**：`/etc/systemd/system/myVulhub.service`
- **应用日志**：`/var/log/myVulhub/app.log`
- **错误日志**：`/var/log/myVulhub/error.log`
- **缓存文件**：`~/.myVulhub_cache.json`

## 使用指南

### Web 界面访问
1. 打开浏览器，访问 `http://<server-ip>:5000`
2. 系统将显示可用的漏洞环境列表
3. 选择目标环境进行部署和管理

### 主要功能
- **环境浏览**：查看所有可用的漏洞环境
- **快速部署**：一键启动指定的漏洞环境
- **状态监控**：实时查看容器运行状态
- **文档查看**：内置环境使用说明和 README
- **漏洞利用脚本**：查看和使用漏洞利用脚本
- **镜像管理**：自动检测缺失镜像并提供拉取选项
- **搜索过滤**：按分类、CVE、状态等条件过滤
- **分页浏览**：支持大量环境的分页浏览
- **Git 同步**：从远程仓库同步最新的漏洞环境

### 操作流程
1. **环境扫描**：系统自动扫描 Vulhub 目录中的环境
2. **环境启动**：
   - 点击 "启动" 按钮
   - 系统检测缺失镜像
   - 选择是否使用代理拉取镜像
   - 自动启动容器
3. **环境停止**：点击 "停止" 按钮停止容器
4. **查看详情**：点击 "详情" 查看环境文档和配置
5. **漏洞利用**：点击 "漏洞利用脚本" 查看利用脚本

### API 接口
系统提供 RESTful API 接口用于程序化管理：

```bash
# 获取环境列表（使用缓存）
curl -X GET http://localhost:5000/api/scan?cache=true

# 获取环境列表（强制刷新）
curl -X GET http://localhost:5000/api/scan?cache=false

# 启动环境
curl -X POST http://localhost:5000/api/start -H "Content-Type: application/json" -d '{"name":"apache/CVE-2021-41773"}'

# 停止环境
curl -X POST http://localhost:5000/api/stop -H "Content-Type: application/json" -d '{"name":"apache/CVE-2021-41773"}'

# 获取环境详情
curl -X GET http://localhost:5000/api/env/apache/CVE-2021-41773

# 获取环境说明文档
curl -X GET http://localhost:5000/api/readme/apache/CVE-2021-41773

# 获取漏洞利用脚本
curl -X GET http://localhost:5000/api/exploit/apache/CVE-2021-41773

# 检查缺失镜像
curl -X GET http://localhost:5000/api/check-images?name=apache/CVE-2021-41773

# 删除环境镜像
curl -X POST http://localhost:5000/api/remove-images -H "Content-Type: application/json" -d '{"name":"apache/CVE-2021-41773"}'

# 获取统计信息
curl -X GET http://localhost:5000/api/stats

# 刷新缓存
curl -X POST http://localhost:5000/api/refresh-cache

# 检查服务就绪状态
curl -X GET http://localhost:5000/api/wait-ready?name=apache/CVE-2021-41773&timeout=20

# 获取 Git 配置
curl -X GET http://localhost:5000/api/git-config

# 同步 Git 仓库
curl -X POST http://localhost:5000/api/git-sync -H "Content-Type: application/json" -d '{"method":"https","remote_url":"https://github.com/vulhub/vulhub.git"}'
```

## 安全配置

### 访问控制
- **网络隔离**：建议在内网环境中部署
- **防火墙配置**：限制外部访问权限
- **身份认证**：生产环境建议配置认证机制

### 防火墙规则
```bash
# Ubuntu/Debian (ufw)
sudo ufw allow from 192.168.0.0/16 to any port 5000

# CentOS/RHEL (firewalld)
sudo firewall-cmd --permanent --add-rich-rule='rule family="ipv4" source address="192.168.0.0/16" port protocol="tcp" port="5000" accept'
sudo firewall-cmd --reload
```

### 安全最佳实践
1. **定期更新**：保持系统和组件最新
2. **访问限制**：严格控制访问权限
3. **日志监控**：持续监控安全事件
4. **备份策略**：定期备份重要配置
5. **隔离环境**：在独立的测试环境中使用

## 运维管理

### 性能监控
- **CPU 使用率**：监控容器 CPU 消耗
- **内存使用**：跟踪内存分配情况
- **磁盘 I/O**：监测磁盘读写性能
- **网络流量**：分析网络带宽使用

### 日志管理
```bash
# 查看应用日志
sudo tail -f /var/log/myVulhub/app.log

# 查看错误日志
sudo tail -f /var/log/myVulhub/error.log

# 日志轮转配置
sudo tee /etc/logrotate.d/myvulhub > /dev/null <<EOF
/var/log/myVulhub/*.log {
    daily
    rotate 30
    compress
    delaycompress
    missingok
    notifempty
    copytruncate
}
EOF
```

### 缓存管理
系统使用两层缓存机制：
- **内存缓存**：临时缓存扫描结果
- **持久化缓存**：保存在 `~/.myVulhub_cache.json` 文件中，24小时过期

### 备份恢复
```bash
# 备份配置文件
sudo tar -czf myvulhub-backup-$(date +%Y%m%d).tar.gz \
  /etc/systemd/system/myVulhub.service \
  /opt/myVulhub/config/

# 恢复配置文件
sudo tar -xzf myvulhub-backup-YYYYMMDD.tar.gz -C /
```

## 故障排除

### 常见问题

#### 服务无法启动
```bash
# 检查服务状态
sudo systemctl status myVulhub

# 查看详细日志
sudo journalctl -u myVulhub --no-pager

# 检查端口占用
sudo netstat -tlnp | grep :5000

# 检查依赖服务
sudo systemctl status docker
```

#### Docker 相关错误
```bash
# 检查 Docker 服务
sudo systemctl status docker

# 检查 Docker 权限
sudo usermod -aG docker $USER

# 重启 Docker 服务
sudo systemctl restart docker
```

#### 网络连接问题
```bash
# 检查防火墙设置
sudo ufw status
sudo firewall-cmd --list-all

# 检查网络接口
ip addr show

# 测试本地连接
curl -I http://localhost:5000
```

#### 端口冲突
当启动环境时遇到端口冲突：
- 查看占用容器：`docker ps` 
- 停止冲突容器：`docker stop <container-id>`
- 或修改环境的 `docker-compose.yml` 文件使用其他端口

### 调试模式
```bash
# 以调试模式启动
sudo -u myvulhub /opt/myVulhub/venv/bin/python app.py --debug

# 查看系统资源使用
sudo htop
sudo docker stats
```

## 卸载清理

### 自动卸载
```bash
# 执行卸载脚本
sudo ./uninstall.sh
```

### 手动卸载
```bash
# 1. 停止并禁用服务
sudo systemctl stop myVulhub
sudo systemctl disable myVulhub

# 2. 删除服务配置
sudo rm -f /etc/systemd/system/myVulhub.service
sudo systemctl daemon-reload
sudo systemctl reset-failed

# 3. 删除应用目录
sudo rm -rf /opt/myVulhub
sudo rm -rf /var/log/myVulhub

# 4. 清理残留文件
sudo find / -name "*.myVulhub*" -type f 2>/dev/null | xargs sudo rm -f
```


## 开发环境搭建
```bash
# 1. 克隆代码
git clone https://github.com/your-org/myvulhub.git
cd myvulhub

# 2. 创建虚拟环境
python3 -m venv venv
source venv/bin/activate

# 3. 安装开发依赖
pip install -r requirements.txt

# 4. 设置环境变量
export VULHUB_PATH="/path/to/vulhub"

# 5. 启动开发服务器
python app.py
```
