# coding: utf-8
"""cache.py 状态同步决策逻辑单元测试（不依赖 Docker 环境）"""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.utils import cache as cache_mod
from app.utils.cache import (
    _norm_path, _project_name_variants, _matches,
    _parse_compose_ls_items, _project_from_ls_item,
    reconcile_cache_with_docker, update_persistent_cache_entry,
)


def _env(name, status):
    return {"name": name, "status": status}


class TestNormPath(unittest.TestCase):
    def test_windows_style_normalized(self):
        self.assertEqual(
            _norm_path(r'D:\VulHub\Flask\SSTI\docker-compose.yml'),
            'd:/vulhub/flask/ssti/docker-compose.yml'
        )

    def test_posix_style_normalized(self):
        self.assertEqual(
            _norm_path('/opt/vulhub/a/docker-compose.yml'),
            '/opt/vulhub/a/docker-compose.yml'
        )


class TestProjectNameVariants(unittest.TestCase):
    def test_dot_version_dir(self):
        variants = _project_name_variants('1.2.24-rce')
        self.assertIn('1-2-24-rce', variants)  # compose v2 归一化
        self.assertIn('1224rce', variants)     # compose v1 归一化

    def test_underscore_dir(self):
        variants = _project_name_variants('weak_password')
        self.assertIn('weak-password', variants)
        self.assertIn('weakpassword', variants)

    def test_cve_dir(self):
        variants = _project_name_variants('CVE-2017-12629')
        self.assertIn('cve-2017-12629', variants)


class TestMatches(unittest.TestCase):
    def test_standard_prefix(self):
        self.assertTrue(_matches('ssti-web-1', 'ssti'))

    def test_underscore_variant_matches_v2_container(self):
        variants = _project_name_variants('weak_password')
        self.assertTrue(any(_matches('weak-password-web-1', v) for v in variants))

    def test_prefix_rule_matches_short_name(self):
        # 规则 2 标准前缀：容器名 = 项目名-service-序号
        self.assertTrue(_matches('cve-2020-10199-web-1', 'cve'))

    def test_substring_boundary_protection(self):
        # 规则 3 子串匹配要求 _ - 分隔符边界
        self.assertTrue(_matches('my_cve_2020', 'cve'))
        self.assertFalse(_matches('my_cveX_2020', 'cve'))

    def test_parent_prefix_scenario(self):
        # 实际调用处容器名已 lower，子串两侧为 _ 边界 → 匹配
        self.assertTrue(_matches('nexus_cve-2020-10199', 'cve-2020-10199'))


