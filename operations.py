# operations.py
# 极小变更版：补齐 check_images / pull_images_stream / wait_ready，并保留 start/stop
# 只做可靠的最少功能，不入侵 app.py 的其他行为

from __future__ import annotations
import os
import subprocess
import json
import time
import re
import logging
import functools
from pathlib import Path
from typing import Tuple, Dict, Any, List

try:
    from urllib.request import urlopen, Request
    from urllib.error import URLError, HTTPError
except Exception:
    urlopen = None

# 设置日志
logger = logging.getLogger('vulhub_manager')

# Git操作错误处理装饰器
def handle_git_errors(func):
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except subprocess.TimeoutExpired:
            logger.error("Git操作超时")
            return False, {"error": "Git操作超时"}
        except subprocess.CalledProcessError as e:
            # 更安全的错误信息处理
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

# 与 app.py 一致的根目录（用你的 VULHUB_PATH）
VULHUB_PATH = Path(os.environ.get('VULHUB_PATH', '../vulhub')).resolve()


class GitOperations:
    """Git 操作类"""
    
    def __init__(self, vulhub_path: Path, run_func):
        self.vulhub_path = vulhub_path
        self._run = run_func  # 接收 _run 方法作为参数
    
    @handle_git_errors
    def sync_vulhub(self, method: str = "https", remote_url: str = None) -> Tuple[bool, Dict[str, Any]]:
        """
        同步 vulhub 仓库
        method: "ssh", "https", "https_proxy", "gh" (GitHub CLI)
        返回: (success, {"message", "changes": {...}})
        """
        if not self.vulhub_path.exists():
            logger.error("Vulhub目录不存在")
            return False, {"error": "Vulhub 目录不存在"}

        # 设置默认远程 URL
        if not remote_url:
            if method == "ssh":
                remote_url = "git@github.com:vulhub/vulhub.git"
            else:
                remote_url = "https://github.com/vulhub/vulhub.git"
        
        # 检查是否使用 proxychains4
        use_proxychains = method == "https_proxy"
        if use_proxychains:
            method = "https"  # 实际还是使用 HTTPS，只是通过 proxychains4
        
        logger.info(f"开始同步Vulhub仓库，方法: {method}, 远程URL: {remote_url}")

        try:
            # 检查是否是 Git 仓库
            is_new_repo = not (self.vulhub_path / ".git").exists()
            
            if is_new_repo:
                return self._init_and_sync(remote_url, use_proxychains)

            # 获取同步前的状态
            sync_result = self._get_sync_summary(use_proxychains)
            
            # 获取当前分支
            current_branch = self._get_current_branch(use_proxychains)
            if not current_branch:
                return False, {"error": "无法获取当前分支"}

            # 保存当前修改
            has_changes = self._has_uncommitted_changes(use_proxychains)
            if has_changes:
                self._stash_changes(use_proxychains)

            # 拉取更新
            pull_ok, pull_output = self._pull_updates(use_proxychains)

            # 恢复修改
            if has_changes:
                self._unstash_changes(use_proxychains)

            if pull_ok:
                # 获取同步后的变更摘要
                changes = self._get_changes_summary(sync_result, use_proxychains)
                
                # 获取最新提交信息
                latest_commit = self._get_latest_commit(use_proxychains)
                
                return True, {
                    "message": "同步成功",
                    "changes": changes,
                    "latest_commit": latest_commit
                }
            else:
                return False, pull_output

        except Exception as e:
            return False, {"error": f"同步失败: {str(e)}"}
    
    def _init_and_sync(self, remote_url: str, use_proxychains: bool = False) -> Tuple[bool, Dict[str, Any]]:
        """初始化 Git 仓库并同步"""
        try:
            # 初始化 Git 仓库
            ok, out, err = self._run_git(["init"], use_proxychains)
            if not ok:
                return False, {"error": f"Git 初始化失败: {err}"}

            # 添加远程仓库
            ok, out, err = self._run_git(["remote", "add", "origin", remote_url], use_proxychains)
            if not ok:
                return False, {"error": f"添加远程仓库失败: {err}"}

            # 拉取所有分支
            ok, out, err = self._run_git(["fetch", "--all"], use_proxychains)
            if not ok:
                return False, {"error": f"拉取分支失败: {err}"}

            # 切换到 master 分支
            ok, out, err = self._run_git(["checkout", "master"], use_proxychains)
            if not ok:
                # 尝试切换到 main 分支
                ok, out, err = self._run_git(["checkout", "main"], use_proxychains)
                if not ok:
                    return False, {"error": f"切换分支失败: {err}"}

            # 获取仓库统计信息
            commit_count = self._get_commit_count(use_proxychains)
            env_count = self._get_env_count(use_proxychains)
            
            return True, {
                "message": "初始化并同步成功",
                "is_new_repo": True,
                "changes": {
                    "new": True,
                    "total_commits": commit_count,
                    "total_environments": env_count
                }
            }

        except Exception as e:
            return False, {"error": f"初始化失败: {str(e)}"}
    
    def _get_current_branch(self, use_proxychains: bool = False) -> str:
        """获取当前分支"""
        ok, out, err = self._run_git(["branch", "--show-current"], use_proxychains)
        return out.strip() if ok else None
    
    def _has_uncommitted_changes(self, use_proxychains: bool = False) -> bool:
        """检查是否有未提交的修改"""
        ok, out, err = self._run_git(["status", "--porcelain"], use_proxychains)
        return bool(out.strip()) if ok else False
    
    def _stash_changes(self, use_proxychains: bool = False):
        """暂存当前修改"""
        self._run_git(["stash", "push", "-m", "vulhub-manager-auto-stash"], use_proxychains)
    
    def _unstash_changes(self, use_proxychains: bool = False):
        """恢复暂存的修改"""
        self._run_git(["stash", "pop"], use_proxychains)
    
    def _pull_updates(self, use_proxychains: bool = False) -> Tuple[bool, Dict[str, Any]]:
        """拉取更新"""
        ok, out, err = self._run_git(["pull", "origin", "master", "--rebase"], use_proxychains)
        if ok:
            return True, {"message": "同步成功", "output": out}
        else:
            return False, {"error": f"拉取失败: {err}"}
    
    def _get_sync_summary(self, use_proxychains: bool = False) -> Dict[str, Any]:
        """获取同步前的摘要信息"""
        return {
            "commits": self._get_commit_count(use_proxychains),
            "env_count": self._get_env_count(use_proxychains)
        }
    
    def _get_commit_count(self, use_proxychains: bool = False) -> int:
        """获取提交数量"""
        ok, out, err = self._run_git(["rev-list", "--count", "HEAD"], use_proxychains)
        try:
            return int(out.strip()) if ok else 0
        except Exception:
            return 0
    
    def _get_env_count(self, use_proxychains: bool = False) -> int:
        """获取环境数量"""
        ok, out, err = self._run_git(["ls-files"], use_proxychains)
        if ok:
            count = out.count('docker-compose.yml')
            return count
        return 0
    
    def _get_changes_summary(self, old_summary: Dict, use_proxychains: bool = False) -> Dict[str, Any]:
        """获取变更摘要"""
        new_commits = self._get_commit_count(use_proxychains)
        old_commits = old_summary.get("commits", 0)
        commit_diff = new_commits - old_commits
        
        # 获取变更文件统计
        changed_files = self._get_changed_files(use_proxychains)
        
        # 获取新增文件
        new_files = self._get_new_files(use_proxychains)
        
        # 获取删除的文件
        deleted_files = self._get_deleted_files(use_proxychains)
        
        # 获取修改的CVE数量
        changed_cves = self._analyze_changed_cves(changed_files)
        
        return {
            "new": False,
            "commits_ahead": commit_diff if commit_diff > 0 else 0,
            "total_commits": new_commits,
            "files_changed": len(changed_files),
            "files_added": len(new_files),
            "files_deleted": len(deleted_files),
            "changed_file_list": changed_files[:20],  # 限制显示数量
            "new_file_list": new_files[:10],
            "deleted_file_list": deleted_files[:10],
            "changed_cves": changed_cves[:10],
            "total_environments": self._get_env_count(use_proxychains)
        }
    
    def _get_changed_files(self, use_proxychains: bool = False) -> List[str]:
        """获取变更的文件列表（新增、修改、删除）"""
        ok, out, err = self._run_git(["status", "--porcelain"], use_proxychains)
        if not ok:
            return []
        
        files = []
        for line in out.strip().split('\n'):
            if line.strip():
                # 解析状态行：XY 文件名
                status = line[:2].strip()
                filename = line[2:].strip()
                # 只统计特定文件
                if filename.endswith('/docker-compose.yml') or 'README' in filename:
                    files.append(f"{status} {filename}")
        
        return files
    
    def _get_new_files(self, use_proxychains: bool = False) -> List[str]:
        """获取新增的文件列表"""
        ok, out, err = self._run_git(["ls-files", "--others", "--exclude-standard"], use_proxychains)
        if not ok:
            return []
        
        files = []
        for line in out.strip().split('\n'):
            if line.strip() and (line.endswith('/docker-compose.yml') or 'README' in line):
                files.append(line.strip())
        
        return files
    
    def _get_deleted_files(self, use_proxychains: bool = False) -> List[str]:
        """获取删除的文件列表"""
        ok, out, err = self._run_git(["ls-files", "--deleted"], use_proxychains)
        if not ok:
            return []
        
        files = []
        for line in out.strip().split('\n'):
            if line.strip() and (line.endswith('/docker-compose.yml') or 'README' in line):
                files.append(line.strip())
        
        return files
    
    def _analyze_changed_cves(self, changed_files: List[str]) -> List[Dict[str, str]]:
        """分析变更的CVE列表"""
        cves = []
        for change in changed_files:
            # 从路径中提取CVE编号
            import re
            # 匹配如 CVE-2020-10199 这样的模式
            matches = re.findall(r'([A-Z]+-\d+-\d+)', change)
            for cve in matches:
                if cve not in [v.get('cve') for v in cves]:
                    change_type = "修改"
                    if 'A ' in change or change.startswith('A '):
                        change_type = "新增"
                    elif 'D ' in change or change.startswith('D '):
                        change_type = "删除"
                    cves.append({
                        "cve": cve,
                        "type": change_type,
                        "path": change.split(' ')[-1] if ' ' in change else change
                    })
        
        return cves
    
    def _get_latest_commit(self, use_proxychains: bool = False) -> Dict[str, str]:
        """获取最新提交信息"""
        ok, out, err = self._run_git(["log", "-1", "--format=%H|%an|%ad|%s"], use_proxychains)
        if not ok:
            return {}
        
        parts = out.strip().split('|')
        if len(parts) >= 4:
            from datetime import datetime
            try:
                # 尝试解析日期
                date = datetime.fromisoformat(parts[2].replace(' ', 'T'))
                date_str = date.strftime('%Y-%m-%d %H:%M')
            except Exception:
                date_str = parts[2]
            
            return {
                "hash": parts[0][:7],
                "author": parts[1],
                "date": date_str,
                "message": parts[3]
            }
        return {}
    
    def _run_git(self, args: List[str], use_proxychains: bool = False) -> Tuple[bool, str, str]:
        """执行 Git 命令"""
        if use_proxychains:
            return self._run(["proxychains4", "git"] + args, cwd=self.vulhub_path)
        else:
            return self._run(["git"] + args, cwd=self.vulhub_path)


