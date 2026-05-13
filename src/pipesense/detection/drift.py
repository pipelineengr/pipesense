"""Functions to detect drift through cumulative sum, positive or negative"""
from __future__ import annotations
from typing import Optional

from pipesense.detection.base import AlarmEvent, AlarmSeverity, Detector
from pipesense.sources.base import TagReading


class DriftDetector(Detector):
    def __init__(
        self,
        tag_id: str,
        baseline_mean: float,
        baseline_std: float,
        k: float = 0.5,
        h: float = 5.0,
    ) -> None:
        super().__init__(tag_id)
        self._mu = baseline_mean
        self._sigma = max(baseline_std, 0.01)
        self._k = k
        self._h = h
        self._cusum_pos: float = 0.0
        self._cusum_neg: float = 0.0
        self._drift_active: bool = False

    def _normalise(self, value: float) -> float:
        return (value - self._mu) / self._sigma

    def update(self, reading: TagReading) -> Optional[AlarmEvent]:
        if reading.quality == "Bad":
            return None

        xi = self._normalise(reading.value)
        self._reading_count += 1

        # Print statement to show the normalised value (xi) for each reading
        # enable this to see what CUSUM actually works with (as multiples of sigma, not the raw unit values).
        # Values near 0 = on baseline. Sustained difference, positive or negative will cause drift to accumulate.
        
        # print(f"[DriftDetector:{self.tag_id}] reading #{self._reading_count} "
        #       f"raw={reading.value:.3f} xi={xi:.4f} (baseline={self._mu}, sigma={self._sigma})")

        self._cusum_pos = max(0.0, self._cusum_pos + xi - self._k)
        self._cusum_neg = max(0.0, self._cusum_neg - xi - self._k)

        # Print statement to show both CUSUM accumulators after every update
        # enable this to watch drift build up gradually. Values climb toward h={h} before an alarm.
        
        # print(f"[DriftDetector:{self.tag_id}] cusum_pos={self._cusum_pos:.4f} "
        #       f"cusum_neg={self._cusum_neg:.4f} threshold={self._h} drift_active={self._drift_active}")

        #If the cumulative drift falls below the limit, the active flag is cleared
        if self._drift_active:
            if self._cusum_pos < self._h and self._cusum_neg < self._h:
                self._drift_active = False
                # Print statement to show when drift_active clears after accumulators fall back below the limit
                # enable this to confirm the detector rearms correctly after a drift event resolves.
                
                # print(f"[DriftDetector:{self.tag_id}] drift_active cleared — detector rearmed")
            return None

        direction: Optional[str] = None
        cusum_val: float = 0.0
        if self._cusum_pos >= self._h:
            direction = "high"
            cusum_val = self._cusum_pos
        elif self._cusum_neg >= self._h:
            direction = "low"
            cusum_val = self._cusum_neg

        if direction is None:
            return None

        # Print statement to show the cumulative sum crossing the threshold (h) triggers the detector alarm —
        # enable this to see which direction the sum crossed the limit and by how much.
        
        # print(f"[DriftDetector:{self.tag_id}] threshold crossed — direction={direction} "
        #       f"cusum_val={cusum_val:.4f} >= h={self._h}")

        self._drift_active = True
        event = AlarmEvent(
            tag_id=self.tag_id,
            severity=AlarmSeverity.HIGH,
            detector="drift",
            value=reading.value,
            timestamp=reading.timestamp,
            message=(
                f"{self.tag_id} drift detected ({direction}): "
                f"value={reading.value:.3f}, CUSUM={cusum_val:.3f}, "
                f"baseline={self._mu:.3f}"
            ),
            metadata={
                "direction": direction,
                "cusum_pos": round(self._cusum_pos, 4),
                "cusum_neg": round(self._cusum_neg, 4),
                "baseline_mean": self._mu,
                "baseline_std": self._sigma,
            },
        )
        # Print statement to show the readings at the moment the detector alarm is triggered
        # enable this alongside the accumulator print above to see exactly which value reading 
        # pushed cusum over threshold.
        
        # print(f"[DriftDetector:{self.tag_id}] DRIFT ALARM — direction={direction} "
        #       f"value={reading.value:.3f} after {self._reading_count} readings")
        
        return event

    def reset(self) -> None:
        self._cusum_pos = 0.0
        self._cusum_neg = 0.0
        self._drift_active = False
        self._reading_count = 0