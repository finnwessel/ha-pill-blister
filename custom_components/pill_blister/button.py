"""Button: pill taken now."""

from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import PillBlisterConfigEntry
from .entity import PillEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: PillBlisterConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    async_add_entities([TakenButton(entry.runtime_data)])


class TakenButton(PillEntity, ButtonEntity):
    def __init__(self, controller) -> None:
        super().__init__(controller, "button", "taken")

    async def async_press(self) -> None:
        await self.controller.async_mark_taken(source="button")
