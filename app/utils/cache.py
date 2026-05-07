# coding: utf-8
import json
import hashlib
import subprocess
from pathlib import Path

from app.config import get_vulhub_path, CACHE_FILE, CACHE_TTL_MS, logger
from app.utils.helpers import now_ms


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


def calculate_vulhub_hash():
    try:
        vulhub_path = get_vulhub_path()
        compose_files = list(vulhub_path.rglob('docker-compose.yml'))
        paths_str = ''.join(sorted([str(f.relative_to(vulhub_path)) for f in compose_files]))
        return hashlib.md5(paths_str.encode()).hexdigest()
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


def reconcile_cache_with_docker(environments):
    """通过 docker ps 获取实际运行状态，同步缓存中环境的状态"""
    try:
        result = subprocess.run(
            ['docker', 'ps', '--format',
             '{{.Label "com.docker.compose.project.working_dir"}}'],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=10
        )
    except (subprocess.CalledProcessError, FileNotFoundError, subprocess.TimeoutExpired):
        logger.debug("无法获取 Docker 运行状态，保持缓存原状态")
        return

    vulhub_path = get_vulhub_path()
    running_dirs = set()
    for line in result.stdout.splitlines():
        line = line.strip()
        if line:
            try:
                running_dirs.add(Path(line).resolve())
            except Exception:
                pass

    if not running_dirs:
        return

    updated = 0
    for env in environments:
        try:
            env_dir = (vulhub_path / env['name']).resolve()
            if env_dir in running_dirs:
                if env.get('status') != 'running':
                    env['status'] = 'running'
                    updated += 1
            elif env.get('status') == 'running':
                env['status'] = 'stopped'
                updated += 1
        except Exception:
            pass

    if updated:
        logger.info(f"Docker 状态同步完成，更新了 {updated} 个环境状态")
