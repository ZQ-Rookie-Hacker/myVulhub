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
DOCKER_IMAGE_CHECK_TIMEOUT = 5
DOCKER_PS_TIMEOUT = 10
DOCKER_COMPOSE_LS_TIMEOUT = 5
GIT_OPERATION_TIMEOUT = 120

# ---- vulhub 路径解析（每次调用都实时解析，不做缓存） ----
# 不缓存的原因：配置可能在运行时被 Web UI 修改、被外部编辑、
# 或被其他 worker 进程更新；缓存旧值会导致"更改路径后仍扫描旧目录"。
# 解析成本仅为一次小文件的读取 + 存在性检查，可忽略。


def get_vulhub_path() -> Path:
    """获取 vulhub 路径，优先级：持久化配置 > 环境变量 > 默认值"""
    if APP_CONFIG_FILE.exists():
        try:
            with open(APP_CONFIG_FILE, 'r', encoding='utf-8') as f:
                config = json.load(f)
            saved_path = config.get('vulhub_path')
            if saved_path:
                p = Path(saved_path).expanduser().resolve()
                if p.exists() and p.is_dir():
                    return p
        except Exception:
            pass

    env_path = os.environ.get('VULHUB_PATH')
    if env_path:
        p = Path(env_path).expanduser().resolve()
        if p.exists() and p.is_dir():
            return p

    return Path('../vulhub').resolve()


def get_configured_vulhub_path() -> str:
    """获取配置的 vulhub 路径原始值（不做存在性过滤，用于前端诊断展示）

    优先级与 get_vulhub_path 一致：持久化配置 > 环境变量 > 默认值。
    get_vulhub_path 在配置的路径不存在时会静默回退，
    用本函数把真实配置值暴露给 /api/vulhub-path，便于排查"列表为空"问题。
    """
    if APP_CONFIG_FILE.exists():
        try:
            with open(APP_CONFIG_FILE, 'r', encoding='utf-8') as f:
                config = json.load(f)
            saved_path = config.get('vulhub_path')
            if saved_path:
                return str(Path(saved_path).resolve())
        except Exception:
            pass

    env_path = os.environ.get('VULHUB_PATH')
    if env_path:
        return str(Path(env_path).resolve())

    return str(Path('../vulhub').resolve())


def set_vulhub_path(new_path: str):
    """设置并持久化 vulhub 路径，返回 (success, message)

    get_vulhub_path 每次调用都实时读取配置文件，因此写入后
    本进程与所有其他 worker 进程立即生效，无需额外失效缓存。
    """
    try:
        p = Path(new_path).expanduser().resolve()
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