class TestReconcileWithDocker(unittest.TestCase):
    def setUp(self):
        cache_mod.invalidate_docker_state_cache()

    def test_docker_unavailable_keeps_running(self):
        """Docker 完全不可用时绝不丢失 running 状态"""
        envs = [_env('flask/ssti', 'running')]
        with patch.object(cache_mod, '_get_compose_ls_projects', return_value=(None, False)), \
             patch.object(cache_mod, '_get_project_labels', return_value=None), \
             patch.object(cache_mod, '_get_running_container_names', return_value=None):
            self.assertFalse(reconcile_cache_with_docker(envs))
        self.assertEqual(envs[0]['status'], 'running')

    def test_exact_config_match_sets_running(self):
        """compose ls 路径精确匹配 → running"""
        projects = [{"name": "ssti", "running": True,
                     "config_files": ["/opt/vulhub/flask/ssti/docker-compose.yml"]}]
        envs = [_env('flask/ssti', 'unknown')]
        with patch.object(cache_mod, 'get_vulhub_path', return_value=Path('/opt/vulhub')), \
             patch.object(cache_mod, '_get_compose_ls_projects', return_value=(projects, True)), \
             patch.object(cache_mod, '_get_project_labels', return_value=None), \
             patch.object(cache_mod, '_get_running_container_names', return_value=set()):
            self.assertTrue(reconcile_cache_with_docker(envs))
        self.assertEqual(envs[0]['status'], 'running')

    def test_exact_config_match_windows_paths(self):
        """Windows 反斜杠路径与 POSIX 路径可互相比对"""
        projects = [{"name": "ssti", "running": True,
                     "config_files": [r'D:\VulHub\flask\ssti\docker-compose.yml']}]
        envs = [_env('flask/ssti', 'unknown')]
        with patch.object(cache_mod, 'get_vulhub_path', return_value=Path('D:/VulHub')), \
             patch.object(cache_mod, '_get_compose_ls_projects', return_value=(projects, True)), \
             patch.object(cache_mod, '_get_project_labels', return_value=None), \
             patch.object(cache_mod, '_get_running_container_names', return_value=set()):
            reconcile_cache_with_docker(envs)
        self.assertEqual(envs[0]['status'], 'running')

    def test_authoritative_empty_list_downgrades_running(self):
        """拿到权威全量清单且项目不存在 → running 下调为 stopped"""
        envs = [_env('flask/ssti', 'running')]
        with patch.object(cache_mod, 'get_vulhub_path', return_value=Path('/opt/vulhub')), \
             patch.object(cache_mod, '_get_compose_ls_projects', return_value=([], True)), \
             patch.object(cache_mod, '_get_project_labels', return_value=set()), \
             patch.object(cache_mod, '_get_running_container_names', return_value=set()):
            self.assertTrue(reconcile_cache_with_docker(envs))
        self.assertEqual(envs[0]['status'], 'stopped')

    def test_non_authoritative_no_match_keeps_running(self):
        """无权威清单（如 compose ls 不可用）时不盲目下调"""
        envs = [_env('flask/ssti', 'running')]
        with patch.object(cache_mod, 'get_vulhub_path', return_value=Path('/opt/vulhub')), \
             patch.object(cache_mod, '_get_compose_ls_projects', return_value=(None, False)), \
             patch.object(cache_mod, '_get_project_labels', return_value=set()), \
             patch.object(cache_mod, '_get_running_container_names', return_value=set()):
            self.assertFalse(reconcile_cache_with_docker(envs))
        self.assertEqual(envs[0]['status'], 'running')

    def test_container_name_fallback(self):
        """compose ls 不可用时，容器名变体匹配可恢复 running"""
        envs = [_env('flask/ssti', 'unknown')]
        with patch.object(cache_mod, 'get_vulhub_path', return_value=Path('/opt/vulhub')), \
             patch.object(cache_mod, '_get_compose_ls_projects', return_value=(None, False)), \
             patch.object(cache_mod, '_get_project_labels', return_value=None), \
             patch.object(cache_mod, '_get_running_container_names', return_value={'ssti-web-1'}):
            self.assertTrue(reconcile_cache_with_docker(envs))
        self.assertEqual(envs[0]['status'], 'running')

    def test_project_label_fallback(self):
        """项目标签匹配（显式 container_name 的场景）"""
        envs = [_env('cve/2018/CVE-2018-1273', 'unknown')]
        with patch.object(cache_mod, 'get_vulhub_path', return_value=Path('/opt/vulhub')), \
             patch.object(cache_mod, '_get_compose_ls_projects', return_value=(None, False)), \
             patch.object(cache_mod, '_get_project_labels', return_value={'cve-2018-1273'}), \
             patch.object(cache_mod, '_get_running_container_names', return_value=set()):
            self.assertTrue(reconcile_cache_with_docker(envs))
        self.assertEqual(envs[0]['status'], 'running')

    def test_compose_ls_name_variant_sets_stopped(self):
        """项目名变体匹配到 exited 项目 → stopped"""
        projects = [{"name": "cve-2017-12629", "running": False, "config_files": []}]
        envs = [_env('solr/CVE-2017-12629', 'running')]
        with patch.object(cache_mod, 'get_vulhub_path', return_value=Path('/opt/vulhub')), \
             patch.object(cache_mod, '_get_compose_ls_projects', return_value=(projects, True)), \
             patch.object(cache_mod, '_get_project_labels', return_value=set()), \
             patch.object(cache_mod, '_get_running_container_names', return_value=set()):
            self.assertTrue(reconcile_cache_with_docker(envs))
        self.assertEqual(envs[0]['status'], 'stopped')


