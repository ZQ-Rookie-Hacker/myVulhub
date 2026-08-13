# coding: utf-8
import json
import hashlib
import os
import re
import subprocess
import threading
from pathlib import Path

from app.config import get_vulhub_path, CACHE_FILE, CACHE_TTL_MS, DOCKER_PS_TIMEOUT, logger
from app.utils.helpers import now_ms

# Docker 状态短期缓存，避免同一请求周期内多次调用。
# 值语义：data=None 表示"尚未获取或获取失败（状态未知）"，
#         data=set()/[] 表示"确认无结果"，两者必须严格区分，
#         否则 Docker 瞬时故障会把所有 running 状态误清空。
# 失败结果同样缓存 TTL 时间，避免 Docker 不可用时每次请求都阻塞等待超时。
_DOCKER_STATE_CACHE_TTL_MS = 2000  # 2 秒

_docker_ps_cache = {"data": None, "ts": 0}
_docker_compose_ls_cache = {"data": None, "ts": 0, "authoritative": False}
_docker_project_labels_cache = {"data": None, "ts": 0}


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


def invalidate_docker_state_cache():
    """启停/删除镜像等改变 Docker 实际状态的操作后，立即失效状态短期缓存，
    避免基于过期快照把刚启动的环境误判为 stopped（或反之）。"""
    global _docker_ps_cache, _docker_compose_ls_cache, _docker_project_labels_cache
    _docker_ps_cache = {"data": None, "ts": 0}
    _docker_compose_ls_cache = {"data": None, "ts": 0, "authoritative": False}
    _docker_project_labels_cache = {"data": None, "ts": 0}


def _get_running_container_names():
    """获取当前运行中的容器名称集合（带 2 秒短期缓存）

    返回 set | None：None 表示 docker ps 执行失败（状态未知），
    与"确认没有运行容器"的 set() 严格区分。
    """
    global _docker_ps_cache
    cache = _docker_ps_cache
    now = now_ms()
    if now - cache["ts"] < _DOCKER_STATE_CACHE_TTL_MS:
        return cache["data"]

    names = None
    try:
        result = subprocess.run(
            ['docker', 'ps', '--format', '{{.Names}}'],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=DOCKER_PS_TIMEOUT
        )
        names = {ln.strip().lower() for ln in result.stdout.splitlines() if ln.strip()}
    except (subprocess.CalledProcessError, FileNotFoundError, subprocess.TimeoutExpired) as e:
        logger.warning(f"docker ps 执行失败，运行状态视为未知: {e}")

    # 查询期间若状态缓存被失效重建（启停操作并发），丢弃本次过期结果，
    # 避免把旧快照写回新缓存导致刚启停的环境被误判
    if _docker_ps_cache is cache:
        cache["data"] = names
        cache["ts"] = now
    return names


def _norm_path(p: str) -> str:
    """路径归一化：统一分隔符 + 忽略大小写，用于跨平台比对 compose 文件路径"""
    return p.strip().replace('\\', '/').lower().rstrip('/')


def _atomic_write_json(path: Path, payload: dict):
    """原子写入 JSON：先写唯一临时文件再 os.replace

    避免并发写（多线程 Flask 下 start 与 scan 落盘可能重叠）互相覆盖写坏文件，
    也避免进程崩溃时留下半截 JSON 导致状态文件损坏。
    """
    tmp = path.with_name(f"{path.name}.tmp.{os.getpid()}.{threading.get_ident()}")
    try:
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        tmp.replace(path)
    finally:
        try:
            if tmp.exists():
                tmp.unlink()
        except OSError:
            pass


def _get_compose_ls_projects():
    """通过 docker compose ls 获取 Compose 项目列表（带 2 秒短期缓存）

    返回 (projects, authoritative)：
    - projects: [{"name", "running", "config_files"}]，命令失败返回 None
    - authoritative: True 表示拿到了"全部项目"清单（--all 生效），
      清单中不存在即可确认"未运行"，允许将缓存中的 running 下调为 stopped；
      False 表示清单仅含运行中的项目（--all 不可用），缺失不代表未运行。
    """
    global _docker_compose_ls_cache
    cache = _docker_compose_ls_cache
    now = now_ms()
    if now - cache["ts"] < _DOCKER_STATE_CACHE_TTL_MS:
        return cache["data"], cache["authoritative"]

    projects = None
    authoritative = False
    # 优先 --all（全量清单，最权威）；旧版本不支持时退化为仅运行中项目清单
    for use_all in (True, False):
        cmd = ['docker', 'compose', 'ls', '--format', 'json']
        if use_all:
            cmd.insert(3, '--all')
        try:
            result = subprocess.run(
                cmd,
                check=False,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=DOCKER_PS_TIMEOUT
            )
        except (FileNotFoundError, subprocess.TimeoutExpired) as e:
            logger.warning(f"docker compose ls 执行失败，Compose 项目状态视为未知: {e}")
            break
        if result.returncode != 0:
            continue

        items = []
        for line in result.stdout.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except Exception:
                continue
            raw_config = obj.get("ConfigFiles") or ""
            items.append({
                "name": (obj.get("Name") or "").strip().lower(),
                "running": bool(re.match(r'^running', (obj.get("Status") or "").strip(), re.IGNORECASE)),
                "config_files": [_norm_path(p) for p in raw_config.split(',') if p.strip()],
            })
        projects = items
        authoritative = use_all
        break

    if projects is None:
        logger.warning("docker compose ls 未能获取任何项目清单（--all 与默认模式均失败）")
    authoritative = authoritative and projects is not None
    # 同 docker ps 缓存：查询期间被失效则丢弃过期结果
    if _docker_compose_ls_cache is cache:
        cache["data"] = projects
        cache["authoritative"] = authoritative
        cache["ts"] = now
    return projects, authoritative


