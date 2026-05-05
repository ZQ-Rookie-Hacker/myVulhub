# coding: utf-8
import re
import json
import time
import subprocess
from pathlib import Path
from typing import Tuple, Dict, Any, List

from app.config import get_vulhub_path, DOCKER_TIMEOUT, DOCKER_STOP_TIMEOUT, logger
from app.utils.compose import fallback_parse_images

try:
    from urllib.request import urlopen, Request
    from urllib.error import URLError, HTTPError
except Exception:
    urlopen = None


class VulhubOperations:
    def __init__(self):
        self.compose_cmd = self._detect_compose_cmd()
        from app.services.git import GitOperations
        self.git_ops = GitOperations()

    def start(self, name: str, use_proxy: bool = False) -> Tuple[bool, Dict[str, Any]]:
        env_dir = self._env_dir(name)
        if not env_dir:
            return False, {"error": f"找不到环境：{name}"}

        if use_proxy:
            logger.info(f"使用代理模式拉取镜像: {name}")
            cmd = self._cmd(['pull'])
            cmd_with_proxy = ['proxychains4'] + cmd
            try:
                result = subprocess.run(
                    cmd_with_proxy,
                    cwd=str(env_dir),
                    check=False,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    timeout=180
                )
                if result.returncode != 0:
                    logger.error(f"代理拉取镜像失败: {name}, 错误: {result.stderr}")
                    return False, {"error": f"代理拉取镜像失败: {result.stderr or result.stdout}"}
                else:
                    logger.info(f"代理拉取镜像成功: {name}")
            except subprocess.TimeoutExpired:
                logger.error(f"代理拉取镜像超时: {name}")
                return False, {"error": "代理拉取镜像超时"}
            except FileNotFoundError:
                logger.error("proxychains4 未找到")
                return False, {"error": "proxychains4 未找到，请确认已安装"}
            except Exception as e:
                logger.error(f"代理拉取镜像异常: {name}, 错误: {e}")
                return False, {"error": f"代理拉取镜像异常: {str(e)}"}

        ok, out, err = self._run(self._cmd(['up', '-d']), cwd=env_dir, timeout=DOCKER_TIMEOUT)
        if not ok:
            info = {"error": (err.strip() or out.strip() or "启动失败")}
            if 'address already in use' in err.lower() or 'port is already allocated' in err.lower():
                info['port_conflict'] = True
            return False, info
        return True, {}

    def stop(self, name: str) -> Tuple[bool, Dict[str, Any]]:
        logger.info(f"开始停止环境: {name}")
        env_dir = self._env_dir(name)
        if not env_dir:
            logger.error(f"停止环境失败: 找不到环境 {name}")
            return False, {"error": f"找不到环境：{name}"}

        ok, out, err = self._run(self._cmd(['down', '--timeout', '5']), cwd=env_dir, timeout=DOCKER_STOP_TIMEOUT)
        if not ok:
            error_msg = err.strip() or out.strip() or "停止失败"
            logger.error(f"停止环境失败: {name}, 错误: {error_msg}")
            return False, {"error": error_msg}

        logger.info(f"成功停止环境: {name}")
        return True, {}

    def check_images(self, name: str) -> Tuple[bool, Dict[str, Any]]:
        logger.info(f"开始检查环境镜像: {name}")
        env_dir = self._env_dir(name)
        if not env_dir:
            logger.warning(f"检查镜像失败: 找不到环境 {name}")
            return True, {"missing": [], "warning": f"找不到环境：{name}（跳过检查）"}

        ok, out, _ = self._run(self._cmd(['config', '--images']), cwd=env_dir)
        images: List[str]
        if ok:
            images = [ln.strip() for ln in out.splitlines() if ln.strip()]
            logger.debug(f"获取镜像列表成功: {name}, 镜像数量: {len(images)}")
        else:
            logger.warning(f"使用备用方法解析镜像: {name}")
            images = fallback_parse_images(env_dir)

        missing: List[str] = []
        for img in images:
            ok2, _, _ = self._run(['docker', 'image', 'inspect', img])
            if not ok2:
                missing.append(img)
                logger.debug(f"镜像缺失: {img}")

        logger.info(f"镜像检查完成: {name}, 缺失镜像数量: {len(missing)}")
        return True, {"missing": missing}

    def pull_images_stream(self, name: str, use_proxy: bool = False):
        logger.info(f"开始拉取环境镜像: {name}, 代理模式: {use_proxy}")
        env_dir = self._env_dir(name)
        if not env_dir:
            logger.error(f"拉取镜像失败: 找不到环境 {name}")
            yield "[Error] 找不到环境"
            return

        cmd = self._cmd(['pull'])
        if use_proxy:
            cmd = ['proxychains4'] + cmd
        try:
            proc = subprocess.Popen(
                cmd,
                cwd=str(env_dir),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1
            )
            logger.debug(f"启动Docker进程: {' '.join(cmd)}")
        except FileNotFoundError:
            if use_proxy:
                logger.error("proxychains4 或 Docker命令未找到")
                yield "[Error] 找不到 proxychains4 或 docker 指令，请确认已安装并配置正确。"
            else:
                logger.error("Docker命令未找到")
                yield "[Error] 找不到 docker 指令，请确认已安装 Docker 并在 PATH 中。"
            return
        except Exception as e:
            logger.error(f"启动Docker进程失败: {e}")
            yield f"[Error] 启动Docker进程失败: {str(e)}"
            return

        if proc.stdout:
            for line in proc.stdout:
                yield line.rstrip('\n')

        return_code = proc.wait()
        if return_code == 0:
            logger.info(f"镜像拉取成功: {name}")
        else:
            logger.warning(f"镜像拉取异常退出: {name}, 退出码: {return_code}")

    def remove_images(self, name: str) -> Tuple[bool, Dict[str, Any]]:
        logger.info(f"开始删除环境镜像: {name}")
        env_dir = self._env_dir(name)
        if not env_dir:
            logger.error(f"删除镜像失败: 找不到环境 {name}")
            return False, {"error": f"找不到环境：{name}"}

        ok, out, _ = self._run(self._cmd(['config', '--images']), cwd=env_dir)
        if not ok:
            logger.error(f"获取镜像列表失败: {name}")
            return False, {"error": "无法获取镜像列表"}

        images = [ln.strip() for ln in out.splitlines() if ln.strip()]
        logger.debug(f"获取到镜像列表: {name}, 镜像数量: {len(images)}")

        if not images:
            logger.info(f"没有需要删除的镜像: {name}")
            return True, {"message": "没有找到需要删除的镜像"}

        removed_images = []
        failed_images = []

        for img in images:
            ok, out, err = self._run(['docker', 'rmi', '-f', img], timeout=30)
            if ok:
                removed_images.append(img)
                logger.debug(f"成功删除镜像: {img}")
            else:
                check_ok, _, _ = self._run(['docker', 'inspect', img], timeout=10)
                if not check_ok:
                    removed_images.append(img)
                    logger.debug(f"镜像已不存在，跳过: {img}")
                else:
                    failed_images.append(img)
                    logger.warning(f"删除镜像失败: {img}, 错误: {err.strip()}")

        result = {
            "removed": removed_images,
            "failed": failed_images,
            "total": len(images)
        }

        if failed_images:
            logger.warning(f"部分镜像删除失败: {name}, 失败数量: {len(failed_images)}")
            return False, {"error": f"部分镜像删除失败", "details": result}

        logger.info(f"成功删除所有镜像: {name}, 删除数量: {len(removed_images)}")
        return True, result

    def wait_ready(self, name: str, timeout: int = 20) -> Tuple[bool, Dict[str, Any]]:
        if urlopen is None:
            return True, {"ready": False}

        env_dir = self._env_dir(name)
        if not env_dir:
            return True, {"ready": False}

        deadline = time.time() + max(1, int(timeout))
        chosen_port = None

        while time.time() < deadline:
            ports = self._pick_host_ports(env_dir)
            if ports:
                chosen_port = ports[0]
                for scheme in ('http', 'https'):
                    try:
                        req = Request(f"{scheme}://127.0.0.1:{chosen_port}", headers={'User-Agent': 'curl/8'})
                        with urlopen(req, timeout=2) as resp:
                            if 200 <= getattr(resp, 'status', 200) < 400:
                                return True, {"ready": True, "port": chosen_port}
                            return True, {"ready": True, "port": chosen_port}
                    except (URLError, HTTPError, Exception):
                        pass
            time.sleep(1.0)

        if chosen_port:
            return True, {"ready": False, "port": chosen_port}
        return True, {"ready": False}

    def _detect_compose_cmd(self) -> List[str]:
        ok, _, _ = self._run(['docker', 'compose', 'version'])
        if ok:
            return ['docker', 'compose']
        ok, _, _ = self._run(['docker-compose', 'version'])
        if ok:
            return ['docker-compose']
        return ['docker', 'compose']

    def _cmd(self, args: List[str]) -> List[str]:
        return self.compose_cmd + args

    def _env_dir(self, name: str) -> Path | None:
        if not name or not isinstance(name, str):
            return None

        clean_name = name.strip()
        if not clean_name or clean_name.startswith('/'):
            return None

        try:
            vulhub_path = get_vulhub_path()
            p = (vulhub_path / clean_name).resolve()
            if vulhub_path not in p.parents and p != vulhub_path:
                logger.warning(f"路径越权检查失败: {name}")
                return None
            if not p.exists():
                logger.debug(f"环境目录不存在: {name}")
                return None
            if not (p / 'docker-compose.yml').exists():
                logger.debug(f"docker-compose.yml不存在: {name}")
                return None
            logger.debug(f"成功解析环境目录: {name} -> {p}")
            return p
        except Exception as e:
            logger.warning(f"环境目录解析失败: {name}, 错误: {e}")
            return None

    def _run(self, args: List[str], cwd: Path | None = None, timeout: int = 60) -> Tuple[bool, str, str]:
        try:
            result = subprocess.run(
                args,
                cwd=str(cwd) if cwd else None,
                check=False,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=timeout
            )
            return result.returncode == 0, result.stdout, result.stderr
        except subprocess.TimeoutExpired:
            return False, "", f"Command timed out after {timeout} seconds: {' '.join(args)}"
        except FileNotFoundError as e:
            return False, "", str(e)
        except Exception as e:
            return False, "", str(e)

    def _pick_host_ports(self, env_dir: Path) -> List[int]:
        ok, out, _ = self._run(self._cmd(['ps', '--format', 'json']), cwd=env_dir)
        ports: List[int] = []
        if ok:
            try:
                lines = [json.loads(x) for x in out.splitlines() if x.strip()]
                for obj in lines:
                    pstr = obj.get('Ports') or ''
                    for hp in self._parse_ports_string(pstr):
                        if hp not in ports:
                            ports.append(hp)
            except Exception:
                pass
        return ports

    def _parse_ports_string(self, s: str) -> List[int]:
        host_ports: List[int] = []
        for part in s.split(','):
            m = re.search(r':(\d+)->\d+/(tcp|udp)', part)
            if m:
                try:
                    host_ports.append(int(m.group(1)))
                except Exception:
                    pass
        return host_ports