class TestDockerStateCacheRace(unittest.TestCase):
    """查询期间发生失效重建（启停并发）时，旧快照不得写回新缓存"""
    def setUp(self):
        cache_mod.invalidate_docker_state_cache()

    def test_stale_ps_result_not_cached_after_invalidate(self):
        from types import SimpleNamespace
        calls = {"n": 0}

        def fake_run(*args, **kwargs):
            if calls["n"] == 0:
                cache_mod.invalidate_docker_state_cache()  # 模拟查询期间完成启停
            calls["n"] += 1
            return SimpleNamespace(returncode=0, stdout="old-container\n", stderr="")

        with patch.object(cache_mod.subprocess, 'run', fake_run):
            names = cache_mod._get_running_container_names()
        self.assertEqual(names, {"old-container"})
        self.assertEqual(calls["n"], 1)

        # 旧快照未写回缓存 → 第二次调用重新查询
        with patch.object(cache_mod.subprocess, 'run', fake_run):
            cache_mod._get_running_container_names()
        self.assertEqual(calls["n"], 2)

    def test_stale_compose_ls_not_cached_after_invalidate(self):
        from types import SimpleNamespace
        calls = {"n": 0}

        def fake_run(*args, **kwargs):
            if calls["n"] == 0:
                cache_mod.invalidate_docker_state_cache()
            calls["n"] += 1
            line = json.dumps({"Name": "ssti", "Status": "running(1)",
                               "ConfigFiles": "/x/docker-compose.yml"}) + "\n"
            return SimpleNamespace(returncode=0, stdout=line, stderr="")

        with patch.object(cache_mod.subprocess, 'run', fake_run):
            projects, authoritative = cache_mod._get_compose_ls_projects()
        self.assertTrue(authoritative)
        self.assertEqual(calls["n"], 1)

        with patch.object(cache_mod.subprocess, 'run', fake_run):
            cache_mod._get_compose_ls_projects()
        self.assertEqual(calls["n"], 2)


class TestComposeLsParsing(unittest.TestCase):
    """docker compose ls --format json 两种输出格式兼容"""
    def test_json_array_format(self):
        """部分 compose 版本输出单个 JSON 数组（用户服务器实际格式）"""
        stdout = json.dumps([
            {"Name": "ssti", "Status": "running(1)", "ConfigFiles": "/v/flask/ssti/docker-compose.yml"},
            {"Name": "weblogic", "Status": "exited(1)", "ConfigFiles": "/v/weblogic/weak_password/docker-compose.yml"},
        ])
        items = _parse_compose_ls_items(stdout)
        self.assertEqual(len(items), 2)
        proj = _project_from_ls_item(items[0])
        self.assertTrue(proj["running"])
        self.assertEqual(proj["config_files"], ["/v/flask/ssti/docker-compose.yml"])

    def test_json_array_pretty_printed(self):
        stdout = json.dumps(
            [{"Name": "ssti", "Status": "running(1)", "ConfigFiles": "/x/docker-compose.yml"}],
            indent=2
        )
        items = _parse_compose_ls_items(stdout)
        self.assertEqual(len(items), 1)

    def test_jsonl_format(self):
        stdout = '{"Name":"a","Status":"running(1)","ConfigFiles":"/a/docker-compose.yml"}\n' \
                 '{"Name":"b","Status":"exited(1)","ConfigFiles":"/b/docker-compose.yml"}\n'
        items = _parse_compose_ls_items(stdout)
        self.assertEqual(len(items), 2)

    def test_config_files_as_list(self):
        proj = _project_from_ls_item({
            "Name": "ssti", "Status": "running(1)",
            "ConfigFiles": ["/x/docker-compose.yml", "/x/override.yml"]
        })
        self.assertEqual(proj["config_files"], ["/x/docker-compose.yml", "/x/override.yml"])

    def test_garbage_lines_ignored(self):
        stdout = 'not-json\n{"Name":"a","Status":"running(1)","ConfigFiles":""}\n'
        items = _parse_compose_ls_items(stdout)
        self.assertEqual(len(items), 1)


