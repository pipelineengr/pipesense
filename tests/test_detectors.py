"""Tests for spike detector, drift detector, and detection engine."""
from __future__ import annotations

import pytest
from datetime import datetime, timezone
from unittest.mock import MagicMock

from pipesense.detection.base import AlarmEvent, AlarmSeverity, Detector
from pipesense.detection.spike import SpikeDetector
from pipesense.detection.drift import DriftDetector
from pipesense.detection.engine import DetectionEngine
from pipesense.sources.base import TagReading


def _reading(value: float, tag: str = "FT-101", quality: str = "Good") -> TagReading:
    return TagReading(
        tag_id=tag,
        value=value,
        timestamp=datetime.now(timezone.utc),
        quality=quality,
    )


def _warm_spike(detector: SpikeDetector, value: float = 100.0, count: int = 25) -> None:
    import random
    rng = random.Random(85)
    for _ in range(count):
        detector.update(_reading(value + rng.gauss(0, 1.0)))


class TestSpikeDetector:
    def test_not_ready_before_window(self):
        det = SpikeDetector("FT-101", window=20)
        for i in range(19):
            result = det.update(_reading(100.0))
            assert result is None
        # print(f"\n  [test_not_ready_before_window] buffer={len(det._buffer)}/20, ready={det.ready}")
        assert not det.ready

    def test_ready_after_window(self):
        det = SpikeDetector("FT-101", window=20)
        _warm_spike(det)
        # print(f"\n  [test_ready_after_window] buffer={len(det._buffer)}/20, ready={det.ready}")
        assert det.ready

    def test_no_alarm_on_normal_value(self):
        det = SpikeDetector("FT-101", window=20, warn_sigma=3.0)
        _warm_spike(det)
        result = det.update(_reading(101.0))
        # print(f"\n  [test_no_alarm_on_normal_value] result={result}")
        assert result is None

    def test_warn_alarm_on_moderate_spike(self):
        det = SpikeDetector("FT-101", window=20, warn_sigma=3.0, crit_sigma=5.0)
        _warm_spike(det)
        result = det.update(_reading(103.0))
        # print(f"\n  [test_warn_alarm_on_moderate_spike] severity={result.severity if result else None}, z_score={result.metadata.get('z_score') if result else 'N/A'}")
        assert result is not None
        assert result.severity == AlarmSeverity.LOW
        assert result.detector == "spike"
        assert result.tag_id == "FT-101"

    def test_critical_alarm_on_large_spike(self):
        det = SpikeDetector("FT-101", window=20, warn_sigma=3.0, crit_sigma=5.0)
        _warm_spike(det)
        result = det.update(_reading(10000.0))
        # print(f"\n  [test_critical_alarm_on_large_spike] severity={result.severity if result else None}, z_score={result.metadata.get('z_score') if result else 'N/A'}")
        assert result is not None
        assert result.severity == AlarmSeverity.CRITICAL

    def test_bad_quality_ignored(self):
        det = SpikeDetector("FT-101", window=20)
        _warm_spike(det)
        result = det.update(_reading(99999.0, quality="Bad"))
        # print(f"\n  [test_bad_quality_ignored] result={result} (expected None — Bad quality skipped)")
        assert result is None

    def test_min_std_prevents_false_alarm_on_stable_channel(self):
        det = SpikeDetector("TT-301", window=20, warn_sigma=3.0, min_std=0.5)
        _warm_spike(det, value=20.0)
        result = det.update(_reading(20.1))
        # print(f"\n  [test_min_std_prevents_false_alarm] result={result} (min_std=0.5 absorbs small deviation)")
        assert result is None

    def test_reset_clears_buffer(self):
        det = SpikeDetector("FT-101", window=20)
        _warm_spike(det)
        # print(f"\n  [test_reset_clears_buffer] before reset: buffer={len(det._buffer)}, ready={det.ready}")
        assert det.ready
        det.reset()
        # print(f"  [test_reset_clears_buffer] after reset:  buffer={len(det._buffer)}, ready={det.ready}")
        assert not det.ready

    def test_alarm_event_has_metadata(self):
        det = SpikeDetector("FT-101", window=20)
        _warm_spike(det, value=100.0)
        result = det.update(_reading(500.0))
        # print(f"\n  [test_alarm_event_has_metadata] metadata={result.metadata if result else None}")
        assert result is not None
        assert "z_score" in result.metadata
        assert "mean" in result.metadata


