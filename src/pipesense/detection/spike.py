"""Functions to detect sudden spikes through difference from base setpoint, positive or negative"""

from __future__ import annotations

import math
from collections import deque

from pipesense.detection.base import AlarmEvent, AlarmSeverity, Detector
from pipesense.sources.base import TagReading


class SpikeDetector(Detector):
    def __init__(
        self,
        tag_id: str,
        window: int = 20,
        warn_sigma: float = 3.0,
        crit_sigma: float = 5.0,
        min_std: float = 0.01,
    ) -> None:
        super().__init__(tag_id)
        self._window = window
        self._warn_sigma = warn_sigma
        self._crit_sigma = crit_sigma
        self._min_std = min_std
        self._buffer: deque[float] = deque(maxlen=window)

    @property
    def ready(self) -> bool:
        return len(self._buffer) >= self._window

    def _rolling_stats(self) -> tuple[float, float]:
        n = len(self._buffer)
        mean = sum(self._buffer) / n
        variance = sum((x - mean) ** 2 for x in self._buffer) / n
        std = math.sqrt(variance)

        # Print statement to show rolling mean and std after each iteration
        # enable this to see how stable the baseline is across readings.

        # print(f"[SpikeDetector:{self.tag_id}] rolling stats — mean={mean:.4f} std={std:.4f} "
        #       f"(effective std={max(std, self._min_std):.4f})")

        return mean, max(std, self._min_std)

    def update(self, reading: TagReading) -> AlarmEvent | None:
        if reading.quality == "Bad":
            return None

        value = reading.value
        self._reading_count += 1

        # Print statement to show buffer fill progress during warm-up
        # enable this to confirm readings are accumulating before the detector arms.

        # print(f"[SpikeDetector:{self.tag_id}] buffer {len(self._buffer)}/{self._window} "
        #       f"reading #{self._reading_count} value={value:.3f} ready={self.ready}")

        if not self.ready:
            self._buffer.append(value)
            return None

        mean, std = self._rolling_stats()
        self._buffer.append(value)
        z = abs(value - mean) / std

        # Print statement to show the z-score for every reading once the detector is armed
        # enable this to observe normal variation (where the deviation is less than 1 stdev)
        # versus a real spike (deviation higher than 3 stdev).
        # Currently, severity levels are at WARNING/LOW for z > 3 and CRITICAL when z is above 5

        # print(f"[SpikeDetector:{self.tag_id}] z-score={z:.3f} value={value:.3f} "
        #       f"mean={mean:.3f} std={std:.3f} warn_thresh={self._warn_sigma} crit_thresh={self._crit_sigma}")

        severity: AlarmSeverity | None = None
        if z >= self._crit_sigma:
            severity = AlarmSeverity.CRITICAL
        elif z >= self._warn_sigma:
            severity = AlarmSeverity.LOW

        # Print statement to show the threshold comparison result for every iteration
        # enable this to see which readings clear the threshold and which are silently discarded.

        # print(f"[SpikeDetector:{self.tag_id}] threshold check — z={z:.3f} result={'ALARM:' + severity.value if severity else 'no alarm'}")

        if severity is None:
            return None

        event = AlarmEvent(
            tag_id=self.tag_id,
            severity=severity,
            detector="spike",
            value=value,
            timestamp=reading.timestamp,
            message=(
                f"{self.tag_id} spike detected: value={value:.3f}, "
                f"z={z:.2f}, mean={mean:.3f}, std={std:.3f}"
            ),
            metadata={
                "z_score": round(z, 4),
                "mean": round(mean, 4),
                "std": round(std, 4),
            },
        )

        # Print statement to show details for the iteration when the spike detector is trigerred
        # enable this to confirm severity and incoming values, detector calculations are correct
        # before the detector engine (combined handler for all detector types) collects it.

        # print(f"[SpikeDetector:{self.tag_id}] ALARM FIRED — {event.severity.value} z={z:.3f}")
        return event

    def reset(self) -> None:
        self._buffer.clear()
        self._reading_count = 0
