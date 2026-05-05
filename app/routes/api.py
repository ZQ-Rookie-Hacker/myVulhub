# coding: utf-8
import base64
import json
import subprocess
import time
from pathlib import Path
from flask import Blueprint, jsonify, request, current_app

from app.config import get_vulhub_path, set_vulhub_path, CACHE_FILE, GIT_CONFIG_FILE, logger
from app.utils.helpers import read_text, get_exploit_files, image_files
from app.utils.cache import load_persistent_cache, save_persistent_cache
from app.services.scanner import scan_environments_fs, get_env_dir_by_name, normalize_env_output

api_bp = Blueprint('api', __name__, url_prefix='/api')

# 尝试导入 markdown
try:
    import markdown as md_lib
except Exception:
    md_lib = None



def _load_git_config():
    default_config = {
        "remote_url": "https://github.com/vulhub/vulhub.git",
        "use_proxy": False,
        "last_updated": None
    }
    if GIT_CONFIG_FILE.exists():
        try:
            with open(GIT_CONFIG_FILE, 'r', encoding='utf-8') as f:
                config = json.load(f)
                return {**default_config, **config}
        except Exception:
            return default_config
    return default_config


def _save_git_config(config):
    try:
        config['last_updated'] = time.time()
        with open(GIT_CONFIG_FILE, 'w', encoding='utf-8') as f:
            json.dump(config, f, indent=2, ensure_ascii=False)
        return True
    except Exception:
        return False


# ====== API 路由 ======

@api_bp.route('/scan')
def api_scan():
    use_cache = request.args.get('cache', 'true').lower() == 'true'
    cache = current_app.config['ENV_CACHE']

    if use_cache and cache.is_valid():
        return jsonify(cache.get())

    if use_cache:
        cached_envs = load_persistent_cache()
        if cached_envs:
            cache.set(cached_envs)
            return jsonify(cached_envs)

    logger.info("执行完整扫描...")
    try:
        envs = scan_environments_fs()
    except FileNotFoundError:
        logger.warning(f"Vulhub路径不存在，返回空列表")
        return jsonify([])
    except Exception as e:
        logger.error(f"扫描失败: {e}")
        return jsonify({"error": f"扫描失败: {str(e)}"}), 500

    out = [normalize_env_output(e) for e in envs]

    cache.set(out)
    save_persistent_cache(out)

    return jsonify(out)


@api_bp.route('/stats')
def api_stats():
    data = current_app.config['ENV_CACHE'].get() or []
    total = len(data)
    running = sum(1 for x in data if x.get("status") == "running")
    with_exploit = sum(1 for x in data if x.get("has_exploit"))
    with_images = sum(1 for x in data if x.get("has_docker_images"))
    cats = {}
    for x in data:
        cats[x["category"]] = cats.get(x["category"], 0) + 1
    return jsonify({
        "total": total,
        "running": running,
        "with_exploit": with_exploit,
        "with_images": with_images,
        "categories": cats
    })


@api_bp.route('/env/<path:name>')
def api_env_detail(name: str):
    try:
        env_dir = get_env_dir_by_name(name)
    except Exception:
        return jsonify({"error": "not found"}), 404

    compose_path = env_dir / 'docker-compose.yml'
    compose_text = read_text(compose_path)

    images_data = []
    for img_path in image_files(env_dir)[:5]:
        try:
            if img_path.stat().st_size < 5 * 1024 * 1024:
                with open(img_path, 'rb') as f:
                    b64 = base64.b64encode(f.read()).decode()
                ext = (img_path.suffix or ".png")[1:].lower()
                images_data.append({
                    "name": img_path.name,
                    "data": f"data:image/{ext};base64,{b64}"
                })
        except Exception:
            pass

    exploit_file_names = [f.name for f in get_exploit_files(env_dir)]

    parts = name.split('/')
    category = parts[0] if parts else 'unknown'
    cve = parts[-1] if parts else 'unknown'

    return jsonify({
        "name": name,
        "category": category,
        "cve": cve,
        "compose": compose_text,
        "images": images_data,
        "exploit_files": exploit_file_names
    })


@api_bp.route('/readme/<path:name>')
def api_readme(name: str):
    try:
        env_dir = get_env_dir_by_name(name)
    except Exception:
        return jsonify({"html": ""})

    md_path = None
    for cand in ['README.zh-cn.md', 'README.zh-CN.md', 'README_zh.md', 'README.md', 'README.MD']:
        p = env_dir / cand
        if p.exists():
            md_path = p
            break

    md_text = read_text(md_path) if md_path else ""
    html = md_lib.markdown(md_text, extensions=['extra', 'tables', 'fenced_code']) if md_text and md_lib else ""
    return jsonify({"html": html})


