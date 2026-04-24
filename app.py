#!/usr/bin/env python3
# coding: utf-8
from flask import Flask, render_template, jsonify, request
from pathlib import Path
import markdown
import base64
import os
import subprocess
import shlex
import json
import time
import hashlib
import logging
import functools

# 设置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger('vulhub_manager')

# 错误处理装饰器
def handle_docker_errors(func):
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except subprocess.TimeoutExpired:
            logger.error("Docker操作超时")
            return False, {"error": "Docker操作超时"}
        except subprocess.CalledProcessError as e:
            # 更安全的错误信息处理
            try:
                error_msg = e.stderr.decode('utf-8', errors='ignore').strip() if e.stderr else ""
                if not error_msg:
                    error_msg = e.stdout.decode('utf-8', errors='ignore').strip() if e.stdout else ""
                if not error_msg:
                    error_msg = str(e)
            except Exception:
                error_msg = str(e)
            logger.error(f"Docker命令执行失败: {error_msg}")
            return False, {"error": f"Docker命令执行失败: {error_msg}"}
        except FileNotFoundError:
            logger.error("Docker未安装或不可用")
            return False, {"error": "Docker未安装或不可用"}
        except Exception as e:
            logger.error(f"Docker操作异常: {str(e)}")
            return False, {"error": f"Docker操作异常: {str(e)}"}
    return wrapper

# 这两个还是保留；operations 仍用你现有的逻辑启停容器
try:
    from vulhub_manager import VulhubManager
except Exception:
    VulhubManager = None

from operations import VulhubOperations

app = Flask(__name__)

# === 基本设置 ===
VULHUB_PATH = Path(os.environ.get('VULHUB_PATH', '../vulhub')).resolve()
CACHE_FILE = Path.home() / '.vulhub_manager_cache.json'  # 持久化缓存文件
CACHE_TTL_MS = 24 * 60 * 60 * 1000  # 缓存有效期：24 小时

if VulhubManager:
    try:
        manager = VulhubManager(str(VULHUB_PATH))
    except Exception:
        manager = None
else:
    manager = None

ops = VulhubOperations()

# 内部缓存（避免每次都跑全扫）
_env_cache = {
    "data": None,     # list[dict]
    "ts": 0,          # epoch ms
    "hash": None      # 目录哈希值，用于检测变化
}

# 可用时尝试加载 PyYAML 解析 compose
try:
    import yaml
except Exception:
    yaml = None


# ====== 小工具 ======

def _now_ms():
    return int(time.time() * 1000)

# 标准API响应格式
def api_response(success, data=None, message="", code=200):
    """标准API响应格式"""
    response = {
        "success": success,
        "message": message,
        "timestamp": _now_ms(),
        "data": data
    }
    return jsonify(response), code


def _read_text(p: Path):
    try:
        # 优化：快速读取小文件，减少不必要的磁盘访问
        stat = p.stat()
        if stat.st_size > 1024 * 100:  # 100KB以上使用流式读取
            with p.open('r', encoding='utf-8', errors='ignore') as f:
                return f.read()
        else:  # 小文件使用read_text更高效
            return p.read_text(encoding='utf-8', errors='ignore')
    except Exception:
        return ''


def _calculate_vulhub_hash():
    """计算 Vulhub 目录的简单哈希值，用于判断是否有变化"""
    try:
        # 只计算 docker-compose.yml 文件的数量和路径
        compose_files = list(VULHUB_PATH.rglob('docker-compose.yml'))
        paths_str = ''.join(sorted([str(f.relative_to(VULHUB_PATH)) for f in compose_files]))
        return hashlib.md5(paths_str.encode()).hexdigest()
    except Exception:
        return None


