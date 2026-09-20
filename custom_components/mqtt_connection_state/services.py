"""Service handlers for MQTT connection state custom integration."""

from __future__ import annotations

import json
import logging

import voluptuous as vol

from homeassistant.core import (
    HomeAssistant,
    ServiceCall,
    ServiceResponse,
    SupportsResponse,
    callback,
)
from homeassistant.helpers import config_validation as cv

from .const import DOMAIN, SERV_LIST_NEW_DEVICES, SERV_REMOVE_DUPLICATE_ENTRIES
from .helpers import async_remove_duplicate_entries, find_duplicate_entries

_LOGGER = logging.getLogger(__name__)

SCHEMA_REMOVE_DUPLICATE_ENTRIES = vol.Schema(
    {vol.Optional("dry_run", default=True): cv.boolean}
)


@callback
def async_setup_services(hass: HomeAssistant) -> None:
    """Register services for MQTT connection state custom integration."""

    _LOGGER.debug("Register services")

    hass.services.async_register(
        DOMAIN,
        SERV_LIST_NEW_DEVICES,
        _async_list_new_devices,
        supports_response=SupportsResponse.ONLY,
    )

    hass.services.async_register(
        DOMAIN,
        SERV_REMOVE_DUPLICATE_ENTRIES,
        _async_remove_duplicate_entries,
        schema=SCHEMA_REMOVE_DUPLICATE_ENTRIES,
        supports_response=SupportsResponse.OPTIONAL,
    )


async def _async_list_new_devices(call: ServiceCall) -> ServiceResponse:
    """List new devices."""

    _LOGGER.debug("Run list devices action")
    return {"new_devices": json.dumps(call.hass.data[DOMAIN]["new_devices"], indent=2)}


async def _async_remove_duplicate_entries(call: ServiceCall) -> ServiceResponse:
    """Review, and with dry_run=false remove, duplicate config entries.

    Home Assistant 2026.8 changed device ids, which made this integration's
    discovery register a second config entry for devices that were already
    configured. This groups the entries by the device they track, keeps the
    oldest of each group and removes the rest.
    """
    hass = call.hass
    dry_run: bool = call.data["dry_run"]

    keep, remove = find_duplicate_entries(hass)

    def _fmt(entry) -> dict[str, str]:
        return {"entry_id": entry.entry_id, "title": entry.title}

    if dry_run:
        _LOGGER.debug(
            "Dry run: %d duplicate config entries would be removed", len(remove)
        )
        return {
            "dry_run": True,
            "duplicate_count": len(remove),
            "would_remove": [_fmt(entry) for entry in remove],
            "would_keep": [_fmt(entry) for entry in keep],
        }

    removed, failed = await async_remove_duplicate_entries(hass)
    return {
        "dry_run": False,
        "removed_count": len(removed),
        "removed": [_fmt(entry) for entry in removed],
        "failed": [_fmt(entry) for entry in failed],
    }
