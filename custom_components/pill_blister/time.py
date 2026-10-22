"""Time: planned intake time."""

from __future__ import annotations

from datetime import time

from homeassistant.components.time import TimeEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import PillBlisterConfigEntry
from .entity import PillEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: PillBlisterConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    async_add_entities([DoseTime(entry.runtime_data)])


class DoseTime(PillEntity, TimeEntity):
    def __init__(self, controller) -> None:
        super().__init__(controller, "time", "dose_time")

    @property
    def native_value(self) -> time | None:
        return self.controller.engine.j.dose_time if self.controller.engine else None

    async def async_set_value(self, value: time) -> None:
        await self.controller.async_set_dose_time(value)
