"""Serve the bundled dashboard card and register it as a Lovelace resource."""

from __future__ import annotations

import json
import logging
from pathlib import Path

from homeassistant.components.http import StaticPathConfig
from homeassistant.core import HomeAssistant

from .const import CARD_URL

_LOGGER = logging.getLogger(__name__)
_DIR = Path(__file__).parent


def _version() -> str:
    return json.loads((_DIR / "manifest.json").read_text())["version"]


async def async_register_card(hass: HomeAssistant) -> None:
    if hass.http is None:  # e.g. in some test setups
        return
    path = _DIR / "frontend" / "pill-blister-card.js"
    await hass.http.async_register_static_paths([StaticPathConfig(CARD_URL, str(path), False)])
    version = await hass.async_add_executor_job(_version)
    url = f"{CARD_URL}?v={version}"

    lovelace = hass.data.get("lovelace")
    resources = getattr(lovelace, "resources", None)
    if resources is None or not hasattr(resources, "async_create_item"):
        _LOGGER.info("Dashboards in YAML mode: add %s as a module resource yourself", url)
        return
    try:
        if not getattr(resources, "loaded", True):
            await resources.async_load()
            resources.loaded = True
        existing = [
            r for r in resources.async_items() if str(r.get("url", "")).split("?")[0] == CARD_URL
        ]
        if not existing:
            await resources.async_create_item({"res_type": "module", "url": url})
        elif existing[0]["url"] != url:
            await resources.async_update_item(existing[0]["id"], {"res_type": "module", "url": url})
    except Exception:  # noqa: BLE001 - a missing resource must never block the integration
        _LOGGER.warning(
            "Could not register the dashboard card; add %s as a module resource", url, exc_info=True
        )
