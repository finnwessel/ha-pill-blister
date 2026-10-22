"""Base entity."""

from __future__ import annotations

from homeassistant.core import callback
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity import Entity
from homeassistant.util import slugify

from .const import DOMAIN
from .controller import PillController


class PillEntity(Entity):
    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, controller: PillController, platform: str, key: str) -> None:
        self.controller = controller
        device_name = f"{controller.name} Pill"
        self._attr_translation_key = key
        self._attr_unique_id = f"{controller.entry.entry_id}_{key}"
        # English entity IDs regardless of the UI language.
        self.entity_id = f"{platform}.{slugify(device_name)}_{key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, controller.entry.entry_id)},
            name=device_name,
            manufacturer="Pill Blister",
            model="Blister",
            entry_type=DeviceEntryType.SERVICE,
        )

    @property
    def snap(self) -> dict:
        return self.controller.snapshot

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(self.controller.async_add_listener(self._handle_update))

    @callback
    def _handle_update(self) -> None:
        self.async_write_ha_state()
