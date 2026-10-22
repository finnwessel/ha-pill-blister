"""Binary sensors."""

from __future__ import annotations

from typing import Any

from homeassistant.components.binary_sensor import BinarySensorDeviceClass, BinarySensorEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import PillBlisterConfigEntry
from .entity import PillEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: PillBlisterConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    c = entry.runtime_data
    async_add_entities([DueSensor(c), NoticeSensor(c)])


class DueSensor(PillEntity, BinarySensorEntity):
    """On from the dose time until the pill is recorded (also after midnight inside the window)."""

    def __init__(self, controller) -> None:
        super().__init__(controller, "binary_sensor", "due")

    @property
    def is_on(self) -> bool:
        return self.snap.get("status") in ("due", "overdue")

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        s = self.snap
        return {
            "day": s.get("overdue_day") or s.get("today"),
            "overdue": s.get("status") == "overdue",
            "missed_deadline": s.get("overdue_deadline") or s.get("missed_deadline"),
        }


class NoticeSensor(PillEntity, BinarySensorEntity):
    """On while a notice from the leaflet rules is active (protection may be reduced)."""

    _attr_device_class = BinarySensorDeviceClass.PROBLEM
    _unrecorded_attributes = frozenset({"notices"})

    def __init__(self, controller) -> None:
        super().__init__(controller, "binary_sensor", "notice")

    @property
    def is_on(self) -> bool:
        return bool(self.snap.get("notices"))

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        notices = self.snap.get("notices") or []
        return {
            "until": self.snap.get("notice_until"),
            "reasons": [n["reason"] for n in notices],
            "action_needed": any(n["kind"] == "replacement" for n in notices),
            "notices": notices,
        }