def _get_project_labels():
    """获取运行中容器的 Compose 项目名标签集合（com.docker.compose.project）

    该标签 compose v1/v2 都会写入，是比容器名更可靠的项目名信号。
    失败返回 None（区别于确认无结果的 set()）。
    """
    global _docker_project_labels_cache
    cache = _docker_project_labels_cache
    now = now_ms()
    if now - cache["ts"] < _DOCKER_STATE_CACHE_TTL_MS:
        return cache["data"]

    labels = None
    try:
        result = subprocess.run(
            ['docker', 'ps', '--filter', 'label=com.docker.compose.project',
             '--format', '{{.Label "com.docker.compose.project"}}'],
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=DOCKER_PS_TIMEOUT
        )
        if result.returncode == 0:
            labels = {ln.strip().lower() for ln in result.stdout.splitlines() if ln.strip()}
    except (FileNotFoundError, subprocess.TimeoutExpired) as e:
        logger.warning(f"docker ps 项目标签查询失败: {e}")

    # 同 docker ps 缓存：查询期间被失效则丢弃过期结果
    if _docker_project_labels_cache is cache:
        cache["data"] = labels
        cache["ts"] = now
    return labels


def get_running_containers_json():
    """获取运行中容器列表（JSON 格式），供 /api/running 复用"""
    try:
        result = subprocess.run(
            ['docker', 'ps', '--format', '{{json .}}'],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=DOCKER_PS_TIMEOUT
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
        return containers
    except (subprocess.CalledProcessError, FileNotFoundError, subprocess.TimeoutExpired):
        return []


def calculate_vulhub_hash():
    """计算 vulhub 目录结构哈希（sha256，仅取前 16 位用于快速比对）"""
    try:
        vulhub_path = get_vulhub_path()
        compose_files = list(vulhub_path.rglob('docker-compose.yml'))
        paths_str = ''.join(sorted([str(f.relative_to(vulhub_path)) for f in compose_files]))
        return hashlib.sha256(paths_str.encode()).hexdigest()[:16]
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
        _atomic_write_json(CACHE_FILE, cache_data)
        logger.info(f"已保存 {len(environments)} 个环境到持久化缓存")
    except Exception as e:
        logger.error(f"保存缓存失败: {e}")


def update_persistent_cache_entry(name: str, status: str) -> bool:
    """直接更新持久化缓存文件中指定环境的状态（不校验 TTL/哈希）

    用于启停操作后立即落盘：即使内存缓存不可用（新进程/多 worker 部署），
    也能保证服务重启或页面重开后状态不丢失。
    """
    try:
        if not CACHE_FILE.exists():
            return False
        with open(CACHE_FILE, 'r', encoding='utf-8') as f:
            cache_data = json.load(f)

        updated = False
        for env in cache_data.get('environments', []):
            if env.get('name') == name:
                env['status'] = status
                updated = True
                break
        if not updated:
            return False

        _atomic_write_json(CACHE_FILE, cache_data)
        logger.info(f"已更新持久化缓存: {name} -> {status}")
        return True
    except Exception as e:
        logger.error(f"更新持久化缓存失败: {e}")
        return False


def reconcile_cache_with_docker(environments) -> bool:
    """通过 Docker 实际状态同步缓存中环境的状态

    信号按可靠性分层（任一命中即采用）：
    1. docker compose ls --all：compose 文件路径精确匹配 / 项目名变体匹配
       → 可同时给出 running 与 stopped，最权威
    2. docker ps 项目标签（com.docker.compose.project）项目名变体匹配 → running
    3. docker ps 容器名变体匹配（兼容显式 container_name 之外的常规场景） → running

    原则：Docker 状态不可用（None）时绝不下调状态；
    只有拿到权威全量清单（compose ls --all 成功）时，
    才允许将"查无此项目"的 running 下调为 stopped。
    返回 bool：是否有状态变更。
    """
    projects, authoritative = _get_compose_ls_projects()
    project_labels = _get_project_labels()
    running_names = _get_running_container_names()

    if projects is None and project_labels is None and running_names is None:
        logger.warning("Docker 状态不可用，跳过状态同步（保留缓存状态）")
        return False

    vulhub_path = get_vulhub_path()
    by_config, by_name = {}, {}
    if projects is not None:
        for proj in projects:
            for cf in proj["config_files"]:
                by_config.setdefault(cf, proj)
            if proj["name"]:
                by_name.setdefault(proj["name"], proj)

    updated = 0
    for env in environments:
        name = env.get("name") or ""
        if not name:
            continue
        variants = _project_name_variants(Path(name).name)
        new_status = None

        if projects is not None:
            compose_file = _norm_path(str(vulhub_path / name / 'docker-compose.yml'))
            proj = by_config.get(compose_file)
            if proj is None:
                proj = next((by_name[v] for v in variants if v in by_name), None)
            if proj is not None:
                new_status = 'running' if proj["running"] else 'stopped'

        if new_status is None and project_labels is not None:
            if any(v in project_labels for v in variants):
                new_status = 'running'

        if new_status is None and running_names is not None:
            if any(_matches(c, v) for v in variants for c in running_names):
                new_status = 'running'

        old = env.get('status')
        if new_status is not None:
            if old != new_status:
                env['status'] = new_status
                updated += 1
        elif old == 'running' and authoritative:
            # 权威全量清单中不存在该项目 → 确认未运行
            env['status'] = 'stopped'
            updated += 1
            logger.info("Docker 状态同步：%s 不在运行项目清单中，标记为 stopped", name)
        elif old == 'running':
            # 无权威信息且未匹配到运行信号 → 保留原状态，避免误清空
            logger.debug("Docker 状态同步：%s 无法确认状态，保留 running", name)

    if updated:
        logger.info(f"Docker 状态同步完成，更新了 {updated} 个环境状态")
    return updated > 0


def _matches(c: str, v: str) -> bool:
    """检查容器名 c 是否匹配项目名变体 v

    匹配规则（满足任一即可）：
    1. 精确相等：c == v
    2. 标准前缀：c 以 v + 分隔符(/_/-) 开头
    3. 子串匹配：v 在 c 中由 /_/- 边界限定（避免 'cve' 误匹配 'CVE-2020-10199'）
       处理父目录前缀场景，如 'nexus_CVE-2020-10199' 含 'cve-2020-10199'
    """
    if c == v:
        return True
    if c.startswith(v + '_') or c.startswith(v + '-'):
        return True
    # 子串匹配：v 必须在 c 中，且两侧都是 _ - / 或字符串边界
    idx = c.find(v)
    if idx < 0:
        return False
    # 左边界：边界或非字母数字字符
    left_ok = idx == 0 or not c[idx - 1].isalnum()
    # 右边界：边界或非字母数字字符
    right_idx = idx + len(v)
    right_ok = right_idx == len(c) or not c[right_idx].isalnum()
    # 但还要避免 'cve' 匹配 'CVE-2020-10199'：要求两侧的分隔符是 _ 或 -（不是任意非字母数字）
    # 这意味着对短名（如 'CVE'），它必须以 _ - 开头（如 'project_cve_...'）才算真正匹配
    if not left_ok or not right_ok:
        return False
    # 左侧必须边界或 _ 或 -
    left_strict = idx == 0 or c[idx - 1] in ('_', '-')
    # 右侧必须边界或 _ 或 -
    right_strict = right_idx == len(c) or c[right_idx] in ('_', '-')
    return left_strict and right_strict


def _project_name_variants(basename: str) -> set:
    """生成目录名可能的 Docker Compose 项目名变体集合

    Docker Compose v2: 非字母数字/下划线 → 连字符，连续连字符合并
    Docker Compose v1: 去除非字母数字
    容器名: <项目名> + 分隔符(-或_) + <service> + 分隔符 + <副本编号>
    """
    lower = basename.lower()
    # v2: 非 [a-z0-9_] → 连字符，合并连续连字符，去首尾连字符
    v2 = re.sub(r'[^a-z0-9_]', '-', lower)
    v2 = re.sub(r'-{2,}', '-', v2).strip('-')
    # v1: 仅保留字母数字
    v1 = re.sub(r'[^a-z0-9]', '', lower)
    # v3: 保留原始（含点号、连字符、下划线）— vulhub 实际容器名常保留版本号点号
    variants = {lower, v1, v2}
    # 连字符版本 → 下划线版本（v1 可能在 v2 基础上把 - 全换成 _）
    if '-' in v2:
        variants.add(v2.replace('-', '_'))
    if '_' in v2:
        variants.add(v2.replace('_', '-'))
    return variants
