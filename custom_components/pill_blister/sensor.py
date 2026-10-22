"""Sensors."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.util import dt as dt_util

from . import PillBlisterConfigEntry
from .const import STATUSES
from .entity import PillEntity

# Shown in the UI and used by the card, but not worth a recorder row on every change.
_BIG = frozenset({"days", "notices", "events", "missing", "pending", "event_types"})


def _ts(value: str | None) -> datetime | None:
    return dt_util.parse_datetime(value) if value else None


async def async_setup_entry(
    hass: HomeAssistant,
    entry: PillBlisterConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    c = entry.runtime_data
    async_add_entities(
        [
            StatusSensor(c),
            PillNumberSensor(c),
            MissingSensor(c),
            LastTakenSensor(c),
            NoticeUntilSensor(c),
            PendingSensor(c),
        ]
    )


class StatusSensor(PillEntity, SensorEntity):
    """Everything the card needs, as one entity."""

    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = STATUSES
    _unrecorded_attributes = _BIG

    def __init__(self, controller) -> None:
        super().__init__(controller, "sensor", "status")

    @property
    def native_value(self) -> str | None:
        return self.snap.get("status")

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        c = self.controller
        attrs = {k: v for k, v in self.snap.items() if k != "status"}
        attrs["config_entry_id"] = c.entry.entry_id
        attrs["person"] = c.person
        attrs["window_before_min"] = round(c.params.window_before.total_seconds() / 60)
        attrs["window_after_min"] = round(c.params.window_after.total_seconds() / 60)
        attrs["on_time_min"] = round(c.params.on_time.total_seconds() / 60)
        attrs["missed_after_min"] = round(c.params.missed_after.total_seconds() / 60)
        attrs["event_types"] = [
            {"key": r.key, "name": r.name, "replacement_hours": r.replacement_hours}
            for r in c.params.illnesses
        ]
        return attrs


class PillNumberSensor(PillEntity, SensorEntity):
    def __init__(self, controller) -> None:
        super().__init__(controller, "sensor", "pill_number")

    @property
    def native_value(self) -> int | None:
        return self.snap.get("pill_number")

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {"cycle_day": self.snap.get("cycle_day"), "cycle_on": self.snap.get("cycle_on")}


class MissingSensor(PillEntity, SensorEntity):
    _unrecorded_attributes = _BIG

    def __init__(self, controller) -> None:
        super().__init__(controller, "sensor", "missing_entries")

    @property
    def native_value(self) -> int:
        return len(self.snap.get("missing") or [])

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {"missing": self.snap.get("missing") or []}


class LastTakenSensor(PillEntity, SensorEntity):
    _attr_device_class = SensorDeviceClass.TIMESTAMP

    def __init__(self, controller) -> None:
        super().__init__(controller, "sensor", "last_taken")

    @property
    def native_value(self) -> datetime | None:
        entry = self.controller.engine.last_taken() if self.controller.engine else None
        return entry.time if entry else None


class NoticeUntilSensor(PillEntity, SensorEntity):
    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _unrecorded_attributes = _BIG

    def __init__(self, controller) -> None:
        super().__init__(controller, "sensor", "notice_until")

    @property
    def native_value(self) -> datetime | None:
        return _ts(self.snap.get("notice_until"))

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {"notices": self.snap.get("notices") or []}


class PendingSensor(PillEntity, SensorEntity):
    """Time of an intake that still has to be assigned to a day."""

    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _unrecorded_attributes = _BIG

    def __init__(self, controller) -> None:
        super().__init__(controller, "sensor", "pending_intake")

    @property
    def native_value(self) -> datetime | None:
        pending = self.snap.get("pending")
        return _ts(pending["time"]) if pending else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {"pending": self.snap.get("pending")}
