"""Date: start of the current blister."""

from __future__ import annotations

from datetime import date

from homeassistant.components.date import DateEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import PillBlisterConfigEntry
from .entity import PillEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: PillBlisterConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    async_add_entities([BlisterStartDate(entry.runtime_data)])


class BlisterStartDate(PillEntity, DateEntity):
    """Day pill 1 of the current blister was (or will be) taken; the cycle follows from it."""

    def __init__(self, controller) -> None:
        super().__init__(controller, "date", "blister_start")

    @property
    def native_value(self) -> date | None:
        value = self.snap.get("blister_start")
        return date.fromisoformat(value) if value else None

    async def async_set_value(self, value: date) -> None:
        await self.controller.async_start_blister(value)