class TestReconcileCrashSafety(unittest.TestCase):
    """Docker 状态同步任何异常都不能拖垮列表接口"""
    def setUp(self):
        cache_mod.invalidate_docker_state_cache()

    def test_reconcile_exception_is_contained(self):
        envs = [_env('flask/ssti', 'running')]
        with patch.object(cache_mod, '_get_compose_ls_projects', side_effect=Exception('boom')):
            self.assertFalse(reconcile_cache_with_docker(envs))
        self.assertEqual(envs[0]['status'], 'running')  # 状态未被破坏


class TestDockerStateCacheTTL(unittest.TestCase):
    """失败结果缓存 30 秒（避免每次请求阻塞），成功结果 2 秒"""
    def test_failure_cached_30s(self):
        cache = {"data": None, "ts": 1000000}
        self.assertTrue(cache_mod._cache_fresh(cache, 1000000 + 29000))
        self.assertFalse(cache_mod._cache_fresh(cache, 1000000 + 31000))

    def test_success_cached_2s(self):
        cache = {"data": set(), "ts": 1000000}
        self.assertTrue(cache_mod._cache_fresh(cache, 1000000 + 1000))
        self.assertFalse(cache_mod._cache_fresh(cache, 1000000 + 3000))


class TestUpdatePersistentCacheEntry(unittest.TestCase):
    def test_update_existing_entry(self):
        with tempfile.TemporaryDirectory() as d:
            f = Path(d) / 'cache.json'
            f.write_text(json.dumps({
                "environments": [{"name": "a/b", "status": "stopped"}],
                "timestamp": 1
            }), encoding='utf-8')
            with patch.object(cache_mod, 'CACHE_FILE', f):
                self.assertTrue(update_persistent_cache_entry('a/b', 'running'))
                data = json.loads(f.read_text(encoding='utf-8'))
                self.assertEqual(data['environments'][0]['status'], 'running')

    def test_env_not_in_file(self):
        with tempfile.TemporaryDirectory() as d:
            f = Path(d) / 'cache.json'
            f.write_text(json.dumps({
                "environments": [{"name": "a/b", "status": "stopped"}],
                "timestamp": 1
            }), encoding='utf-8')
            with patch.object(cache_mod, 'CACHE_FILE', f):
                self.assertFalse(update_persistent_cache_entry('x/y', 'running'))

    def test_missing_file(self):
        with tempfile.TemporaryDirectory() as d:
            with patch.object(cache_mod, 'CACHE_FILE', Path(d) / 'not_exist.json'):
                self.assertFalse(update_persistent_cache_entry('a/b', 'running'))

    def test_no_tmp_leftover_after_update(self):
        with tempfile.TemporaryDirectory() as d:
            f = Path(d) / 'cache.json'
            f.write_text(json.dumps({
                "environments": [{"name": "a/b", "status": "stopped"}],
                "timestamp": 1
            }), encoding='utf-8')
            with patch.object(cache_mod, 'CACHE_FILE', f):
                self.assertTrue(update_persistent_cache_entry('a/b', 'running'))
            leftovers = list(Path(d).glob('cache.json.tmp.*'))
            self.assertEqual(leftovers, [])
            data = json.loads(f.read_text(encoding='utf-8'))
            self.assertEqual(data['environments'][0]['status'], 'running')

    def test_save_persistent_cache_is_valid_json(self):
        with tempfile.TemporaryDirectory() as d:
            f = Path(d) / 'cache.json'
            with patch.object(cache_mod, 'CACHE_FILE', f), \
                 patch.object(cache_mod, 'get_vulhub_path', return_value=Path('/opt/vulhub')):
                cache_mod.save_persistent_cache([{"name": "a/b", "status": "running"}])
            data = json.loads(f.read_text(encoding='utf-8'))
            self.assertEqual(data['environments'][0]['status'], 'running')
            # 路径以 str(Path) 的本地格式存储，读取端用同格式比对
            self.assertEqual(data['vulhub_path'], str(Path('/opt/vulhub')))


if __name__ == '__main__':
    unittest.main()