@api_bp.route('/exploit/<path:name>')
def api_exploit(name: str):
    try:
        env_dir = get_env_dir_by_name(name)
    except Exception:
        return jsonify([]), 404

    exploits = []
    for exploit_path in get_exploit_files(env_dir):
        try:
            content = read_text(exploit_path)
            if content:
                usage = ""
                lines = content.splitlines()
                for line in lines[:20]:
                    if 'usage:' in line.lower() or 'example:' in line.lower():
                        usage = line
                        break

                exploits.append({
                    "filename": exploit_path.name,
                    "path": str(exploit_path.relative_to(env_dir)),
                    "content": content[:10000],
                    "size": len(content),
                    "lines": len(lines),
                    "usage": usage
                })
        except Exception:
            pass

    return jsonify(exploits)


@api_bp.route('/start', methods=['POST'])
def api_start():
    ops = current_app.config['OPS']
    cache = current_app.config['ENV_CACHE']
    data = request.get_json(force=True)
    name = (data.get('name') or '').strip()
    if not name:
        return jsonify({"success": False, "error": "缺少环境名称"}), 400
    use_proxy = data.get('use_proxy', False)
    ok, info = ops.start(name, use_proxy=use_proxy)
    if ok and cache.is_valid():
        for e in cache.get():
            if e.get("name") == name:
                e["status"] = "running"
                break
    return jsonify({"success": ok, **(info or {})})


@api_bp.route('/stop', methods=['POST'])
def api_stop():
    ops = current_app.config['OPS']
    cache = current_app.config['ENV_CACHE']
    data = request.get_json(force=True)
    name = (data.get('name') or '').strip()
    if not name:
        return jsonify({"success": False, "error": "缺少环境名称"}), 400
    ok, info = ops.stop(name)
    if ok and cache.is_valid():
        for e in cache.get():
            if e.get("name") == name:
                e["status"] = "stopped"
                break
    return jsonify({"success": ok, **(info or {})})


@api_bp.route('/remove-images', methods=['POST'])
def api_remove_images():
    ops = current_app.config['OPS']
    data = request.get_json(force=True)
    name = (data.get('name') or '').strip()
    if not name:
        return jsonify({"success": False, "error": "缺少环境名称"}), 400
    ok, info = ops.remove_images(name)
    return jsonify({"success": ok, **(info or {})})


@api_bp.route('/check-images')
def api_check_images():
    ops = current_app.config['OPS']
    name = request.args.get('name', '')
    ok, info = ops.check_images(name)
    return jsonify({"success": ok, **(info or {})})


@api_bp.route('/pull-stream')
def api_pull_stream():
    ops = current_app.config['OPS']
    name = request.args.get('name', '')
    use_proxy = request.args.get('proxy', 'false').lower() == 'true'

    def gen():
        exit_ok = None
        for line in ops.pull_images_stream(name, use_proxy=use_proxy):
            if line.startswith('[EXIT_CODE:0]'):
                exit_ok = True
            elif line.startswith('[EXIT_CODE:'):
                exit_ok = False
                code = line[11:-1] if line.endswith(']') else line[11:]
                yield f"event: log\ndata: [Error] 镜像拉取失败，退出码: {code}\n\n"
            else:
                yield f"event: log\ndata: {line}\n\n"
        if exit_ok is True:
            yield "event: done\ndata: ok\n\n"
        else:
            yield "event: done\ndata: error\n\n"

    return current_app.response_class(gen(), mimetype='text/event-stream')


@api_bp.route('/wait-ready')
def api_wait_ready():
    ops = current_app.config['OPS']
    name = request.args.get('name', '')
    timeout = int(request.args.get('timeout', '20'))
    ok, info = ops.wait_ready(name, timeout=timeout)
    return jsonify({"success": ok, **(info or {})})


@api_bp.route('/running')
def api_running():
    try:
        result = subprocess.run(
            ['docker', 'ps', '--format', '{{json .}}'],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )
        containers = []
        for line in result.stdout.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except Exception:
                continue
            containers.append({
                "id": (obj.get("ID") or "")[:12],
                "name": obj.get("Names") or "",
                "image": obj.get("Image") or "",
                "status": obj.get("Status") or "",
                "ports": obj.get("Ports") or ""
            })

        return jsonify({"success": True, "containers": containers})
    except subprocess.CalledProcessError as e:
        return jsonify({
            "success": False,
            "error": f"docker ps 失败：{e.stderr.strip() or e.stdout.strip()}"
        }), 500
    except FileNotFoundError:
        return jsonify({
            "success": False,
            "error": "找不到 docker 指令，请确认已安装 Docker 并在 PATH 中。"
        }), 500


