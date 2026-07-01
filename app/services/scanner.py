# coding: utf-8
import os
import concurrent.futures
from pathlib import Path
from typing import List, Dict, Any

from app.config import get_vulhub_path, logger
from app.utils.helpers import has_exploit, image_files
from app.utils.compose import parse_services_ports, check_docker_images_exist, get_local_images


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

    docker_images = get_local_images()
    if docker_images:
        logger.info(f"已獲取本地 {len(docker_images)} 個 Docker 鏡像，將用於快速檢查")

    max_workers = min(8, (os.cpu_count() or 4), max(1, total // 15 + 1))

    def process_single_env(compose_path):
        try:
            env_dir = compose_path.parent
            rel = env_dir.relative_to(vulhub_path).as_posix()
            parts = rel.split('/')
            category = parts[0] if parts else 'unknown'
            cve = parts[-1] if parts else 'unknown'

            services, ports_map = parse_services_ports(compose_path)

            has_readme = any((env_dir / n).exists() for n in ('README.md', 'README.MD'))
            has_readme_zh = any((env_dir / n).exists() for n in ('README.zh-cn.md', 'README.zh-CN.md', 'README_zh.md'))

            imgs = image_files(env_dir)
            has_docker_images = check_docker_images_exist(compose_path, local_images=docker_images)

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
    """标准化环境数据输出（仅处理 dict 类型，扫描器始终返回 dict）"""
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