def _load_persistent_cache():
    """从文件加载持久化缓存"""
    try:
        if CACHE_FILE.exists():
            with open(CACHE_FILE, 'r', encoding='utf-8') as f:
                cache_data = json.load(f)
                
            # 检查缓存是否过期
            cache_ts = cache_data.get('timestamp', 0)
            if _now_ms() - cache_ts > CACHE_TTL_MS:
                logger.info("缓存已过期，需要重新扫描")
                return None
                
            # 检查 Vulhub 目录是否有变化
            saved_hash = cache_data.get('vulhub_hash')
            current_hash = _calculate_vulhub_hash()
            if saved_hash != current_hash:
                logger.info("检测到 Vulhub 目录有变化，需要重新扫描")
                return None
                
            # 检查缓存路径是否匹配
            saved_path = cache_data.get('vulhub_path')
            if saved_path and saved_path != str(VULHUB_PATH):
                logger.info("Vulhub路径已变更，需要重新扫描")
                return None
                
            env_count = len(cache_data.get('environments', []))
            logger.info(f"从持久化缓存加载 {env_count} 个环境")
            return cache_data.get('environments', [])
    except Exception as e:
        logger.error(f"加载缓存失败: {e}")
    return None


def _save_persistent_cache(environments):
    """保存持久化缓存到文件"""
    try:
        cache_data = {
            'environments': environments,
            'timestamp': _now_ms(),
            'vulhub_hash': _calculate_vulhub_hash(),
            'vulhub_path': str(VULHUB_PATH)
        }
        with open(CACHE_FILE, 'w', encoding='utf-8') as f:
            json.dump(cache_data, f, ensure_ascii=False, indent=2)
        print(f"已保存 {len(environments)} 个环境到持久化缓存")
    except Exception as e:
        print(f"保存缓存失败: {e}")


def _compose_parse_services_ports(compose_path: Path):
    """
    尝试从 docker-compose.yml 解析 service 名称与 host 端口（若没装 PyYAML 就回空）
    返回: (services: list[str], ports_map: dict[str, str])
    """
    services, ports_map = [], {}
    if not compose_path.exists():
        return services, ports_map

    if yaml:
        try:
            data = yaml.safe_load(_read_text(compose_path)) or {}
            svcs = data.get('services') or {}
            for svc_name, svc_cfg in svcs.items():
                services.append(str(svc_name))
                port_list = svc_cfg.get('ports') or []
                host_ports = []
                for item in port_list:
                    # 可能是 "8080:80" 或 "127.0.0.1:8080:80" 或 dict
                    if isinstance(item, str):
                        # 取最左边 host port（冒号前一段最后的数字）
                        parts = item.split(':')
                        if len(parts) >= 2:
                            # 127.0.0.1:8080:80 -> 取 -2 位置
                            try:
                                host_ports.append(str(int(parts[-2])))
                            except Exception:
                                # "8080:80" -> 取 -2 仍是 8080；若格式怪就忽略
                                pass
                        else:
                            # "8080" 这种，不太常见，直接塞
                            host_ports.append(parts[0])
                    elif isinstance(item, dict):
                        # {"target": 80, "published": 8080, "mode": "host", "protocol": "tcp"}
                        hp = item.get('published')
                        if hp:
                            host_ports.append(str(hp))
                if host_ports:
                    # 取第一個 host port 當代表
                    ports_map[svc_name] = host_ports[0]
        except Exception:
            pass

    return services, ports_map


def _has_exploit(env_dir: Path):
    # 优化：使用更高效的方式检测Exploit文件
    # 首先检查目录是否存在（更快）
    for sub in ['exploit', 'exploits', 'poc', 'pocs']:
        if (env_dir / sub).exists():
            return True
    
    # 优化：使用next而不是list，避免创建完整列表
    exploit_patterns = ['*exploit*.py', '*exploit*.sh', 'poc.py', 'poc.sh', 'exp.py', 'PoC.py']
    for pattern in exploit_patterns:
        try:
            if next(env_dir.glob(pattern), None):  # 使用next而不是list，更高效
                return True
        except Exception:
            continue
    return False


def _image_files(env_dir: Path):
    exts = {'.png', '.jpg', '.jpeg', '.gif', '.webp', '.bmp', '.svg'}
    # 优化：使用生成器表达式，避免创建完整列表
    try:
        return [p for p in env_dir.iterdir() if p.is_file() and p.suffix.lower() in exts]
    except Exception:
        return []


