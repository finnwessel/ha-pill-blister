"""Services. Every service targets one config entry (one person)."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Any

import voluptuous as vol
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import (
    HomeAssistant,
    ServiceCall,
    ServiceResponse,
    SupportsResponse,
    callback,
)
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import config_validation as cv
from homeassistant.util import dt as dt_util

from .const import (
    ATTR_CONFIG_ENTRY_ID,
    ATTR_DATE,
    ATTR_DATETIME,
    ATTR_DISCARD,
    ATTR_EVENT_ID,
    ATTR_SOURCE,
    ATTR_TIME,
    ATTR_TIME_UNKNOWN,
    ATTR_TYPE,
    DOMAIN,
    SERVICE_ASSIGN_INTAKE,
    SERVICE_MARK_REPLACEMENT,
    SERVICE_MARK_TAKEN,
    SERVICE_REMOVE_ENTRY,
    SERVICE_REMOVE_EVENT,
    SERVICE_REPORT_EVENT,
    SERVICE_START_BLISTER,
)
from .engine import EngineError

if TYPE_CHECKING:
    from .controller import PillController

BASE = {vol.Required(ATTR_CONFIG_ENTRY_ID): cv.string}

SCHEMAS: dict[str, vol.Schema] = {
    SERVICE_MARK_TAKEN: vol.Schema(
        {
            **BASE,
            vol.Optional(ATTR_DATE): cv.date,
            vol.Optional(ATTR_TIME): cv.time,
            vol.Optional(ATTR_TIME_UNKNOWN, default=False): cv.boolean,
            vol.Optional(ATTR_SOURCE, default="service"): cv.string,
        }
    ),
    SERVICE_REMOVE_ENTRY: vol.Schema({**BASE, vol.Required(ATTR_DATE): cv.date}),
    SERVICE_ASSIGN_INTAKE: vol.Schema(
        {
            **BASE,
            vol.Optional(ATTR_DATE): cv.date,
            vol.Optional(ATTR_DISCARD, default=False): cv.boolean,
        }
    ),
    SERVICE_START_BLISTER: vol.Schema({**BASE, vol.Optional(ATTR_DATE): cv.date}),
    SERVICE_REPORT_EVENT: vol.Schema(
        {**BASE, vol.Required(ATTR_TYPE): cv.string, vol.Optional(ATTR_DATETIME): cv.datetime}
    ),
    SERVICE_REMOVE_EVENT: vol.Schema({**BASE, vol.Required(ATTR_EVENT_ID): cv.string}),
    SERVICE_MARK_REPLACEMENT: vol.Schema({**BASE, vol.Optional(ATTR_DATETIME): cv.datetime}),
}


def _controller(hass: HomeAssistant, entry_id: str) -> PillController:
    entry = hass.config_entries.async_get_entry(entry_id)
    if entry is None or entry.domain != DOMAIN:
        raise ServiceValidationError(translation_domain=DOMAIN, translation_key="entry_not_found")
    if entry.state is not ConfigEntryState.LOADED:
        raise ServiceValidationError(translation_domain=DOMAIN, translation_key="entry_not_loaded")
    return entry.runtime_data


def _local(value):
    if value is None:
        return None
    return (
        dt_util.as_local(value)
        if value.tzinfo
        else value.replace(tzinfo=dt_util.get_default_time_zone())
    )


@callback
def async_setup_services(hass: HomeAssistant) -> None:
    def handler(
        run: Callable[[PillController, dict[str, Any]], Awaitable[Any]],
    ) -> Callable[[ServiceCall], Awaitable[ServiceResponse]]:
        async def handle(call: ServiceCall) -> ServiceResponse:
            controller = _controller(hass, call.data[ATTR_CONFIG_ENTRY_ID])
            try:
                result = await run(controller, dict(call.data))
            except EngineError as err:
                raise ServiceValidationError(
                    translation_domain=DOMAIN,
                    translation_key=err.key,
                    translation_placeholders=err.placeholders,
                ) from err
            return result if call.return_response else None

        return handle

    async def mark_taken(c: PillController, d: dict[str, Any]) -> dict[str, Any]:
        return await c.async_mark_taken(
            day=d.get(ATTR_DATE),
            tod=d.get(ATTR_TIME),
            time_unknown=d[ATTR_TIME_UNKNOWN],
            source=d[ATTR_SOURCE],
        )

    async def remove_entry(c: PillController, d: dict[str, Any]) -> None:
        await c.async_remove_entry(d[ATTR_DATE])

    async def assign_intake(c: PillController, d: dict[str, Any]) -> None:
        if not d[ATTR_DISCARD] and ATTR_DATE not in d:
            raise EngineError("date_or_discard")
        await c.async_assign(None if d[ATTR_DISCARD] else d[ATTR_DATE])

    async def start_blister(c: PillController, d: dict[str, Any]) -> None:
        await c.async_start_blister(d.get(ATTR_DATE) or dt_util.now().date())

    async def report_event(c: PillController, d: dict[str, Any]) -> None:
        await c.async_report_event(d[ATTR_TYPE], _local(d.get(ATTR_DATETIME)))

    async def remove_event(c: PillController, d: dict[str, Any]) -> None:
        await c.async_remove_event(d[ATTR_EVENT_ID])

    async def mark_replacement(c: PillController, d: dict[str, Any]) -> None:
        await c.async_mark_replacement(_local(d.get(ATTR_DATETIME)))

    for name, run, response in (
        (SERVICE_MARK_TAKEN, mark_taken, SupportsResponse.OPTIONAL),
        (SERVICE_REMOVE_ENTRY, remove_entry, SupportsResponse.NONE),
        (SERVICE_ASSIGN_INTAKE, assign_intake, SupportsResponse.NONE),
        (SERVICE_START_BLISTER, start_blister, SupportsResponse.NONE),
        (SERVICE_REPORT_EVENT, report_event, SupportsResponse.NONE),
        (SERVICE_REMOVE_EVENT, remove_event, SupportsResponse.NONE),
        (SERVICE_MARK_REPLACEMENT, mark_replacement, SupportsResponse.NONE),
    ):
        hass.services.async_register(
            DOMAIN, name, handler(run), schema=SCHEMAS[name], supports_response=response
        )
