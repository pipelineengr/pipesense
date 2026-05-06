"""Tests for pipesense config loader and validation."""

"""Are more tests needed?"""
"""ADD HERE"""

import pytest
import yaml
from pipesense.config.loader import ConfigError, load_config
from pipesense.config.schema import PipesenseConfig


@pytest.fixture
def valid_yaml(tmp_path):
    data = {
        "version": "1.0",
        "sites": [{
            "id": "TEST-001", "name": "Test Site",
            "opc_ua_endpoint": "opc.tcp://localhost:4840",
            "channels": [{
                "id": "FT-001", "name": "Test Flow",
                "opc_node": "ns=2;s=TEST.FT001.PV",
                "pi_tag": "TEST.FT001.PV",
                "unit": "m3/h", "type": "flow",
                "poll_interval_s": 5,
                "thresholds": {
                    "low_low": 0.0, "low": 10.0,
                    "high": 90.0, "high_high": 100.0
                }
            }],
            "detection": {
                "spike": {"enabled": True, "z_threshold": 3.5, "min_samples": 10},
                "drift": {"enabled": True, "cusum_threshold": 5.0,
                          "cusum_slack": 0.5, "window_s": 300}
            }
        }]
    }
    p = tmp_path / "config.yaml"
    p.write_text(yaml.dump(data))
    return p


def test_load_returns_config(valid_yaml):
    assert isinstance(load_config(valid_yaml), PipesenseConfig)

def test_load_site_id(valid_yaml):
    assert load_config(valid_yaml).sites[0].id == "TEST-001"

def test_load_channel_count(valid_yaml):
    assert len(load_config(valid_yaml).sites[0].channels) == 1

def test_load_channel_thresholds(valid_yaml):
    t = load_config(valid_yaml).sites[0].channels[0].thresholds
    assert t.high_high == pytest.approx(100.0)
    assert t.low_low == pytest.approx(0.0)

def test_load_real_config_file():
    config = load_config("config/site_default.yaml")
    assert config.sites[0].id == "LACT-001"
    assert len(config.sites[0].channels) == 5

def test_missing_file_raises():
    with pytest.raises(ConfigError, match="not found"):
        load_config("nonexistent.yaml")

def test_malformed_yaml_raises(tmp_path):
    p = tmp_path / "bad.yaml"
    p.write_text("{ unclosed: [bracket")
    with pytest.raises(ConfigError, match="YAML parse error"):
        load_config(p)

def test_missing_sites_raises(tmp_path):
    p = tmp_path / "nosites.yaml"
    p.write_text("version: '1.0'\n")
    with pytest.raises(ConfigError, match="sites"):
        load_config(p)

def test_invalid_channel_type_raises(valid_yaml, tmp_path):
    data = yaml.safe_load(valid_yaml.read_text())
    data["sites"][0]["channels"][0]["type"] = "radioactive"
    p = tmp_path / "bad_type.yaml"
    p.write_text(yaml.dump(data))
    with pytest.raises(ConfigError, match="invalid type"):
        load_config(p)

def test_inverted_thresholds_raises(valid_yaml, tmp_path):
    data = yaml.safe_load(valid_yaml.read_text())
    data["sites"][0]["channels"][0]["thresholds"]["high_high"] = 1.0
    data["sites"][0]["channels"][0]["thresholds"]["low_low"] = 999.0
    p = tmp_path / "inv.yaml"
    p.write_text(yaml.dump(data))
    with pytest.raises(ConfigError, match="low_low <= low"):
        load_config(p)

def test_zero_poll_interval_raises(valid_yaml, tmp_path):
    data = yaml.safe_load(valid_yaml.read_text())
    data["sites"][0]["channels"][0]["poll_interval_s"] = 0
    p = tmp_path / "zero_poll.yaml"
    p.write_text(yaml.dump(data))
    with pytest.raises(ConfigError, match="poll_interval_s"):
        load_config(p)

def test_empty_channels_raises(valid_yaml, tmp_path):
    data = yaml.safe_load(valid_yaml.read_text())
    data["sites"][0]["channels"] = []
    p = tmp_path / "empty_ch.yaml"
    p.write_text(yaml.dump(data))
    with pytest.raises(ConfigError, match="at least one channel"):
        load_config(p)

def test_threshold_check_high_high(valid_yaml):
    t = load_config(valid_yaml).sites[0].channels[0].thresholds
    assert t.check(101.0) == "HIGH_HIGH"

def test_threshold_check_normal(valid_yaml):
    t = load_config(valid_yaml).sites[0].channels[0].thresholds
    assert t.check(50.0) is None

def test_get_channel_by_id(valid_yaml):
    ch = load_config(valid_yaml).sites[0].get_channel("FT-001")
    assert ch is not None and ch.name == "Test Flow"

def test_get_channel_missing_returns_none(valid_yaml):
    assert load_config(valid_yaml).sites[0].get_channel("NOPE") is None