class VulhubOperations:
    def __init__(self):
        self.compose_cmd = self._detect_compose_cmd()
        self.git_ops = GitOperations(VULHUB_PATH, self._run)

    # ===== 公开 API =====

    def start(self, name: str, use_proxy: bool = False) -> Tuple[bool, Dict[str, Any]]:
        env_dir = self._env_dir(name)
        if not env_dir:
            return False, {"error": f"找不到环境：{name}"}
        
        # 如果需要使用代理，则先拉取镜像
        if use_proxy:
            logger.info(f"使用代理模式拉取镜像: {name}")
            # 创建临时的拉取进程，使用proxychains4
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
                    timeout=180  # 增加超时时间以应对网络较慢的情况
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

        ok, out, err = self._run(self._cmd(['up', '-d']), cwd=env_dir, timeout=90)
        if not ok:
            info = {"error": (err.strip() or out.strip() or "启动失败")}
            if 'address already in use' in err.lower() or 'port is already allocated' in err.lower():
                info['port_conflict'] = True
            return False, info
        return True, {}

    def stop(self, name: str) -> Tuple[bool, Dict[str, Any]]:
        """停止环境"""
        logger.info(f"开始停止环境: {name}")
        env_dir = self._env_dir(name)
        if not env_dir:
            logger.error(f"停止环境失败: 找不到环境 {name}")
            return False, {"error": f"找不到环境：{name}"}
        
        # 使用更高效的停止命令，快速停止所有服务
        ok, out, err = self._run(self._cmd(['down', '--timeout', '5']), cwd=env_dir, timeout=20)
        if not ok:
            error_msg = err.strip() or out.strip() or "停止失败"
            logger.error(f"停止环境失败: {name}, 错误: {error_msg}")
            return False, {"error": error_msg}
        
        logger.info(f"成功停止环境: {name}")
        return True, {}

    def check_images(self, name: str) -> Tuple[bool, Dict[str, Any]]:
        """
        使用 `docker compose config --images` 取得所需 image。
        返回 (True, {"missing": [...]})；True 代表 API 正常，不代表不缺。
        """
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
            images = self._fallback_parse_images(env_dir)

        missing: List[str] = []
        for img in images:
            ok2, _, _ = self._run(['docker', 'image', 'inspect', img])
            if not ok2:
                missing.append(img)
                logger.debug(f"镜像缺失: {img}")

        logger.info(f"镜像检查完成: {name}, 缺失镜像数量: {len(missing)}")
        return True, {"missing": missing}

    def pull_images_stream(self, name: str, use_proxy: bool = False):
        """
        逐行输出 `docker compose pull` 给 SSE。
        use_proxy: 是否使用 proxychains4 代理拉取镜像
        """
        logger.info(f"开始拉取环境镜像: {name}, 代理模式: {use_proxy}")
        env_dir = self._env_dir(name)
        if not env_dir:
            logger.error(f"拉取镜像失败: 找不到环境 {name}")
            yield "[Error] 找不到环境"
            return

        cmd = self._cmd(['pull'])
        if use_proxy:
            # 使用 proxychains4 代理执行 docker compose pull
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
            line_count = 0
            for line in proc.stdout:
                line_count += 1
                yield line.rstrip('\n')
            logger.debug(f"拉取镜像完成，输出行数: {line_count}")
        
        return_code = proc.wait()
        if return_code == 0:
            logger.info(f"镜像拉取成功: {name}")
        else:
            logger.warning(f"镜像拉取异常退出: {name}, 退出码: {return_code}")

    def remove_images(self, name: str) -> Tuple[bool, Dict[str, Any]]:
        """
        删除环境相关的所有 Docker 镜像。
        """
        logger.info(f"开始删除环境镜像: {name}")
        env_dir = self._env_dir(name)
        if not env_dir:
            logger.error(f"删除镜像失败: 找不到环境 {name}")
            return False, {"error": f"找不到环境：{name}"}

        # 获取环境使用的所有镜像
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
            # 删除镜像，使用适当的超时时间
            ok, out, err = self._run(['docker', 'rmi', '-f', img], timeout=30)
            if ok:
                removed_images.append(img)
                logger.debug(f"成功删除镜像: {img}")
            else:
                # 检查镜像是否真的不存在（这种情况可以忽略）
                check_ok, _, _ = self._run(['docker', 'inspect', img], timeout=10)
                if not check_ok:
                    # 镜像已经不存在，这不算错误
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
        """
        在 timeout 內嘗試連到第一個對外的 host port；連上就回 ready=True。
        """
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

    # ===== 私有工具 =====

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
        """获取环境目录，包含完整的安全检查"""
        # 输入验证
        if not name or not isinstance(name, str):
            return None
        
        # 清理路径（防止路径遍历攻击）
        clean_name = name.strip().replace('..', '').replace('//', '/')
        if not clean_name:
            return None
        
        try:
            p = (VULHUB_PATH / clean_name).resolve()
            
            # 路径越权检查（核心安全机制）
            if VULHUB_PATH not in p.parents and p != VULHUB_PATH:
                logger.warning(f"路径越权检查失败: {name}")
                return None
                
            # 存在性检查
            if not p.exists():
                logger.debug(f"环境目录不存在: {name}")
                return None
                
            if not (p / 'docker-compose.yml').exists():
                logger.debug(f"docker-compose.yml不存在: {name}")
                return None
                
            logger.debug(f"成功解析环境目录: {name} -> {p}")
            return p
        except Exception as e:
            # 记录异常便于调试
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

    def _fallback_parse_images(self, env_dir: Path) -> List[str]:
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