# coding: utf-8
import re
import subprocess
from pathlib import Path
from typing import List, Tuple, Dict, Any

from app.config import get_vulhub_path, GIT_OPERATION_TIMEOUT, logger
from app.utils.helpers import handle_git_errors


class GitOperations:
    """Git 操作类"""

    def __init__(self, vulhub_path: Path = None):
        self.vulhub_path = vulhub_path or get_vulhub_path()

    @handle_git_errors
    def sync_vulhub(self, method: str = "https", remote_url: str = None) -> Tuple[bool, Dict[str, Any]]:
        if not self.vulhub_path.exists():
            logger.error("Vulhub目录不存在")
            return False, {"error": "Vulhub 目录不存在"}

        if not remote_url:
            if method == "ssh":
                remote_url = "git@github.com:vulhub/vulhub.git"
            else:
                remote_url = "https://github.com/vulhub/vulhub.git"

        use_proxychains = method == "https_proxy"
        if use_proxychains:
            method = "https"

        logger.info(f"开始同步Vulhub仓库，方法: {method}, 远程URL: {remote_url}")

        try:
            is_new_repo = not (self.vulhub_path / ".git").exists()
            if is_new_repo:
                return self._init_and_sync(remote_url, use_proxychains)

            # 空仓库（如 git init 后未 fetch）按新仓库处理
            if self._get_commit_count(use_proxychains=False) == 0:
                logger.info("检测到空仓库，按新仓库初始化")
                return self._init_and_sync(remote_url, use_proxychains)

            # 本地操作：不经过代理
            sync_result = self._get_sync_summary(use_proxychains=False)
            current_branch = self._get_current_branch(use_proxychains=False)
            if not current_branch:
                return False, {"error": "无法获取当前分支"}

            has_changes = self._has_uncommitted_changes(use_proxychains=False)
            if has_changes:
                self._stash_changes(use_proxychains=False)

            # 网络操作：经过代理
            pull_ok, pull_output = self._pull_updates(use_proxychains)

            if has_changes:
                self._unstash_changes(use_proxychains=False)

            if pull_ok:
                # 变更摘要中的本地操作也不经过代理
                changes = self._get_changes_summary(sync_result, use_proxychains=False)
                latest_commit = self._get_latest_commit(use_proxychains=False)
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
        try:
            # 本地操作（已初始化则跳过）
            if not (self.vulhub_path / ".git").exists():
                ok, out, err = self._run_git(["init"], use_proxychains=False)
                if not ok:
                    return False, {"error": f"Git 初始化失败: {err}"}

            # 检查远程仓库是否已存在
            ok, out, _ = self._run_git(["remote", "get-url", "origin"], use_proxychains=False)
            if ok:
                # 远程已存在，更新 URL
                self._run_git(["remote", "set-url", "origin", remote_url], use_proxychains=False)
            else:
                ok, out, err = self._run_git(["remote", "add", "origin", remote_url], use_proxychains=False)
                if not ok:
                    return False, {"error": f"添加远程仓库失败: {err}"}

            # 网络操作：fetch 需要代理
            ok, out, err = self._run_git(["fetch", "--all"], use_proxychains)
            if not ok:
                return False, {"error": f"拉取分支失败: {err}"}

            # 本地操作
            ok, out, err = self._run_git(["checkout", "master"], use_proxychains=False)
            if not ok:
                ok, out, err = self._run_git(["checkout", "main"], use_proxychains=False)
                if not ok:
                    return False, {"error": f"切换分支失败: {err}"}

            commit_count = self._get_commit_count(use_proxychains=False)
            env_count = self._get_env_count(use_proxychains=False)

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
        ok, out, err = self._run_git(["branch", "--show-current"], use_proxychains)
        return out.strip() if ok else None

    def _has_uncommitted_changes(self, use_proxychains: bool = False) -> bool:
        ok, out, err = self._run_git(["status", "--porcelain"], use_proxychains)
        return bool(out.strip()) if ok else False

    def _stash_changes(self, use_proxychains: bool = False):
        self._run_git(["stash", "push", "-m", "vulhub-manager-auto-stash"], use_proxychains)

    def _unstash_changes(self, use_proxychains: bool = False):
        self._run_git(["stash", "pop"], use_proxychains)

    def _pull_updates(self, use_proxychains: bool = False) -> Tuple[bool, Dict[str, Any]]:
        ok, out, err = self._run_git(["pull", "origin", "master", "--rebase"], use_proxychains)
        if ok:
            return True, {"message": "同步成功", "output": out}
        else:
            return False, {"error": f"拉取失败: {err}"}

    def _get_sync_summary(self, use_proxychains: bool = False) -> Dict[str, Any]:
        return {
            "commits": self._get_commit_count(use_proxychains),
            "env_count": self._get_env_count(use_proxychains)
        }

    def _get_commit_count(self, use_proxychains: bool = False) -> int:
        ok, out, err = self._run_git(["rev-list", "--count", "HEAD"], use_proxychains)
        try:
            return int(out.strip()) if ok else 0
        except Exception:
            return 0

    def _get_env_count(self, use_proxychains: bool = False) -> int:
        ok, out, err = self._run_git(["ls-files"], use_proxychains)
        if ok:
            return out.count('docker-compose.yml')
        return 0

    def _get_changes_summary(self, old_summary: Dict, use_proxychains: bool = False) -> Dict[str, Any]:
        new_commits = self._get_commit_count(use_proxychains)
        old_commits = old_summary.get("commits", 0)
        commit_diff = new_commits - old_commits

        changed_files = self._get_changed_files(use_proxychains)
        new_files = self._get_new_files(use_proxychains)
        deleted_files = self._get_deleted_files(use_proxychains)
        changed_cves = self._analyze_changed_cves(changed_files)

        return {
            "new": False,
            "commits_ahead": commit_diff if commit_diff > 0 else 0,
            "total_commits": new_commits,
            "files_changed": len(changed_files),
            "files_added": len(new_files),
            "files_deleted": len(deleted_files),
            "changed_file_list": changed_files[:20],
            "new_file_list": new_files[:10],
            "deleted_file_list": deleted_files[:10],
            "changed_cves": changed_cves[:10],
            "total_environments": self._get_env_count(use_proxychains)
        }

    def _get_changed_files(self, use_proxychains: bool = False) -> List[str]:
        ok, out, err = self._run_git(["status", "--porcelain"], use_proxychains)
        if not ok:
            return []
        files = []
        for line in out.strip().split('\n'):
            if line.strip():
                status = line[:2].strip()
                filename = line[2:].strip()
                if filename.endswith('/docker-compose.yml') or 'README' in filename:
                    files.append(f"{status} {filename}")
        return files

    def _get_new_files(self, use_proxychains: bool = False) -> List[str]:
        ok, out, err = self._run_git(["ls-files", "--others", "--exclude-standard"], use_proxychains)
        if not ok:
            return []
        files = []
        for line in out.strip().split('\n'):
            if line.strip() and (line.endswith('/docker-compose.yml') or 'README' in line):
                files.append(line.strip())
        return files

    def _get_deleted_files(self, use_proxychains: bool = False) -> List[str]:
        ok, out, err = self._run_git(["ls-files", "--deleted"], use_proxychains)
        if not ok:
            return []
        files = []
        for line in out.strip().split('\n'):
            if line.strip() and (line.endswith('/docker-compose.yml') or 'README' in line):
                files.append(line.strip())
        return files

    def _analyze_changed_cves(self, changed_files: List[str]) -> List[Dict[str, str]]:
        cves = []
        for change in changed_files:
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
        ok, out, err = self._run_git(["log", "-1", "--format=%H|%an|%ad|%s"], use_proxychains)
        if not ok:
            return {}
        parts = out.strip().split('|')
        if len(parts) >= 4:
            return {
                "hash": parts[0][:7],
                "author": parts[1],
                "date": parts[2],
                "message": parts[3]
            }
        return {}

    def _run_git(self, args: List[str], use_proxychains: bool = False, _retry: bool = True) -> Tuple[bool, str, str]:
        if use_proxychains:
            cmd = ["proxychains4", "git"] + args
        else:
            cmd = ["git"] + args
        try:
            result = subprocess.run(
                cmd,
                cwd=str(self.vulhub_path),
                check=False,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=GIT_OPERATION_TIMEOUT
            )
            ok = result.returncode == 0
            err = result.stderr
            if not ok and _retry and 'detected dubious ownership' in err:
                m = re.search(r"detected dubious ownership in repository at '([^']+)'", err)
                if not m:
                    m = re.search(r'at (.+)$', err)
                if m:
                    repo_dir = m.group(1).strip()
                    logger.warning(f"检测到 Git 仓库所有者不匹配，自动配置 safe.directory: {repo_dir}")
                    subprocess.run(
                        ['git', 'config', '--global', '--add', 'safe.directory', repo_dir],
                        check=False, timeout=10
                    )
                    return self._run_git(args, use_proxychains, _retry=False)
            return ok, result.stdout, err
        except subprocess.TimeoutExpired:
            return False, "", f"Command timed out: {' '.join(cmd)}"
        except FileNotFoundError as e:
            return False, "", str(e)
        except Exception as e:
            return False, "", str(e)