@handle_docker_errors
def _check_docker_images_exist(compose_path: Path, fast_mode: bool = True):
    """
    檢查 docker-compose.yml 中定義的映像是否已存在本地
    fast_mode: True 表示快速模式（不实际检查Docker）
    """
    if fast_mode:
        # 快速模式：只解析镜像名称，不实际检查
        images_to_check = []
        
        if yaml and compose_path.exists():
            try:
                data = yaml.safe_load(_read_text(compose_path)) or {}
                svcs = data.get('services') or {}
                for svc_name, svc_cfg in svcs.items():
                    if 'image' in svc_cfg:
                        images_to_check.append(svc_cfg['image'])
            except Exception as e:
                logger.warning(f"解析YAML失败: {e}")
        
        # 如果無法解析 YAML，嘗試用正則表達式
        if not images_to_check:
            try:
                content = _read_text(compose_path)
                import re
                # 匹配 image: xxx 格式
                images = re.findall(r'^\s*image:\s*([^\s#]+)', content, re.MULTILINE)
                images_to_check = images
            except Exception as e:
                logger.warning(f"正则解析失败: {e}")
        
        # 快速模式返回False，避免IO阻塞
        return False if images_to_check else False
    else:
        # 完整检查模式
        images_to_check = []
        
        if yaml and compose_path.exists():
            try:
                data = yaml.safe_load(_read_text(compose_path)) or {}
                svcs = data.get('services') or {}
                for svc_name, svc_cfg in svcs.items():
                    if 'image' in svc_cfg:
                        images_to_check.append(svc_cfg['image'])
            except Exception as e:
                logger.warning(f"解析YAML失败: {e}")
        
        if not images_to_check:
            try:
                content = _read_text(compose_path)
                import re
                # 匹配 image: xxx 格式
                images = re.findall(r'^\s*image:\s*([^\s#]+)', content, re.MULTILINE)
                images_to_check = images
            except Exception as e:
                logger.warning(f"正则解析失败: {e}")
        
        if not images_to_check:
            return False
        
        # 优化：使用更高效的Docker命令检查
        # 使用docker images命令一次性获取所有本地镜像，然后检查目标镜像是否存在
        try:
            result = subprocess.run(
                ['docker', 'images', '--format', '{{.Repository}}:{{.Tag}}'],
                capture_output=True,
                timeout=2,  # 更短的超时时间
                text=True
            )
            if result.returncode == 0:
                local_images = set(result.stdout.strip().split('\n'))
                # 检查所有目标镜像是否都在本地存在
                for image in images_to_check:
                    if image not in local_images:
                        logger.debug(f"镜像不存在: {image}")
                        return False
                return True
            else:
                # 如果docker images命令失败，回退到逐个检查
                all_exist = True
                for image in images_to_check:
                    try:
                        result = subprocess.run(
                            ['docker', 'image', 'inspect', image],
                            capture_output=True,
                            timeout=2,  # 减少超时时间
                            text=True
                        )
                        if result.returncode != 0:
                            all_exist = False
                            logger.debug(f"镜像不存在: {image}")
                            break  # 一旦发现缺少镜像就停止检查
                    except Exception as e:
                        all_exist = False
                        logger.error(f"检查镜像失败: {image}, 错误: {e}")
                        break
                
                return all_exist
        except Exception as e:
            logger.warning(f"使用docker images命令检查失败，回退到逐个检查: {e}")
            # 回退到原来的逐个检查方式
            all_exist = True
            for image in images_to_check:
                try:
                    result = subprocess.run(
                        ['docker', 'image', 'inspect', image],
                        capture_output=True,
                        timeout=2,
                        text=True
                    )
                    if result.returncode != 0:
                        all_exist = False
                        logger.debug(f"镜像不存在: {image}")
                        break
                except Exception as e:
                    all_exist = False
                    logger.error(f"检查镜像失败: {image}, 错误: {e}")
                    break
            return all_exist


