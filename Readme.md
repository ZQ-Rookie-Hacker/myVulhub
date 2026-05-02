# MyVulHub — 漏洞环境管理系统

基于 Flask 的 Web 界面漏洞环境管理平台，提供 Docker 化漏洞环境的一键部署、状态监控和镜像管理。

## 项目结构

```
myVulhub/
├── run.py                       # 应用入口
├── app/
│   ├── __init__.py              # Flask 工厂函数 create_app()
│   ├── config.py                # 集中配置（路径、TTL、日志等）
│   ├── routes/
│   │   ├── __init__.py          # Blueprint 注册
│   │   ├── main.py              # 页面路由 GET /
│   │   └── api.py               # 全部 API 路由（/api/*）
│   ├── services/
│   │   ├── __init__.py
│   │   ├── scanner.py           # 环境扫描（并行线程池）
│   │   ├── docker.py            # Docker 操作（VulhubOperations 类）
│   │   └── git.py               # Git 同步操作（GitOperations 类）
│   └── utils/
│       ├── __init__.py
│       ├── helpers.py           # 通用工具函数 + 错误装饰器
│       ├── cache.py             # 缓存管理（EnvCache + 持久化）
│       └── compose.py           # docker-compose.yml 解析
├── templates/
│   └── index.html               # 前端页面
├── static/
│   ├── style.css
│   └── script.js
├── deploy.sh                    # 一键部署脚本
├── uninstall.sh                 # 卸载脚本
└── requirements.txt
```

**架构分层：**

| 层 | 目录 | 职责 |
|----|------|------|
| 路由层 | `app/routes/` | HTTP 请求处理，参数提取，响应格式化 |
| 服务层 | `app/services/` | 核心业务逻辑（扫描、Docker操作、Git同步） |
| 工具层 | `app/utils/` | 可复用的纯函数（缓存、compose解析、装饰器） |
| 配置层 | `app/config.py` | 集中管理所有常量和日志配置 |

## 系统要求

| 组件 | 最低版本 |
|------|----------|
| Python | 3.7+ |
| Docker | 20.10+ |
| Docker Compose | 2.0+ |
| Git | 2.0+（可选） |

推荐：Ubuntu 20.04+ / Debian 10+，8GB+ RAM，SSD 存储。

## 快速开始

### 开发环境

```bash
# 1. 克隆项目
git clone https://github.com/your-org/myvulhub.git
cd myvulhub

# 2. 克隆 vulhub 仓库到任意目录
git clone https://github.com/vulhub/vulhub.git /path/to/vulhub

# 3. 安装依赖
pip install -r requirements.txt

# 4. 启动（三种方式配置 vulhub 路径）
# 方式 A: 环境变量
export VULHUB_PATH="/path/to/vulhub"
python run.py

# 方式 B: Web UI 配置（启动后在工具栏更改）
python run.py

# 方式 C: 持久化配置文件（自动创建于 ~/.vulhub_manager_app_config.json）
# 访问 http://localhost:5000
```

### 生产部署

```bash
# 先克隆 vulhub 仓库
git clone https://github.com/vulhub/vulhub.git /opt/vulhub

# 一键部署（默认路径 /opt/vulhub）
sudo ./deploy.sh

# 或指定自定义路径
VULHUB_PATH=/custom/path/to/vulhub sudo ./deploy.sh
```

部署脚本会自动创建 systemd 服务，启动命令：
```bash
sudo systemctl start myVulhub
sudo systemctl status myVulhub
sudo journalctl -u myVulhub -f
```

## API 接口文档

所有接口返回统一格式：

```json
{
  "success": true,
  "message": "",
  "timestamp": 1714636800000,
  "data": null
}
```

### 环境管理

#### `GET /api/scan`
扫描所有漏洞环境。默认使用缓存，`?cache=false` 强制重新扫描。

```bash
curl http://localhost:5000/api/scan
curl http://localhost:5000/api/scan?cache=false
```

**响应 data 字段**（数组，每个元素）：
| 字段 | 类型 | 说明 |
|------|------|------|
| name | string | 环境标识（如 `nexus/CVE-2020-10199`） |
| category | string | 分类名称 |
| cve | string | CVE 编号 |
| status | string | `unknown` / `running` / `stopped` |
| ports | object | 服务端口映射 `{"service": "port"}` |
| services | array | 服务名称列表 |
| has_exploit | bool | 是否包含漏洞利用脚本 |
| has_images | bool | 是否包含截图 |
| has_readme | bool | 是否包含 README |
| has_readme_zh | bool | 是否包含中文 README |
| has_docker_images | bool | 所需 Docker 镜像是否存在 |

