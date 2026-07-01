# coding: utf-8
import json
import hashlib
import re
import subprocess
from pathlib import Path

from app.config import get_vulhub_path, CACHE_FILE, CACHE_TTL_MS, DOCKER_PS_TIMEOUT, logger
from app.utils.helpers import now_ms

# docker ps 短期缓存，避免同一请求周期内多次调用
_docker_ps_cache = {"data": None, "ts": 0}
_DOCKER_PS_CACHE_TTL_MS = 2000  # 2 秒


class EnvCache:
    def __init__(self):
        self.data = None
        self.ts = 0
        self.hash = None

    def get(self):
        return self.data

    def set(self, data):
        self.data = data
        self.ts = now_ms()

    def is_valid(self):
        return self.data is not None

    def clear(self):
        self.data = None
        self.ts = 0
        self.hash = None


def _get_running_container_names() -> set:
    """获取当前运行中的容器名称集合（带 2s 短期缓存）"""
    global _docker_ps_cache
    now = now_ms()
    if _docker_ps_cache["data"] is not None and (now - _docker_ps_cache["ts"]) < _DOCKER_PS_CACHE_TTL_MS:
        return _docker_ps_cache["data"]

    try:
        result = subprocess.run(
            ['docker', 'ps', '--format', '{{.Names}}'],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=DOCKER_PS_TIMEOUT
        )
        names = {ln.strip().lower() for ln in result.stdout.splitlines() if ln.strip()}
    except (subprocess.CalledProcessError, FileNotFoundError, subprocess.TimeoutExpired):
        names = set()

    _docker_ps_cache["data"] = names
    _docker_ps_cache["ts"] = now
    return names


def get_running_containers_json():
    """获取运行中容器列表（JSON 格式），供 /api/running 复用"""
    try:
        result = subprocess.run(
            ['docker', 'ps', '--format', '{{json .}}'],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=DOCKER_PS_TIMEOUT
        )
        containers = []
        for line in result.stdout.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except Exception:
                continue
            containers.append({
                "id": (obj.get("ID") or "")[:12],
                "name": obj.get("Names") or "",
                "image": obj.get("Image") or "",
                "status": obj.get("Status") or "",
                "ports": obj.get("Ports") or ""
            })
        return containers
    except (subprocess.CalledProcessError, FileNotFoundError, subprocess.TimeoutExpired):
        return []


def calculate_vulhub_hash():
    """计算 vulhub 目录结构哈希（sha256，仅取前 16 位用于快速比对）"""
    try:
        vulhub_path = get_vulhub_path()
        compose_files = list(vulhub_path.rglob('docker-compose.yml'))
        paths_str = ''.join(sorted([str(f.relative_to(vulhub_path)) for f in compose_files]))
        return hashlib.sha256(paths_str.encode()).hexdigest()[:16]
    except Exception:
        return None


def load_persistent_cache():
    try:
        if CACHE_FILE.exists():
            with open(CACHE_FILE, 'r', encoding='utf-8') as f:
                cache_data = json.load(f)

            cache_ts = cache_data.get('timestamp', 0)
            if now_ms() - cache_ts > CACHE_TTL_MS:
                logger.info("缓存已过期，需要重新扫描")
                return None

            saved_hash = cache_data.get('vulhub_hash')
            current_hash = calculate_vulhub_hash()
            if saved_hash != current_hash:
                logger.info("检测到 Vulhub 目录有变化，需要重新扫描")
                return None

            saved_path = cache_data.get('vulhub_path')
            if saved_path and saved_path != str(get_vulhub_path()):
                logger.info("Vulhub路径已变更，需要重新扫描")
                return None

            env_count = len(cache_data.get('environments', []))
            logger.info(f"从持久化缓存加载 {env_count} 个环境")
            return cache_data.get('environments', [])
    except Exception as e:
        logger.error(f"加载缓存失败: {e}")
    return None


def save_persistent_cache(environments):
    try:
        cache_data = {
            'environments': environments,
            'timestamp': now_ms(),
            'vulhub_hash': calculate_vulhub_hash(),
            'vulhub_path': str(get_vulhub_path())
        }
        with open(CACHE_FILE, 'w', encoding='utf-8') as f:
            json.dump(cache_data, f, ensure_ascii=False, indent=2)
        logger.info(f"已保存 {len(environments)} 个环境到持久化缓存")
    except Exception as e:
        logger.error(f"保存缓存失败: {e}")


def reconcile_cache_with_docker(environments) -> bool:
    """通过 docker ps 获取实际运行状态，同步缓存中环境的状态

    使用容器名称匹配（跨平台安全），不依赖路径格式。
    匹配规则：运行容器名 == 项目名变体  或  以 项目名变体+分隔符 开头。
    返回 bool：是否有状态变更（始终返回 bool）。
    """
    running_names = _get_running_container_names()

    if not running_names:
        updated = 0
        for env in environments:
            if env.get('status') == 'running':
                env['status'] = 'stopped'
                updated += 1
        if updated:
            logger.info("Docker 状态同步：无运行中容器，修正了 %d 个环境状态", updated)
        return updated > 0

    updated = 0
    for env in environments:
        basename = Path(env['name']).name
        variants = _project_name_variants(basename)
        # 精确匹配：容器名 == 变体 或 容器名以 变体+_ 或 变体+- 开头
        is_running = any(
            c == v or c.startswith(v + '_') or c.startswith(v + '-')
            for v in variants for c in running_names
        )
        if is_running and env.get('status') != 'running':
            env['status'] = 'running'
            updated += 1
        elif not is_running and env.get('status') == 'running':
            env['status'] = 'stopped'
            updated += 1

    if updated:
        logger.info(f"Docker 状态同步完成，更新了 {updated} 个环境状态")
    return updated > 0


def _project_name_variants(basename: str) -> set:
    """生成目录名可能的 Docker Compose 项目名变体集合

    Docker Compose v2: 非字母数字/下划线 → 连字符，连续连字符合并
    Docker Compose v1: 去除非字母数字
    容器名: <项目名> + 分隔符(-或_) + <service> + 分隔符 + <副本编号>
    """
    lower = basename.lower()
    # v2: 非 [a-z0-9_] → 连字符，合并连续连字符，去首尾连字符
    v2 = re.sub(r'[^a-z0-9_]', '-', lower)
    v2 = re.sub(r'-{2,}', '-', v2).strip('-')
    # v1: 仅保留字母数字
    v1 = re.sub(r'[^a-z0-9]', '', lower)
    variants = {lower, v1, v2}
    # 连字符版本 → 下划线版本（v1 可能在 v2 基础上把 - 全换成 _）
    if '-' in v2:
        variants.add(v2.replace('-', '_'))
    if '_' in v2:
        variants.add(v2.replace('_', '-'))
    return variants
