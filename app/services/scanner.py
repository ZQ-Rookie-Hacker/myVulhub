# coding: utf-8
import concurrent.futures
from pathlib import Path
from typing import List, Dict, Any

from app.config import get_vulhub_path, logger
from app.utils.helpers import has_exploit, image_files
from app.utils.compose import parse_services_ports, check_docker_images_exist


def get_env_dir_by_name(name: str) -> Path:
    vulhub_path = get_vulhub_path()
    p = (vulhub_path / name).resolve()
    if vulhub_path not in p.parents and p != vulhub_path:
        raise FileNotFoundError("Invalid env path")
    return p


def scan_environments_fs(vulhub_path: Path = None) -> List[Dict[str, Any]]:
    """檔案系統掃描：尋找所有包含 docker-compose.yml 的資料夾"""
    if vulhub_path is None:
        vulhub_path = get_vulhub_path()

    if not vulhub_path.exists():
        raise FileNotFoundError(f"Vulhub path does not exist: {vulhub_path}")

    compose_files = list(vulhub_path.rglob('docker-compose.yml'))
    total = len(compose_files)
    logger.info(f"找到 {total} 個環境，開始並行掃描...")

    max_workers = min(4, max(1, total // 10 + 1))

    def process_single_env(compose_path):
        try:
            env_dir = compose_path.parent
            rel = env_dir.relative_to(vulhub_path).as_posix()
            parts = rel.split('/')
            category = parts[0] if parts else 'unknown'
            cve = parts[-1] if parts else 'unknown'

            services, ports_map = parse_services_ports(compose_path)

            readme_files = [
                env_dir / 'README.md',
                env_dir / 'README.zh-cn.md',
                env_dir / 'README_zh.md'
            ]
            has_readme = readme_files[0].exists()
            has_readme_zh = readme_files[1].exists() or readme_files[2].exists()

            imgs = image_files(env_dir)
            has_docker_images = check_docker_images_exist(compose_path, fast_mode=False)

            return {
                "name": rel,
                "category": category,
                "cve": cve,
                "status": "unknown",
                "ports": ports_map,
                "services": services,
                "has_exploit": has_exploit(env_dir),
                "has_images": bool(imgs),
                "has_readme": has_readme,
                "has_readme_zh": has_readme_zh,
                "has_docker_images": has_docker_images,
            }
        except Exception as e:
            logger.warning(f"扫描环境失败: {compose_path}, 错误: {e}")
            return None

    envs = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_compose = {executor.submit(process_single_env, path): path for path in compose_files}

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


def normalize_env_output(env_data) -> Dict[str, Any]:
    """标准化环境数据输出"""
    if isinstance(env_data, dict):
        return {
            "name": env_data.get("name"),
            "category": env_data.get("category"),
            "cve": env_data.get("cve"),
            "status": env_data.get("status", "unknown"),
            "ports": env_data.get("ports") or {},
            "services": env_data.get("services") or [],
            "has_exploit": bool(env_data.get("has_exploit")),
            "has_images": bool(env_data.get("has_images")),
            "has_readme": bool(env_data.get("has_readme")),
            "has_readme_zh": bool(env_data.get("has_readme_zh")),
            "has_docker_images": bool(env_data.get("has_docker_images", False)),
        }
    else:
        name = getattr(env_data, 'name', None) or getattr(env_data, 'path', None)
        vulhub_path = get_vulhub_path()
        if name and isinstance(name, str) and name.startswith(str(vulhub_path)):
            rel = Path(name).resolve().relative_to(vulhub_path).as_posix()
        else:
            rel = name
        category = getattr(env_data, 'category', None)
        cve = getattr(env_data, 'cve', None)
        status = getattr(env_data, 'status', 'unknown')
        ports = getattr(env_data, 'ports', {}) or {}
        services = getattr(env_data, 'services', []) or []
        has_exploit_val = bool(getattr(env_data, 'has_exploit', False))
        images = getattr(env_data, 'images', []) or []
        has_images_val = bool(images)
        has_readme = bool(getattr(env_data, 'has_readme', False))
        has_readme_zh = bool(getattr(env_data, 'has_readme_zh', False))
        has_docker_images = bool(getattr(env_data, 'has_docker_images', False))

        if (not category or not cve) and isinstance(rel, str):
            parts = rel.split('/')
            if not category and parts:
                category = parts[0]
            if not cve and parts:
                cve = parts[-1]

        return {
            "name": rel,
            "category": category or 'unknown',
            "cve": cve or 'unknown',
            "status": status or 'unknown',
            "ports": ports,
            "services": services,
            "has_exploit": has_exploit_val,
            "has_images": has_images_val,
            "has_readme": has_readme,
            "has_readme_zh": has_readme_zh,
            "has_docker_images": has_docker_images,
        }
