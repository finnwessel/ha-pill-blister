"""Diagnostics."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from homeassistant.core import HomeAssistant

if TYPE_CHECKING:
    from . import PillBlisterConfigEntry


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: PillBlisterConfigEntry
) -> dict[str, Any]:
    c = entry.runtime_data
    journal = c.engine.j.to_dict() if c.engine else {}
    return {
        "options": dict(entry.options),
        "journal": {
            **journal,
            "entries": len(journal.get("entries", [])),
            "events": len(journal.get("events", [])),
        },
        "snapshot": {k: v for k, v in c.snapshot.items() if k not in ("days",)},
    }
