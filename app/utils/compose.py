# coding: utf-8
import re
import subprocess
from pathlib import Path
from typing import List, Dict, Tuple

from app.config import logger, DOCKER_IMAGE_CHECK_TIMEOUT
from app.utils.helpers import read_text

try:
    import yaml
except Exception:
    yaml = None


def parse_services_ports(compose_path: Path) -> Tuple[List[str], Dict[str, str]]:
    """从 docker-compose.yml 解析 service 名称与 host 端口"""
    services, ports_map = [], {}
    if not compose_path.exists():
        return services, ports_map

    if yaml:
        try:
            data = yaml.safe_load(read_text(compose_path)) or {}
            svcs = data.get('services') or {}
            for svc_name, svc_cfg in svcs.items():
                services.append(str(svc_name))
                port_list = svc_cfg.get('ports') or []
                host_ports = []
                for item in port_list:
                    if isinstance(item, str):
                        parts = item.split(':')
                        if len(parts) >= 2:
                            try:
                                host_ports.append(str(int(parts[-2])))
                            except Exception:
                                pass
                        else:
                            host_ports.append(parts[0])
                    elif isinstance(item, dict):
                        hp = item.get('published')
                        if hp:
                            host_ports.append(str(hp))
                if host_ports:
                    ports_map[svc_name] = host_ports[0]
        except Exception:
            pass

    return services, ports_map


def check_docker_images_exist(compose_path: Path, local_images: set = None) -> bool:
    """检查 docker-compose.yml 中定义的镜像是否全部存在于本地

    优先使用预获取的 local_images set；未提供时通过 docker images 命令查询。
    返回 False 当：任一镜像缺失、无法解析出镜像列表、或 Docker 不可达。
    """
    images_to_check = _parse_image_names(compose_path)
    if not images_to_check:
        return False

    if local_images is not None:
        return all(img in local_images for img in images_to_check)

    # 回退：调用 docker images 命令
    try:
        result = subprocess.run(
            ['docker', 'images', '--format', '{{.Repository}}:{{.Tag}}'],
            capture_output=True,
            timeout=DOCKER_IMAGE_CHECK_TIMEOUT,
            text=True
        )
        if result.returncode == 0:
            local = {ln for ln in result.stdout.strip().split('\n') if ln}
            return all(img in local for img in images_to_check)
    except Exception as e:
        logger.warning(f"docker images 命令失败，回退到逐个检查: {e}")

    return _check_images_one_by_one(images_to_check)


def get_local_images() -> set:
    """获取本地所有 Docker 镜像集合（标签格式），失败返回空 set"""
    try:
        result = subprocess.run(
            ['docker', 'images', '--format', '{{.Repository}}:{{.Tag}}'],
            capture_output=True,
            timeout=DOCKER_IMAGE_CHECK_TIMEOUT,
            text=True
        )
        if result.returncode == 0:
            return {ln for ln in result.stdout.strip().split('\n') if ln}
    except Exception:
        pass
    return set()


def _parse_image_names(compose_path: Path) -> List[str]:
    """从 compose 文件中提取镜像名称"""
    images = []
    if yaml and compose_path.exists():
        try:
            data = yaml.safe_load(read_text(compose_path)) or {}
            svcs = data.get('services') or {}
            for svc_name, svc_cfg in svcs.items():
                if 'image' in svc_cfg:
                    images.append(svc_cfg['image'])
        except Exception as e:
            logger.warning(f"解析YAML失败: {e}")

    if not images:
        try:
            content = read_text(compose_path)
            found = re.findall(r'^\s*image:\s*([^\s#]+)', content, re.MULTILINE)
            images = found
        except Exception as e:
            logger.warning(f"正则解析失败: {e}")

    return images


def _check_images_one_by_one(images: List[str]) -> bool:
    """逐个检查镜像是否存在"""
    for image in images:
        try:
            result = subprocess.run(
                ['docker', 'image', 'inspect', image],
                capture_output=True,
                timeout=DOCKER_IMAGE_CHECK_TIMEOUT,
                text=True
            )
            if result.returncode != 0:
                logger.debug(f"镜像不存在: {image}")
                return False
        except Exception as e:
            logger.error(f"检查镜像失败: {image}, 错误: {e}")
            return False
    return True


def fallback_parse_images(env_dir: Path) -> List[str]:
    """正则回退解析 docker-compose.yml 中的镜像"""
    images: List[str] = []
    compose_path = env_dir / 'docker-compose.yml'
    try:
        for ln in compose_path.read_text(encoding='utf-8', errors='ignore').splitlines():
            m = re.search(r'^\s*image\s*:\s*([^\s#]+)', ln)
            if m:
                images.append(m.group(1).strip())
    except Exception:
        pass
    seen = set()
    uniq = []
    for x in images:
        if x not in seen:
            seen.add(x)
            uniq.append(x)
    return uniq
