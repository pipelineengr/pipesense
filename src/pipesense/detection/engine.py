"""Detection Engine Class to run all the detectors. Currently, drift and spike types have been added. 
If more are needed, functions for them will be written under their own class/file and imported here.
"""
from __future__ import annotations
from typing import Optional

from pipesense.config.schema import ChannelConfig, DetectionConfig, SiteConfig
from pipesense.detection.base import AlarmEvent, Detector
from pipesense.detection.drift import DriftDetector
from pipesense.detection.spike import SpikeDetector
from pipesense.sources.base import TagReading


class DetectionEngine:
    def __init__(
        self,
        site: SiteConfig,
        baseline_stats: Optional[dict[str, dict[str, float]]] = None,
    ) -> None:
        self._site = site
        self._baseline_stats = baseline_stats or {}
        self._detectors: dict[str, list[Detector]] = {}
        self._build(site.channels, site.detection)

    def _build(
        self,
        channels: list[ChannelConfig],
        detection: DetectionConfig,
    ) -> None:
        for ch in channels:
            detectors: list[Detector] = []

            if detection.spike.enabled:
                detectors.append(
                    SpikeDetector(
                        tag_id=ch.tag_id,
                        window=detection.spike.window,
                        warn_sigma=detection.spike.warn_sigma,
                        crit_sigma=detection.spike.crit_sigma,
                    )
                )

            if detection.drift.enabled and ch.tag_id in self._baseline_stats:
                stats = self._baseline_stats[ch.tag_id]
                detectors.append(
                    DriftDetector(
                        tag_id=ch.tag_id,
                        baseline_mean=stats["mean"],
                        baseline_std=stats["std"],
                        k=detection.drift.k,
                        h=detection.drift.h,
                    )
                )

            self._detectors[ch.tag_id] = detectors
            # Print statement to show which detectors are configured for each channel
            # in the YAML file enable this to confirm all the detectors are showing up
            # and to check if any channels that got skipped due to missing baseline values.
            
            # print(f"[DetectionEngine] built channel={ch.tag_id} "
            #       f"detectors={[type(d).__name__ for d in detectors]}")

    def process(self, reading: TagReading) -> list[AlarmEvent]:
        detectors = self._detectors.get(reading.tag_id, [])
        # Print statement to show each reading as it is sent to the detectors
        # enable this to verify the engine is receiving readings and matching 
        # them to the right signal in the channel.
        
        # print(f"[DetectionEngine] routing tag={reading.tag_id} value={reading.value:.3f} "
        #       f"quality={reading.quality} to {len(detectors)} detector(s)")

        events: list[AlarmEvent] = []
        for det in detectors:
            result = det.update(reading)
            if result is not None:
                events.append(result)

        # Print statement to show alarm events collected from all detectors for this reading
        # enable this to see every alarm the engine surfaces before it reaches the caller.
        
        # print(f"[DetectionEngine] tag={reading.tag_id} produced {len(events)} alarm(s): "
        #       f"{[e.severity.value + '/' + e.detector for e in events]}")
        return events

    def reset(self, tag_id: Optional[str] = None) -> None:
        targets = [tag_id] if tag_id else list(self._detectors.keys())
        # Print statement to show which channels are being reset —
        # enable this to confirm reset() is targeting the right tags.
        # print(f"[DetectionEngine] resetting detectors for tags={targets}")
        for tid in targets:
            for det in self._detectors.get(tid, []):
                det.reset()

    def detector_count(self) -> int:
        return sum(len(v) for v in self._detectors.values())