#### `GET /api/stats`
获取统计摘要。

```bash
curl http://localhost:5000/api/stats
```

返回：`total`（环境总数）、`running`（运行中）、`with_exploit`（含利用脚本）、`with_images`（已有镜像）、`categories`（分类分布）。

#### `GET /api/env/<path:name>`
获取指定环境的详情（compose 内容、截图、利用脚本列表）。

```bash
curl http://localhost:5000/api/env/nexus/CVE-2020-10199
```

#### `GET /api/readme/<path:name>`
获取环境的 README 文档（转 HTML，优先中文版）。

```bash
curl http://localhost:5000/api/readme/nexus/CVE-2020-10199
```

#### `GET /api/exploit/<path:name>`
获取漏洞利用脚本内容。

```bash
curl http://localhost:5000/api/exploit/nexus/CVE-2020-10199
```

返回 exploit 文件列表，每个包含 `filename`、`content`、`usage` 等字段。

### 容器操作

#### `POST /api/start`
启动环境。

```bash
curl -X POST http://localhost:5000/api/start \
  -H "Content-Type: application/json" \
  -d '{"name": "nexus/CVE-2020-10199", "use_proxy": false}'
```

| 参数 | 类型 | 说明 |
|------|------|------|
| name | string | 环境标识（必填） |
| use_proxy | bool | 是否通过 proxychains4 代理拉取镜像 |

#### `POST /api/stop`
停止环境。

```bash
curl -X POST http://localhost:5000/api/stop \
  -H "Content-Type: application/json" \
  -d '{"name": "nexus/CVE-2020-10199"}'
```

#### `GET /api/check-images`
检查环境所需的 Docker 镜像是否缺失。

```bash
curl "http://localhost:5000/api/check-images?name=nexus/CVE-2020-10199"
```

返回 `missing` 数组列出缺失的镜像名称。

#### `GET /api/pull-stream` (SSE)
通过 Server-Sent Events 流式拉取镜像。

```bash
curl -N "http://localhost:5000/api/pull-stream?name=nexus/CVE-2020-10199&proxy=false"
```

事件类型：`event: log`（拉取日志行）、`event: done`（完成）。

#### `GET /api/wait-ready`
轮询等待服务就绪（HTTP 200 响应）。

```bash
curl "http://localhost:5000/api/wait-ready?name=nexus/CVE-2020-10199&timeout=30"
```

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| name | string | — | 环境标识 |
| timeout | int | 20 | 最大等待秒数 |

返回 `ready: true/false` 及 `port`。

#### `POST /api/remove-images`
删除环境相关的 Docker 镜像。

```bash
curl -X POST http://localhost:5000/api/remove-images \
  -H "Content-Type: application/json" \
  -d '{"name": "nexus/CVE-2020-10199"}'
```

返回 `removed`、`failed`、`total` 统计。

### 系统管理

#### `GET|POST /api/vulhub-path`
获取或设置 vulhub 仓库路径。设置后自动清除缓存。

```bash
# 获取当前路径
curl http://localhost:5000/api/vulhub-path

# 设置新路径
curl -X POST http://localhost:5000/api/vulhub-path \
  -H "Content-Type: application/json" \
  -d '{"path": "/opt/vulhub"}'
```

路径优先级：Web UI 设置 > 环境变量 `VULHUB_PATH` > 默认 `../vulhub`。

#### `GET|POST /api/git-config`
获取或保存 Git 远程仓库配置。

```bash
# 获取
curl http://localhost:5000/api/git-config

# 保存
curl -X POST http://localhost:5000/api/git-config \
  -H "Content-Type: application/json" \
  -d '{"remote_url": "https://github.com/vulhub/vulhub.git", "use_proxy": false}'
```

#### `POST /api/git-sync`
同步 Vulhub 仓库。

```bash
curl -X POST http://localhost:5000/api/git-sync \
  -H "Content-Type: application/json" \
  -d '{"method": "https", "remote_url": "https://github.com/vulhub/vulhub.git"}'
```

