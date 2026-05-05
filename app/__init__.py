# coding: utf-8
from flask import Flask

from app.config import get_vulhub_path, CACHE_FILE, logger
from app.utils.cache import EnvCache, load_persistent_cache
from app.services.docker import VulhubOperations


def create_app():
    app = Flask(__name__, template_folder='../templates', static_folder='../static')

    # 初始化缓存
    env_cache = EnvCache()

    # 尝试加载持久化缓存
    print(f"Vulhub 路径: {get_vulhub_path()}")
    print(f"缓存文件: {CACHE_FILE}")

    cached_data = load_persistent_cache()
    if cached_data:
        env_cache.set(cached_data)
        print(f"成功载入持久化缓存，共 {len(cached_data)} 个环境")
    else:
        print("未找到有效缓存，将在首次请求时扫描")

    # 初始化 Docker 操作服务
    ops = VulhubOperations()
    print(f"使用 Docker Compose 命令: {' '.join(ops.compose_cmd)}")

    # 注入到 app.config 供路由使用
    app.config['ENV_CACHE'] = env_cache
    app.config['OPS'] = ops
    app.config['VULHUB_PATH'] = get_vulhub_path()
    app.config['CACHE_FILE'] = CACHE_FILE

    # 注册 Blueprint
    from app.routes.main import main_bp
    from app.routes.api import api_bp
    app.register_blueprint(main_bp)
    app.register_blueprint(api_bp)

    return app
