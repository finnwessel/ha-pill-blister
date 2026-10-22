"""Pill Blister: a contraceptive pill blister with cycle, intake window, journal and notices.

One config entry per person. The engine (``engine.py``) holds all rules; this package
wires it to Home Assistant: storage, a one-minute clock, entities, services, events and
the bundled dashboard card.
"""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.typing import ConfigType

from .const import DOMAIN
from .controller import PillController
from .frontend import async_register_card
from .services import async_setup_services

PLATFORMS: list[Platform] = [
    Platform.BINARY_SENSOR,
    Platform.BUTTON,
    Platform.CALENDAR,
    Platform.DATE,
    Platform.SENSOR,
    Platform.TIME,
]

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

type PillBlisterConfigEntry = ConfigEntry[PillController]


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Register services and the dashboard card once."""
    async_setup_services(hass)
    await async_register_card(hass)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: PillBlisterConfigEntry) -> bool:
    controller = PillController(hass, entry)
    await controller.async_start()
    entry.runtime_data = controller
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_reload))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: PillBlisterConfigEntry) -> bool:
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        await entry.runtime_data.async_stop()
    return unloaded


async def _async_reload(hass: HomeAssistant, entry: PillBlisterConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)