class TestDriftDetector:
    def test_no_alarm_at_baseline(self):
        det = DriftDetector("PT-201", baseline_mean=500.0, baseline_std=5.0, k=0.5, h=5.0)
        for _ in range(50):
            result = det.update(_reading(500.0, tag="PT-201"))
            assert result is None
        # print(f"\n  [test_no_alarm_at_baseline] cusum_pos={det._cusum_pos:.4f}, cusum_neg={det._cusum_neg:.4f} (both near 0)")

    def test_upward_drift_detected(self):
        det = DriftDetector("PT-201", baseline_mean=500.0, baseline_std=5.0, k=0.5, h=5.0)
        alarm = None
        for _ in range(60):
            alarm = det.update(_reading(510.0, tag="PT-201"))
            if alarm is not None:
                # print(f"\n  [test_upward_drift_detected] alarm fired on reading {i+1}: direction={alarm.metadata['direction']}, severity={alarm.severity}")
                break
        assert alarm is not None
        assert alarm.detector == "drift"
        assert alarm.metadata["direction"] == "high"

    def test_downward_drift_detected(self):
        det = DriftDetector("PT-201", baseline_mean=500.0, baseline_std=5.0, k=0.5, h=5.0)
        alarm = None
        for _ in range(60):
            alarm = det.update(_reading(490.0, tag="PT-201"))
            if alarm is not None:
                # print(f"\n  [test_downward_drift_detected] alarm fired on reading {i+1}: direction={alarm.metadata['direction']}, severity={alarm.severity}")
                break
        assert alarm is not None
        assert alarm.metadata["direction"] == "low"

    def test_no_repeated_alarm_while_drift_active(self):
        det = DriftDetector("PT-201", baseline_mean=500.0, baseline_std=5.0, k=0.5, h=5.0)
        alarms = []
        for _ in range(100):
            r = det.update(_reading(510.0, tag="PT-201"))
            if r:
                alarms.append(r)
        # print(f"\n  [test_no_repeated_alarm_while_drift_active] total alarms fired over 100 readings: {len(alarms)} (expected 1)")
        assert len(alarms) == 1

    def test_reset_clears_cusum(self):
        det = DriftDetector("PT-201", baseline_mean=500.0, baseline_std=5.0, h=5.0)
        for _ in range(50):
            det.update(_reading(510.0, tag="PT-201"))
        det.reset()
        # print(f"\n  [test_reset_clears_cusum] before reset: cusum_pos={det._cusum_pos:.4f}, cusum_neg={det._cusum_neg:.4f}, drift_active={det._drift_active}")
        assert det._cusum_pos == 0.0
        assert det._cusum_neg == 0.0
        assert not det._drift_active

    def test_bad_quality_skipped(self):
        det = DriftDetector("PT-201", baseline_mean=500.0, baseline_std=5.0, h=5.0)
        result = det.update(_reading(99999.0, tag="PT-201", quality="Bad"))
        # print(f"\n  [test_bad_quality_skipped] result={result} (expected None — Bad quality skipped)")
        assert result is None

    def test_alarm_event_as_dict(self):
        det = DriftDetector("PT-201", baseline_mean=500.0, baseline_std=5.0, h=5.0)
        alarm = None
        for _ in range(60):
            alarm = det.update(_reading(510.0, tag="PT-201"))
            if alarm:
                break
        # print(f"\n  [test_alarm_event_as_dict] as_dict keys={list(alarm.as_dict().keys()) if alarm else None}")
        assert alarm is not None
        d = alarm.as_dict()
        assert d["detector"] == "drift"
        assert "baseline_mean" in d["metadata"]


class TestDetectionEngine:
    def _make_site(self):
        from pipesense.config.schema import (
            ChannelConfig, DetectionConfig, SpikeDetectionConfig,
            DriftDetectionConfig, SiteConfig, Thresholds,
        )
        thresh = Thresholds(low_low=0.0, low=10.0, high=900.0, high_high=1000.0)
        channels = [
            ChannelConfig(                          
                id="FT-101",                        
                name="Flow",
                description="",                     
                opc_node="ns=2;s=FT101.PV",        
                pi_tag="OIL.FT101.PV",             
                unit="m3/h",
                type="flow",                        
                poll_interval_s=5,
                thresholds=thresh,
            ),
            ChannelConfig(
                id="PT-201",                        
                name="Pressure",
                description="",
                opc_node="ns=2;s=PT201.PV",
                pi_tag="OIL.PT201.PV",
                unit="kPa",
                type="pressure",                   
                poll_interval_s=5,
                thresholds=thresh,
            ),
        ]
        detection = DetectionConfig(
            spike=SpikeDetectionConfig(
                enabled=True,
                z_threshold=3.0,                   
                crit_sigma=5.0,                    
                min_samples=20,                    
            ),
            drift=DriftDetectionConfig(
                enabled=True,
                cusum_slack=0.5,                   
                cusum_threshold=5.0,              
            ),
        )
        return MagicMock(channels=channels, detection=detection)

    def test_engine_builds_detectors(self):
        site = self._make_site()
        baseline = {"PT-201": {"mean": 500.0, "std": 5.0}}
        eng = DetectionEngine(site, baseline_stats=baseline)
        #  print(f"\n  [test_engine_builds_detectors] detector_count={eng.detector_count()}")
        assert eng.detector_count() > 0

    def test_process_unknown_tag_returns_empty(self):
        site = self._make_site()
        eng = DetectionEngine(site)
        result = eng.process(_reading(100.0, tag="UNKNOWN"))
        # print(f"\n  [test_process_unknown_tag_returns_empty] result={result} (expected [])")
        assert result == []

    def test_process_returns_alarm_on_spike(self):
        site = self._make_site()
        eng = DetectionEngine(site)
        for _ in range(25):
            eng.process(_reading(100.0, tag="FT-101"))
        alarms = eng.process(_reading(99999.0, tag="FT-101"))
        # print(f"\n  [test_process_returns_alarm_on_spike] alarms={[(a.detector, a.severity.value) for a in alarms]}")
        assert len(alarms) > 0
        assert alarms[0].detector == "spike"

    def test_reset_all(self):
        site = self._make_site()
        eng = DetectionEngine(site)
        for _ in range(25):
            eng.process(_reading(100.0, tag="FT-101"))
        eng.reset()
        alarms = eng.process(_reading(99999.0, tag="FT-101"))
        # print(f"\n  [test_reset_all] alarms after reset+1 reading={alarms} (expected [])")
        assert alarms == []

    def test_no_drift_detector_without_baseline(self):
        site = self._make_site()
        eng = DetectionEngine(site, baseline_stats={})
        detectors = eng._detectors.get("PT-201", [])
        types = [type(d).__name__ for d in detectors]
        # print(f"\n  [test_no_drift_detector_without_baseline] detectors on PT-201={types}")
        assert "DriftDetector" not in types