# coding: utf-8
import time
import functools
import subprocess
from pathlib import Path

from app.config import logger


def now_ms():
    return int(time.time() * 1000)


def handle_subprocess_errors(tool_name: str):
    """参数化错误装饰器，消除 Docker/Git 两套重复代码"""
    def _safe_decode(data):
        """安全解码 subprocess 输出（兼容 text=True 返回 str 的场景）"""
        if data is None:
            return ""
        if isinstance(data, bytes):
            return data.decode('utf-8', errors='ignore').strip()
        return str(data).strip()

    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            try:
                return func(*args, **kwargs)
            except subprocess.TimeoutExpired:
                logger.error("%s操作超时", tool_name)
                return False, {"error": f"{tool_name}操作超时"}
            except subprocess.CalledProcessError as e:
                error_msg = _safe_decode(e.stderr) or _safe_decode(e.stdout) or str(e)
                logger.error("%s命令执行失败: %s", tool_name, error_msg)
                return False, {"error": f"{tool_name}命令执行失败: {error_msg}"}
            except FileNotFoundError:
                logger.error("%s未安装或不可用", tool_name)
                return False, {"error": f"{tool_name}未安装或不可用"}
            except Exception as e:
                logger.error("%s操作异常: %s", tool_name, str(e))
                return False, {"error": f"{tool_name}操作异常: {str(e)}"}
        return wrapper
    return decorator


# 向后兼容别名
handle_docker_errors = handle_subprocess_errors("Docker")
handle_git_errors = handle_subprocess_errors("Git")


def read_text(p: Path):
    try:
        stat = p.stat()
        if stat.st_size > 1024 * 100:
            with p.open('r', encoding='utf-8', errors='ignore') as f:
                return f.read()
        else:
            return p.read_text(encoding='utf-8', errors='ignore')
    except Exception:
        return ''


def has_exploit(env_dir: Path):
    for sub in ['exploit', 'exploits', 'poc', 'pocs']:
        if (env_dir / sub).exists():
            return True
    exploit_patterns = ['*exploit*.py', '*exploit*.sh', 'poc.py', 'poc.sh', 'exp.py', 'PoC.py']
    for pattern in exploit_patterns:
        try:
            if next(env_dir.glob(pattern), None):
                return True
        except Exception:
            continue
    return False


def get_exploit_files(env_dir: Path):
    seen = set()
    exploit_files = []
    for sub in ['exploit', 'exploits', 'poc', 'pocs']:
        sub_dir = env_dir / sub
        if sub_dir.exists() and sub_dir.is_dir():
            for f in sub_dir.iterdir():
                if f.is_file() and f.suffix in ['.py', '.sh', '.rb', '.go', '.c', '.cpp']:
                    if f not in seen:
                        seen.add(f)
                        exploit_files.append(f)
    for pattern in ['*exploit*.py', '*exploit*.sh', 'poc.py', 'poc.sh', 'exp.py', 'PoC.py']:
        for f in env_dir.glob(pattern):
            if f.is_file() and f not in seen:
                seen.add(f)
                exploit_files.append(f)
    return exploit_files


def image_files(env_dir: Path):
    exts = {'.png', '.jpg', '.jpeg', '.gif', '.webp', '.bmp', '.svg'}
    try:
        return [p for p in env_dir.iterdir() if p.is_file() and p.suffix.lower() in exts]
    except Exception:
        return []
