"""
配置加载测试
"""
import os
import pytest
from pathlib import Path

from drift_detector.config import load_config, _expand_env


class TestEnvExpand:
    def test_no_env_var(self):
        assert _expand_env("hello") == "hello"

    def test_env_var_set(self, monkeypatch):
        monkeypatch.setenv("TEST_VAR", "world")
        assert _expand_env("hello ${TEST_VAR}") == "hello world"

    def test_env_var_with_default(self):
        result = _expand_env("${NONEXISTENT_VAR:-default_val}")
        assert result == "default_val"

    def test_env_var_overrides_default(self, monkeypatch):
        monkeypatch.setenv("MY_VAR", "actual")
        assert _expand_env("${MY_VAR:-fallback}") == "actual"


class TestLoadConfig:
    def test_load_from_defaults(self):
        """测试从默认配置目录加载"""
        config_dir = Path(__file__).parent.parent / "config"
        if not config_dir.exists():
            pytest.skip("config directory not found")
        cfg = load_config(
            vendors_path=config_dir / "vendors.yaml",
            probes_path=config_dir / "probes.yaml",
        )
        assert "openai" in cfg.vendors
        assert cfg.vendors["openai"].enabled is True
        assert len(cfg.vendors["openai"].endpoints) > 0

    def test_probes_loaded(self):
        config_dir = Path(__file__).parent.parent / "config"
        if not config_dir.exists():
            pytest.skip("config directory not found")
        cfg = load_config(
            vendors_path=config_dir / "vendors.yaml",
            probes_path=config_dir / "probes.yaml",
        )
        assert "chat_completions" in cfg.probes
        assert cfg.probes["chat_completions"].skip is False
