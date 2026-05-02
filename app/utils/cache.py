# coding: utf-8
import json
import hashlib
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
        print(f"已保存 {len(environments)} 个环境到持久化缓存")
    except Exception as e:
        print(f"保存缓存失败: {e}")
