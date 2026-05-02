# coding: utf-8
import os
import json
import logging
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger('vulhub_manager')

APP_CONFIG_FILE = Path.home() / '.vulhub_manager_app_config.json'
CACHE_FILE = Path.home() / '.vulhub_manager_cache.json'
GIT_CONFIG_FILE = Path.home() / '.vulhub_manager_git_config.json'

CACHE_TTL_MS = 24 * 60 * 60 * 1000

DOCKER_TIMEOUT = 90
DOCKER_STOP_TIMEOUT = 20
DOCKER_IMAGE_CHECK_TIMEOUT = 2
GIT_OPERATION_TIMEOUT = 120


def get_vulhub_path() -> Path:
    """获取 vulhub 路径，优先级：持久化配置 > 环境变量 > 默认值"""
    if APP_CONFIG_FILE.exists():
        try:
            with open(APP_CONFIG_FILE, 'r', encoding='utf-8') as f:
                config = json.load(f)
            saved_path = config.get('vulhub_path')
            if saved_path:
                p = Path(saved_path).resolve()
                if p.exists() and p.is_dir():
                    return p
        except Exception:
            pass

    env_path = os.environ.get('VULHUB_PATH')
    if env_path:
        p = Path(env_path).resolve()
        if p.exists() and p.is_dir():
            return p

    return Path('../vulhub').resolve()


def set_vulhub_path(new_path: str):
    """设置并持久化 vulhub 路径，返回 (success, message)"""
    try:
        p = Path(new_path).resolve()
        if not p.exists():
            return False, f"路径不存在: {p}"
        if not p.is_dir():
            return False, f"路径不是目录: {p}"

        config = {}
        if APP_CONFIG_FILE.exists():
            try:
                with open(APP_CONFIG_FILE, 'r', encoding='utf-8') as f:
                    config = json.load(f)
            except Exception:
                pass

        config['vulhub_path'] = str(p)

        with open(APP_CONFIG_FILE, 'w', encoding='utf-8') as f:
            json.dump(config, f, indent=2, ensure_ascii=False)

        return True, str(p)
    except Exception as e:
        return False, f"保存配置失败: {str(e)}"