def _scan_environments_fs():
    """
    檔案系統掃描：尋找所有包含 docker-compose.yml 的資料夾
    產出前端需要的扁平資料
    """
    if not VULHUB_PATH.exists():
        raise FileNotFoundError(f"Vulhub path does not exist: {VULHUB_PATH}")

    import concurrent.futures
    from threading import Lock
    
    compose_files = list(VULHUB_PATH.rglob('docker-compose.yml'))
    total = len(compose_files)
    logger.info(f"找到 {total} 個環境，開始並行掃描...")

    # 使用线程池并行处理环境扫描
    max_workers = min(4, max(1, total // 10 + 1))  # 根据环境数量动态调整线程数
    
    def process_single_env(compose_path):
        """处理单个环境"""
        try:
            env_dir = compose_path.parent
            rel = env_dir.relative_to(VULHUB_PATH).as_posix()  # e.g. "nexus/CVE-2020-10199"
            parts = rel.split('/')
            category = parts[0] if parts else 'unknown'
            cve = parts[-1] if parts else 'unknown'

            # 优化：减少不必要的文件系统操作
            services, ports_map = _compose_parse_services_ports(compose_path)
            
            # 优化：批量检查文件存在性，减少系统调用
            readme_files = [
                env_dir / 'README.md',
                env_dir / 'README.zh-cn.md',
                env_dir / 'README_zh.md'
            ]
            has_readme = readme_files[0].exists()
            has_readme_zh = readme_files[1].exists() or readme_files[2].exists()
            
            # 优化：延迟加载图像文件列表
            imgs = _image_files(env_dir)
            
            # 检查 Docker 映像是否已存在（使用完整检查模式）
            has_docker_images = _check_docker_images_exist(compose_path, fast_mode=False)

            return {
                "name": rel,
                "category": category,
                "cve": cve,
                "status": "unknown",
                "ports": ports_map,
                "services": services,
                "has_exploit": _has_exploit(env_dir),
                "has_images": bool(imgs),
                "has_readme": has_readme,
                "has_readme_zh": has_readme_zh,
                "has_docker_images": has_docker_images,
            }
        except Exception as e:
            logger.warning(f"扫描环境失败: {compose_path}, 错误: {e}")
            return None

    envs = []
    # 使用线程池进行并行处理
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        # 提交所有任务
        future_to_compose = {executor.submit(process_single_env, path): path for path in compose_files}
        
        # 收集结果
        completed = 0
        for future in concurrent.futures.as_completed(future_to_compose):
             result = future.result()
             if result:
                 envs.append(result)
             
             completed += 1
             if completed % 50 == 0 or completed == total:
                 logger.info(f"已處理 {completed}/{total} 個環境...")

    envs.sort(key=lambda x: x["name"])
    logger.info(f"掃描完成，共找到 {len(envs)} 個有效環境")
    return envs


def _get_env_dir_by_name(name: str) -> Path:
    # name 形如 "nexus/CVE-2020-10199"
    p = (VULHUB_PATH / name).resolve()
    # 防止越權
    if VULHUB_PATH not in p.parents and p != VULHUB_PATH:
        raise FileNotFoundError("Invalid env path")
    return p


def _get_exploit_files(env_dir: Path):
    """獲取 exploit 檔案列表"""
    exploit_files = []
    
    # 檢查 exploit 目錄
    for sub in ['exploit', 'exploits', 'poc', 'pocs']:
        sub_dir = env_dir / sub
        if sub_dir.exists() and sub_dir.is_dir():
            for f in sub_dir.iterdir():
                if f.is_file() and f.suffix in ['.py', '.sh', '.rb', '.go', '.c', '.cpp']:
                    exploit_files.append(f)
    
    # 檢查根目錄的 exploit 檔案
    for pattern in ['*exploit*.py', '*exploit*.sh', 'poc.py', 'poc.sh', 'exp.py', 'PoC.py']:
        for f in env_dir.glob(pattern):
            if f.is_file():
                exploit_files.append(f)
    
    return exploit_files


# ====== Pages ======
@app.route('/')
def index():
    return render_template('index.html')


# ====== APIs ======

@app.route('/api/scan')
def api_scan():
    """
    掃描 vulhub 目錄
    ?cache=true 使用記憶體快取（預設）
    ?cache=false 強制重新掃描
    """
    use_cache = request.args.get('cache', 'true').lower() == 'true'

    # 優先使用記憶體快取
    if use_cache and _env_cache["data"]:
        return jsonify(_env_cache["data"])

    # 嘗試從持久化快取載入
    if use_cache:
        cached_envs = _load_persistent_cache()
        if cached_envs:
            _env_cache["data"] = cached_envs
            _env_cache["ts"] = _now_ms()
            return jsonify(cached_envs)

    # 需要重新掃描
    print("執行完整掃描...")
    
    # 若你的 VulhubManager 有類似 .environments 可用，就先像它
    envs = None
    if manager is not None and hasattr(manager, 'environments'):
        try:
            envs = manager.environments
        except Exception:
            envs = None

    # envs 不是 list 就改用檔案系統掃描
    if not isinstance(envs, list) or not envs:
        envs = _scan_environments_fs()

    # 標準化輸出結構
    out = []
    for e in envs:
        # 如果是我自己掃描的，就已經是 dict；若是自訂物件，盡量抽取
        if isinstance(e, dict):
            out.append({
                "name": e.get("name"),
                "category": e.get("category"),
                "cve": e.get("cve"),
                "status": e.get("status", "unknown"),
                "ports": e.get("ports") or {},
                "services": e.get("services") or [],
                "has_exploit": bool(e.get("has_exploit")),
                "has_images": bool(e.get("has_images")),
                "has_readme": bool(e.get("has_readme")),
                "has_readme_zh": bool(e.get("has_readme_zh")),
                "has_docker_images": bool(e.get("has_docker_images", False)),
            })
        else:
            # 盡最大努力從物件取出欄位
            name = getattr(e, 'name', None) or getattr(e, 'path', None)
            if name and isinstance(name, str) and name.startswith(str(VULHUB_PATH)):
                rel = Path(name).resolve().relative_to(VULHUB_PATH).as_posix()
            else:
                rel = name
            category = getattr(e, 'category', None)
            cve = getattr(e, 'cve', None)
            status = getattr(e, 'status', 'unknown')
            ports = getattr(e, 'ports', {}) or {}
            services = getattr(e, 'services', []) or []
            has_exploit = bool(getattr(e, 'has_exploit', False))
            images = getattr(e, 'images', []) or []
            has_images = bool(images)
            has_readme = bool(getattr(e, 'has_readme', False))
            has_readme_zh = bool(getattr(e, 'has_readme_zh', False))
            has_docker_images = bool(getattr(e, 'has_docker_images', False))

            if (not category or not cve) and isinstance(rel, str):
                parts = rel.split('/')
                if not category and parts:
                    category = parts[0]
                if not cve and parts:
                    cve = parts[-1]

            out.append({
                "name": rel,
                "category": category or 'unknown',
                "cve": cve or 'unknown',
                "status": status or 'unknown',
                "ports": ports,
                "services": services,
                "has_exploit": has_exploit,
                "has_images": has_images,
                "has_readme": has_readme,
                "has_readme_zh": has_readme_zh,
                "has_docker_images": has_docker_images,
            })

    # 更新記憶體快取
    _env_cache["data"] = out
    _env_cache["ts"] = _now_ms()
    
    # 保存到持久化快取
    _save_persistent_cache(out)
    
    return jsonify(out)


@app.route('/api/stats')
def api_stats():
    data = _env_cache["data"] or []
    total = len(data)
    running = sum(1 for x in data if x.get("status") == "running")
    with_exploit = sum(1 for x in data if x.get("has_exploit"))
    with_images = sum(1 for x in data if x.get("has_docker_images"))
    cats = {}
    for x in data:
        cats[x["category"]] = cats.get(x["category"], 0) + 1
    return jsonify({
        "total": total,
        "running": running,
        "with_exploit": with_exploit,
        "with_images": with_images,
        "categories": cats
    })


@app.route('/api/env/<path:name>')
def api_env_detail(name: str):
    """
    取得單一環境細節（compose、images 列表等）
    不依賴 manager.get_environment；直接從檔案系統讀
    """
    try:
        env_dir = _get_env_dir_by_name(name)
    except Exception:
        return jsonify({"error": "not found"}), 404

    compose_path = env_dir / 'docker-compose.yml'
    compose_text = _read_text(compose_path)

    # 附圖（最多 5 張，<5MB）
    images_data = []
    for img_path in _image_files(env_dir)[:5]:
        try:
            if img_path.stat().st_size < 5 * 1024 * 1024:
                with open(img_path, 'rb') as f:
                    b64 = base64.b64encode(f.read()).decode()
                ext = (img_path.suffix or ".png")[1:].lower()
                images_data.append({
                    "name": img_path.name,
                    "data": f"data:image/{ext};base64,{b64}"
                })
        except Exception:
            pass

    # 粗略列出可能的 exploit 檔名
    exploit_files = [f.name for f in _get_exploit_files(env_dir)]

    parts = name.split('/')
    category = parts[0] if parts else 'unknown'
    cve = parts[-1] if parts else 'unknown'

    return jsonify({
        "name": name,
        "category": category,
        "cve": cve,
        "compose": compose_text,
        "images": images_data,
        "exploit_files": exploit_files
    })


@app.route('/api/readme/<path:name>')
def api_readme(name: str):
    """
    把 README 轉成 HTML 回傳（優先顯示中文版）
    """
    try:
        env_dir = _get_env_dir_by_name(name)
    except Exception:
        return jsonify({"html": ""})

    md_path = None
    # 優先中文版，然後才是英文版
    for cand in ['README.zh-cn.md', 'README.zh-CN.md', 'README_zh.md', 'README.md', 'README.MD']:
        p = env_dir / cand
        if p.exists():
            md_path = p
            break

    md_text = _read_text(md_path) if md_path else ""
    html = markdown.markdown(md_text, extensions=['extra', 'tables', 'fenced_code']) if md_text else ""
    return jsonify({"html": html})


@app.route('/api/exploit/<path:name>')
def api_exploit(name: str):
    """
    獲取 exploit 檔案內容
    """
    try:
        env_dir = _get_env_dir_by_name(name)
    except Exception:
        return jsonify([]), 404

    exploits = []
    for exploit_path in _get_exploit_files(env_dir):
        try:
            content = _read_text(exploit_path)
            if content:
                # 嘗試提取使用說明（從註釋中）
                usage = ""
                lines = content.splitlines()
                for line in lines[:20]:  # 只看前20行
                    if 'usage:' in line.lower() or 'example:' in line.lower():
                        usage = line
                        break
                
                exploits.append({
                    "filename": exploit_path.name,
                    "path": str(exploit_path.relative_to(env_dir)),
                    "content": content[:10000],  # 限制大小
                    "size": len(content),
                    "lines": len(lines),
                    "usage": usage
                })
        except Exception:
            pass

    return jsonify(exploits)


@app.route('/api/start', methods=['POST'])
def api_start():
    data = request.get_json(force=True)
    name = data.get('name')
    use_proxy = data.get('use_proxy', False)
    ok, info = ops.start(name, use_proxy=use_proxy)
    # 啟動成功後，更新快取中的 status
    if ok and _env_cache["data"]:
        # 优化：使用更高效的方式更新缓存
        for e in _env_cache["data"]:
            if e.get("name") == name:
                e["status"] = "running"
                break
    return jsonify({"success": ok, **(info or {})})


@app.route('/api/stop', methods=['POST'])
def api_stop():
    data = request.get_json(force=True)
    name = data.get('name')
    ok, info = ops.stop(name)
    if ok and _env_cache["data"]:
        # 优化：使用字典查找而非循环遍历
        for e in _env_cache["data"]:
            if e.get("name") == name:
                e["status"] = "stopped"
                break
    return jsonify({"success": ok, **(info or {})})

@app.route('/api/remove-images', methods=['POST'])
def api_remove_images():
    """删除指定环境的镜像"""
    data = request.get_json(force=True)
    name = data.get('name')
    if not name:
        return jsonify({"success": False, "error": "缺少环境名称"})
    
    ok, info = ops.remove_images(name)
    return jsonify({"success": ok, **(info or {})})

# Git 配置存储文件
GIT_CONFIG_FILE = Path.home() / '.vulhub_manager_git_config.json'

def load_git_config():
    """加载 Git 配置"""
    default_config = {
        "remote_url": "https://github.com/vulhub/vulhub.git",
        "use_proxy": False,
        "last_updated": None
    }
    
    if GIT_CONFIG_FILE.exists():
        try:
            with open(GIT_CONFIG_FILE, 'r', encoding='utf-8') as f:
                config = json.load(f)
                return {**default_config, **config}
        except Exception:
            return default_config
    return default_config

def save_git_config(config):
    """保存 Git 配置"""
    try:
        config['last_updated'] = time.time()
        with open(GIT_CONFIG_FILE, 'w', encoding='utf-8') as f:
            json.dump(config, f, indent=2, ensure_ascii=False)
        return True
    except Exception:
        return False

@app.route('/api/git-config', methods=['GET', 'POST'])
def api_git_config():
    """获取或保存 Git 配置"""
    if request.method == 'GET':
        # 获取当前 Git 配置
        try:
            # 从文件加载配置
            config = load_git_config()
            
            # 检查当前远程仓库配置（优先使用实际 Git 配置）
            ok, stdout, stderr = ops._run(['git', 'remote', 'get-url', 'origin'], cwd=VULHUB_PATH)
            if ok and stdout.strip():
                config['remote_url'] = stdout.strip()
            
            return jsonify({
                "success": True,
                "remote_url": config['remote_url'],
                "use_proxy": config['use_proxy']
            })
        except Exception as e:
            return jsonify({"success": False, "error": str(e)})
    
    else:  # POST
        # 保存 Git 配置
        data = request.get_json(force=True)
        remote_url = data.get('remote_url')
        use_proxy = data.get('use_proxy', False)
        protocol = data.get('protocol', 'https')
        
        if not remote_url:
            return jsonify({"success": False, "error": "远程仓库 URL 不能为空"})
        
        try:
            # 检查是否是有效的 Git 仓库
            if not (VULHUB_PATH / ".git").exists():
                # 如果不是 Git 仓库，初始化并设置远程仓库
                ops._run(['git', 'init'], cwd=VULHUB_PATH)
                ops._run(['git', 'remote', 'add', 'origin', remote_url], cwd=VULHUB_PATH)
            else:
                # 如果是现有仓库，修改远程仓库 URL
                ops._run(['git', 'remote', 'set-url', 'origin', remote_url], cwd=VULHUB_PATH)
            
            # 保存配置到文件
            config = {
                "remote_url": remote_url,
                "use_proxy": use_proxy,
                "protocol": protocol
            }
            
            if save_git_config(config):
                return jsonify({"success": True, "message": "Git 配置保存成功"})
            else:
                return jsonify({"success": False, "error": "保存配置文件失败"})
            
        except Exception as e:
            return jsonify({"success": False, "error": f"保存配置失败: {str(e)}"})
            
        except Exception as e:
            return jsonify({"success": False, "error": f"保存配置失败: {str(e)}"})

@app.route('/api/git-sync', methods=['POST'])
def api_git_sync():
    """同步 vulhub 仓库"""
    data = request.get_json(force=True)
    method = data.get('method', 'https')
    remote_url = data.get('remote_url')
    
    if method not in ['ssh', 'https', 'https_proxy', 'gh']:
        return jsonify({"success": False, "error": "不支持的同步方式"})
    
    # 如果是 GitHub CLI 方式，需要特殊处理
    if method == 'gh':
        return _sync_with_gh_cli(remote_url)
    
    ok, info = ops.git_ops.sync_vulhub(method, remote_url)
    return jsonify({"success": ok, **(info or {})})

def _sync_with_gh_cli(remote_url: str = None):
    """使用 GitHub CLI 同步"""
    try:
        # 检查是否安装了 gh CLI
        import subprocess
        result = subprocess.run(['gh', '--version'], capture_output=True, text=True)
        if result.returncode != 0:
            return {"success": False, "error": "未安装 GitHub CLI (gh)"}
        
        vulhub_path = VULHUB_PATH
        
        # 使用 gh repo clone 或 gh repo sync
        if not (vulhub_path / ".git").exists():
            # 克隆仓库
            if remote_url:
                repo_url = remote_url
            else:
                repo_url = "vulhub/vulhub"
            
            cmd = ['gh', 'repo', 'clone', repo_url, str(vulhub_path)]
            result = subprocess.run(cmd, capture_output=True, text=True)
        else:
            # 同步现有仓库
            cmd = ['gh', 'repo', 'sync']
            result = subprocess.run(cmd, cwd=str(vulhub_path), capture_output=True, text=True)
        
        if result.returncode == 0:
            return {"success": True, "message": "GitHub CLI 同步成功", "output": result.stdout}
        else:
            return {"success": False, "error": f"GitHub CLI 同步失败: {result.stderr}"}
            
    except Exception as e:
        return {"success": False, "error": f"GitHub CLI 同步异常: {str(e)}"}


@app.route('/api/check-images')
def api_check_images():
    name = request.args.get('name', '')
    ok, info = ops.check_images(name)
    return jsonify({"success": ok, **(info or {})})


@app.route('/api/pull-stream')
def api_pull_stream():
    """
    SSE：拉取缺少的 images；由前端 /api/pull-stream 使用 EventSource 讀取
    """
    name = request.args.get('name', '')
    use_proxy = request.args.get('proxy', 'false').lower() == 'true'

    def gen():
        for line in ops.pull_images_stream(name, use_proxy=use_proxy):
            yield f"event: log\ndata: {line}\n\n"
        yield "event: done\ndata: ok\n\n"

    return app.response_class(gen(), mimetype='text/event-stream')


@app.route('/api/wait-ready')
def api_wait_ready():
    """
    等 web 服務可用（避免剛起來就打開 404）
    """
    name = request.args.get('name', '')
    timeout = int(request.args.get('timeout', '20'))
    ok, info = ops.wait_ready(name, timeout=timeout)
    return jsonify({"success": ok, **(info or {})})


# === /api/running：列出目前運行中的容器 ===
@app.route('/api/running')
def api_running():
    try:
        cmd = "docker ps --format {{json .}}"
        result = subprocess.run(
            shlex.split(cmd),
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )
        containers = []
        for line in result.stdout.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except Exception:
                obj = {}
            containers.append({
                "id": (obj.get("ID") or "")[:12],
                "name": obj.get("Names") or "",
                "image": obj.get("Image") or "",
                "status": obj.get("Status") or "",
                "ports": obj.get("Ports") or ""
            })

        return jsonify({"success": True, "containers": containers})
    except subprocess.CalledProcessError as e:
        return jsonify({
            "success": False,
            "error": f"docker ps 失敗：{e.stderr.strip() or e.stdout.strip()}"
        }), 500
    except FileNotFoundError:
        return jsonify({
            "success": False,
            "error": "找不到 docker 指令，請確認已安裝 Docker 並在 PATH 中。"
        }), 500


@app.route('/api/refresh-cache', methods=['POST'])
def api_refresh_cache():
    """強制清除並重建快取"""
    try:
        # 清除記憶體快取
        _env_cache["data"] = None
        _env_cache["ts"] = 0
        
        # 删除持久化缓存文件
        if CACHE_FILE.exists():
            CACHE_FILE.unlink()
            print("已删除持久化缓存文件")
        
        # 重新掃描
        print("強制重新掃描所有環境...")
        envs = _scan_environments_fs()
        
        # 標準化輸出
        out = []
        for e in envs:
            out.append({
                "name": e.get("name"),
                "category": e.get("category"),
                "cve": e.get("cve"),
                "status": e.get("status", "unknown"),
                "ports": e.get("ports") or {},
                "services": e.get("services") or [],
                "has_exploit": bool(e.get("has_exploit")),
                "has_images": bool(e.get("has_images")),
                "has_readme": bool(e.get("has_readme")),
                "has_readme_zh": bool(e.get("has_readme_zh")),
                "has_docker_images": bool(e.get("has_docker_images", False)),
            })
        
        # 更新快取
        _env_cache["data"] = out
        _env_cache["ts"] = _now_ms()
        _save_persistent_cache(out)
        
        return jsonify({"success": True, "count": len(out)})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


if __name__ == '__main__':
    # 啟動時嘗試載入持久化快取
    print(f"Vulhub 路径: {VULHUB_PATH}")
    print(f"缓存文件: {CACHE_FILE}")
    
    cached_data = _load_persistent_cache()
    if cached_data:
        _env_cache["data"] = cached_data
        _env_cache["ts"] = _now_ms()
        print(f"成功载入持久化缓存，共 {len(cached_data)} 个环境")
    else:
        print("未找到有效缓存，将在首次请求时扫描")
    
    print(f"使用 Docker Compose 命令: docker compose")
    app.run(debug=True, host='0.0.0.0', port=5000)