@api_bp.route('/git-config', methods=['GET', 'POST'])
def api_git_config():
    ops = current_app.config['OPS']

    if request.method == 'GET':
        try:
            config = _load_git_config()
            ok, stdout, stderr = ops.git_ops._run_git(['remote', 'get-url', 'origin'])
            if ok and stdout.strip():
                config['remote_url'] = stdout.strip()
            return jsonify({
                "success": True,
                "remote_url": config['remote_url'],
                "use_proxy": config['use_proxy']
            })
        except Exception as e:
            return jsonify({"success": False, "error": str(e)})
    else:
        data = request.get_json(force=True)
        remote_url = data.get('remote_url')
        use_proxy = data.get('use_proxy', False)
        protocol = data.get('protocol', 'https')

        if not remote_url:
            return jsonify({"success": False, "error": "远程仓库 URL 不能为空"})

        try:
            if not (get_vulhub_path() / ".git").exists():
                ok, _, err = ops.git_ops._run_git(['init'])
                if not ok:
                    return jsonify({"success": False, "error": f"Git 初始化失败: {err}"})
                ok, _, err = ops.git_ops._run_git(['remote', 'add', 'origin', remote_url])
                if not ok:
                    return jsonify({"success": False, "error": f"添加远程仓库失败: {err}"})
            else:
                ok, _, err = ops.git_ops._run_git(['remote', 'set-url', 'origin', remote_url])
                if not ok:
                    return jsonify({"success": False, "error": f"设置远程仓库失败: {err}"})

            config = {
                "remote_url": remote_url,
                "use_proxy": use_proxy,
                "protocol": protocol
            }

            if _save_git_config(config):
                return jsonify({"success": True, "message": "Git 配置保存成功"})
            else:
                return jsonify({"success": False, "error": "保存配置文件失败"})
        except Exception as e:
            return jsonify({"success": False, "error": f"保存配置失败: {str(e)}"})


@api_bp.route('/git-sync', methods=['POST'])
def api_git_sync():
    ops = current_app.config['OPS']
    data = request.get_json(force=True)
    method = data.get('method', 'https')
    remote_url = data.get('remote_url')

    if method not in ['ssh', 'https', 'https_proxy', 'gh']:
        return jsonify({"success": False, "error": "不支持的同步方式"})

    if method == 'gh':
        return jsonify(_sync_with_gh_cli(remote_url))

    ok, info = ops.git_ops.sync_vulhub(method, remote_url)
    return jsonify({"success": ok, **(info or {})})


def _sync_with_gh_cli(remote_url: str = None):
    try:
        result = subprocess.run(['gh', '--version'], capture_output=True, text=True)
        if result.returncode != 0:
            return {"success": False, "error": "未安装 GitHub CLI (gh)"}

        vulhub_path = get_vulhub_path()

        if not (vulhub_path / ".git").exists():
            if remote_url:
                repo_url = remote_url
            else:
                repo_url = "vulhub/vulhub"
            # 空目录会导致 clone 失败，先删除
            if vulhub_path.exists() and not any(vulhub_path.iterdir()):
                try:
                    vulhub_path.rmdir()
                except Exception:
                    pass
            cmd = ['gh', 'repo', 'clone', repo_url, str(vulhub_path)]
            result = subprocess.run(cmd, capture_output=True, text=True)
        else:
            cmd = ['gh', 'repo', 'sync']
            result = subprocess.run(cmd, cwd=str(vulhub_path), capture_output=True, text=True)

        if result.returncode == 0:
            return {"success": True, "message": "GitHub CLI 同步成功", "output": result.stdout}
        else:
            return {"success": False, "error": f"GitHub CLI 同步失败: {result.stderr}"}

    except Exception as e:
        return {"success": False, "error": f"GitHub CLI 同步异常: {str(e)}"}


@api_bp.route('/refresh-cache', methods=['POST'])
def api_refresh_cache():
    cache = current_app.config['ENV_CACHE']
    try:
        cache.clear()

        if CACHE_FILE.exists():
            CACHE_FILE.unlink()
            logger.info("已删除持久化缓存文件")

        logger.info("强制重新扫描所有环境...")
        envs = scan_environments_fs()

        out = [normalize_env_output(e) for e in envs]

        cache.set(out)
        save_persistent_cache(out)

        return jsonify({"success": True, "count": len(out)})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@api_bp.route('/vulhub-path', methods=['GET', 'POST'])
def api_vulhub_path():
    if request.method == 'GET':
        current_path = str(get_vulhub_path())
        return jsonify({
            "success": True,
            "path": current_path,
            "exists": Path(current_path).exists()
        })

    data = request.get_json(force=True)
    new_path = data.get('path', '').strip()
    if not new_path:
        return jsonify({"success": False, "error": "路径不能为空"}), 400

    ok, msg = set_vulhub_path(new_path)
    if not ok:
        return jsonify({"success": False, "error": msg}), 400

    current_app.config['VULHUB_PATH'] = Path(msg)

    cache = current_app.config['ENV_CACHE']
    cache.clear()
    if CACHE_FILE.exists():
        try:
            CACHE_FILE.unlink()
        except Exception:
            pass

    ops = current_app.config['OPS']
    ops.git_ops.vulhub_path = Path(msg)

    return jsonify({"success": True, "path": msg, "message": "路径已更新，缓存已清除"})
