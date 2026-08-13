# coding: utf-8
"""config.get_vulhub_path 路径解析逻辑测试（不依赖真实环境配置）"""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app import config as config_mod


class TestVulhubPathResolution(unittest.TestCase):
    def test_config_file_change_takes_effect_without_restart(self):
        """外部修改配置文件后（如其他 worker 进程写入），再次解析应立即生效

        旧实现有进程级缓存，此场景下会一直返回旧路径。
        """
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            v1 = d / 'vulhub_a'
            v1.mkdir()
            v2 = d / 'vulhub_b'
            v2.mkdir()
            cfg = d / 'app_config.json'
            cfg.write_text(json.dumps({"vulhub_path": str(v1)}), encoding='utf-8')

            with patch.dict('os.environ', {'VULHUB_PATH': ''}), \
                 patch.object(config_mod, 'APP_CONFIG_FILE', cfg):
                self.assertEqual(config_mod.get_vulhub_path(), v1.resolve())
                # 模拟另一进程 / 外部修改配置文件
                cfg.write_text(json.dumps({"vulhub_path": str(v2)}), encoding='utf-8')
                self.assertEqual(config_mod.get_vulhub_path(), v2.resolve())

    def test_config_file_priority_over_env(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            v_cfg = d / 'from_cfg'
            v_cfg.mkdir()
            v_env = d / 'from_env'
            v_env.mkdir()
            cfg = d / 'app_config.json'
            cfg.write_text(json.dumps({"vulhub_path": str(v_cfg)}), encoding='utf-8')

            with patch.dict('os.environ', {'VULHUB_PATH': str(v_env)}), \
                 patch.object(config_mod, 'APP_CONFIG_FILE', cfg):
                self.assertEqual(config_mod.get_vulhub_path(), v_cfg.resolve())

    def test_env_fallback_when_config_invalid(self):
        """配置文件中的路径不存在时，回退到环境变量"""
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            v_env = d / 'from_env'
            v_env.mkdir()
            cfg = d / 'app_config.json'
            cfg.write_text(json.dumps({"vulhub_path": str(d / 'missing_dir')}), encoding='utf-8')

            with patch.dict('os.environ', {'VULHUB_PATH': str(v_env)}), \
                 patch.object(config_mod, 'APP_CONFIG_FILE', cfg):
                self.assertEqual(config_mod.get_vulhub_path(), v_env.resolve())

    def test_set_vulhub_path_expands_tilde(self):
        """~/xxx 形式路径应展开到用户主目录"""
        with tempfile.TemporaryDirectory() as d, \
             patch.object(config_mod, 'APP_CONFIG_FILE', Path(d) / 'cfg.json'):
            home = Path(d) / 'home'
            home.mkdir()
            target = home / 'vulhub'
            target.mkdir()

            with patch.dict('os.environ', {'HOME': str(home), 'USERPROFILE': str(home)}):
                ok, msg = config_mod.set_vulhub_path('~/vulhub')
            self.assertTrue(ok, msg)
            self.assertEqual(msg, str(target.resolve()))

            # 写入后 get_vulhub_path 立即读到新路径（无需失效缓存）
            with patch.dict('os.environ', {'VULHUB_PATH': ''}):
                self.assertEqual(config_mod.get_vulhub_path(), target.resolve())


if __name__ == '__main__':
    unittest.main()
