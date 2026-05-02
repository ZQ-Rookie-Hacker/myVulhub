# coding: utf-8
import time
import functools
import subprocess
from pathlib import Path
from flask import jsonify

from app.config import logger


def now_ms():
    return int(time.time() * 1000)


def api_response(success, data=None, message="", code=200):
    response = {
        "success": success,
        "message": message,
        "timestamp": now_ms(),
        "data": data
    }
    return jsonify(response), code


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


def handle_docker_errors(func):
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except subprocess.TimeoutExpired:
            logger.error("Docker操作超时")
            return False, {"error": "Docker操作超时"}
        except subprocess.CalledProcessError as e:
            try:
                error_msg = e.stderr.decode('utf-8', errors='ignore').strip() if e.stderr else ""
                if not error_msg:
                    error_msg = e.stdout.decode('utf-8', errors='ignore').strip() if e.stdout else ""
                if not error_msg:
                    error_msg = str(e)
            except Exception:
                error_msg = str(e)
            logger.error(f"Docker命令执行失败: {error_msg}")
            return False, {"error": f"Docker命令执行失败: {error_msg}"}
        except FileNotFoundError:
            logger.error("Docker未安装或不可用")
            return False, {"error": "Docker未安装或不可用"}
        except Exception as e:
            logger.error(f"Docker操作异常: {str(e)}")
            return False, {"error": f"Docker操作异常: {str(e)}"}
    return wrapper


def handle_git_errors(func):
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except subprocess.TimeoutExpired:
            logger.error("Git操作超时")
            return False, {"error": "Git操作超时"}
        except subprocess.CalledProcessError as e:
            try:
                error_msg = e.stderr.decode('utf-8', errors='ignore').strip() if e.stderr else ""
                if not error_msg:
                    error_msg = e.stdout.decode('utf-8', errors='ignore').strip() if e.stdout else ""
                if not error_msg:
                    error_msg = str(e)
            except Exception:
                error_msg = str(e)
            logger.error(f"Git命令执行失败: {error_msg}")
            return False, {"error": f"Git命令执行失败: {error_msg}"}
        except FileNotFoundError:
            logger.error("Git未安装或不可用")
            return False, {"error": "Git未安装或不可用"}
        except Exception as e:
            logger.error(f"Git操作异常: {str(e)}")
            return False, {"error": f"Git操作异常: {str(e)}"}
    return wrapper


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
    exploit_files = []
    for sub in ['exploit', 'exploits', 'poc', 'pocs']:
        sub_dir = env_dir / sub
        if sub_dir.exists() and sub_dir.is_dir():
            for f in sub_dir.iterdir():
                if f.is_file() and f.suffix in ['.py', '.sh', '.rb', '.go', '.c', '.cpp']:
                    exploit_files.append(f)
    for pattern in ['*exploit*.py', '*exploit*.sh', 'poc.py', 'poc.sh', 'exp.py', 'PoC.py']:
        for f in env_dir.glob(pattern):
            if f.is_file():
                exploit_files.append(f)
    return exploit_files


def image_files(env_dir: Path):
    exts = {'.png', '.jpg', '.jpeg', '.gif', '.webp', '.bmp', '.svg'}
    try:
        return [p for p in env_dir.iterdir() if p.is_file() and p.suffix.lower() in exts]
    except Exception:
        return []
