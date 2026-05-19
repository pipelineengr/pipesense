from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum

from pipesense.sources.base import TagReading


class AlarmSeverity(str, Enum):
    LOW = "LOW"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


@dataclass
class AlarmEvent:
    # Used to implement an Alarm Event when it happens, like crossing the low or high-high limit
    tag_id: str
    severity: AlarmSeverity
    detector: str
    value: float
    timestamp: datetime
    message: str
    metadata: dict = field(default_factory=dict)

    def __post_init__(self):
        # Print statement to show every field on an AlarmEvent the moment it is constructed —
        # useful for confirming tag_id, severity, and metadata are all populated correctly.
        # print(f"[AlarmEvent created] tag={self.tag_id} severity={self.severity.value} "
        #       f"detector={self.detector} value={self.value:.3f} meta={self.metadata}")
        pass

    def as_dict(self) -> dict:
        result = {
            "tag_id": self.tag_id,
            "severity": self.severity.value,
            "detector": self.detector,
            "value": self.value,
            "timestamp": self.timestamp.isoformat(),
            "message": self.message,
            "metadata": self.metadata,
        }
        # Print statement to show the dictionary that will be written as a JSON line —
        # enable this to verify the shape before wiring up the alarm log in Week 4.
        # print(f"[AlarmEvent.as_dict] {result}")
        return result


class Detector(ABC):
    # A Detector class to serve as a template for child classes through abstraction
    # Not implemented here, each detector will have it's own file
    def __init__(self, tag_id: str) -> None:
        self.tag_id = tag_id  # Tracking ID used when initializing a new detector
        self._reading_count = 0

    # Required functions within the created detectors
    @abstractmethod
    def update(self, reading: TagReading) -> AlarmEvent | None: ...

    @abstractmethod
    def reset(self) -> None: ...

    @property
    def ready(self) -> bool:
        return True