method 支持：`https`、`ssh`、`https_proxy`（proxychains4）、`gh`（GitHub CLI）。

#### `GET /api/running`
获取当前运行中的 Docker 容器列表（基于 `docker ps`）。

```bash
curl http://localhost:5000/api/running
```

#### `POST /api/refresh-cache`
强制清除缓存并重新扫描。

```bash
curl -X POST http://localhost:5000/api/refresh-cache
```

## 开发指南

### 架构设计

应用使用 Flask 的 **应用工厂模式**（`create_app()`）和 **Blueprint** 进行路由组织。核心原则：

- **路由层不写业务逻辑**：路由函数只做参数提取 → 调服务 → 格式化返回
- **服务之间通过构造函数注入依赖**：如 `VulhubOperations.__init__()` 中创建 `GitOperations` 实例
- **服务通过 `current_app.config` 暴露给路由**：避免循环导入

### 启动流程

```
run.py
  └── create_app()                    # app/__init__.py
        ├── EnvCache()                # 初始化缓存
        ├── load_persistent_cache()   # 尝试加载磁盘缓存
        ├── VulhubOperations()        # 初始化 Docker 服务（含 GitOperations）
        └── register_blueprint()      # 注册 main_bp + api_bp
```

### 添加新 API 端点

1. 如需新业务逻辑，在 `app/services/` 添加方法
2. 在 `app/routes/api.py` 添加路由函数
3. 通过 `current_app.config['OPS']` 获取服务实例

示例：

```python
# app/routes/api.py
@api_bp.route('/my-endpoint')
def my_endpoint():
    ops = current_app.config['OPS']
    result = ops.some_method()
    return jsonify({"success": True, "data": result})
```

### 添加新服务

1. 在 `app/services/` 创建新模块
2. 在 `app/__init__.py` 的 `create_app()` 中初始化
3. 通过 `app.config['KEY']` 注入

### 配置管理

所有常量集中在 `app/config.py`。动态配置通过以下机制：

- **Vulhub 路径**：通过 `get_vulhub_path()` / `set_vulhub_path()` 管理，持久化到 `~/.vulhub_manager_app_config.json`
- **Git 配置**：通过 `/api/git-config` 端点管理，持久化到 `~/.vulhub_manager_git_config.json`
- **环境扫描缓存**：自动持久化到 `~/.vulhub_manager_cache.json`

### 缓存机制

- **内存缓存** (`EnvCache` 类)：会话级，重启丢失
- **持久化缓存** (`~/.vulhub_manager_cache.json`)：24 小时过期，通过目录哈希检测变化自动失效
- **路径变更检测**：当 vulhub 路径变更、目录结构变化或缓存过期时自动重新扫描
- 强制刷新：`POST /api/refresh-cache` 或通过 Web UI 更改 vulhub 路径

### 模块依赖关系

```
routes (api.py, main.py)
  ├── services (scanner.py, docker.py, git.py)
  │     └── utils (compose.py, helpers.py)
  └── utils (cache.py, helpers.py)
        └── config.py
```

`services` 和 `routes` 之间不互相导入 —— 路由通过 `current_app.config` 获取服务实例。

## 配置参考

### 环境变量

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `VULHUB_PATH` | `../vulhub` | Vulhub 根目录（可被 Web UI 设置覆盖） |
| `FLASK_ENV` | `production` | Flask 运行模式 |

### 持久化配置文件

| 文件 | 说明 |
|------|------|
| `~/.vulhub_manager_app_config.json` | 应用配置（vulhub 路径） |
| `~/.vulhub_manager_cache.json` | 环境扫描缓存（24h TTL） |
| `~/.vulhub_manager_git_config.json` | Git 远程仓库配置 |

## 安全建议

- 仅在内网或 VPN 环境下暴露 Web 端口
- 启动环境时注意端口冲突，端口冲突会返回 `port_conflict: true`
- 路径遍历保护：所有环境名经过 `_env_dir()` / `get_env_dir_by_name()` 的越权检查
- 生产环境建议配置反向代理（nginx）+ HTTPS

## 卸载

```bash
sudo ./uninstall.sh
```

卸载脚本会清理：systemd 服务、应用目录、日志目录、所有用户缓存及配置文件。

## 许可证

MIT License
