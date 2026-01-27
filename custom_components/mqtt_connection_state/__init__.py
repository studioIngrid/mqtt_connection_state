"""MQTT connection state custom integration."""

from __future__ import annotations

import json
import logging

from homeassistant.components.mqtt import (
    async_subscribe,
    async_wait_for_mqtt_client,
    models,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import Event, EventStateChangedData, HomeAssistant, callback
from homeassistant.helpers import device_registry as dr, issue_registry as ir
from homeassistant.helpers.event import (
    async_track_device_registry_updated_event,
    async_track_time_interval,
)
from homeassistant.helpers.typing import Any, ConfigType

from .const import CONF_DEVICE_ID, CONF_DISCOVERY_INTERVAL, CONF_TOPIC, DOMAIN
from .discovery import async_discover_devices, async_trigger_discovery

_LOGGER = logging.getLogger(__name__)


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Set up discovery once."""

    if DOMAIN in hass.data:  # already done
        return True
    hass.data[DOMAIN] = {}

    _LOGGER.info("Setup discovery")
    if not await async_wait_for_mqtt_client(hass):
        _LOGGER.error("MQTT integration not available")
        return False

    async def _async_discovery(now=None) -> None:
        async_trigger_discovery(hass, await async_discover_devices(hass))

    @callback
    def _on_bridge_state(message: models.ReceiveMessage) -> None:
        try:
            payload = json.loads(message.payload)
        except ValueError:
            return

        if payload["state"] == "online":
            _LOGGER.debug(
                "Bridge online on %s, running discovery",
                message.topic,
            )
            hass.async_create_task(_async_discovery())

    await async_subscribe(
        hass,
        "+/bridge/state",
        _on_bridge_state,
    )

    async_track_time_interval(
        hass, _async_discovery, CONF_DISCOVERY_INTERVAL, cancel_on_shutdown=True
    )

    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up a config entry."""

    _LOGGER.info(
        "Setup entry: %s, listening to topic: %s",
        entry.title,
        entry.data.get(CONF_TOPIC),
    )
    device_id = entry.data.get(CONF_DEVICE_ID)
    device_registry = dr.async_get(hass)
    device_entry = device_registry.async_get(device_id)

    def _update_entry_title() -> None:
        new_device_entry = device_registry.async_get(device_id)
        if not new_device_entry:
            return
        device_name = (
            new_device_entry.name_by_user
            if new_device_entry.name_by_user is not None
            else new_device_entry.name
        )
        if entry.title != device_name:
            _LOGGER.info("Change entry title: %s ->%s", entry.title, device_name)
            hass.config_entries.async_update_entry(entry, title=device_name)

    def _check_primary_config_entry(old_primary_config: Any | None) -> None:
        new_device_entry = device_registry.async_get(device_id)
        if not new_device_entry:
            return
        new_primary_config = (
            new_device_entry.primary_config_entry if new_device_entry else None
        )

        if old_primary_config is not None and new_primary_config is None:
            _LOGGER.warning("Raise issue orphaned device: %s", entry.title)
            ir.async_create_issue(
                hass,
                DOMAIN,
                issue_id=f"orphaned_{entry.entry_id}",
                is_fixable=True,
                severity=ir.IssueSeverity.ERROR,
                translation_key="orphaned_device",
                translation_placeholders={"name": entry.title},
            )
        elif old_primary_config is None and new_primary_config is not None:
            _LOGGER.info("Resolved issue orphaned device: %s", entry.title)
            ir.async_delete_issue(hass, DOMAIN, f"orphaned_{entry.entry_id}")

    @callback
    def _async_device_registry_updated(event: Event[EventStateChangedData]) -> None:
        if event.data.get("action") == "update":
            changes = event.data.get("changes", {})
            if "name" in changes or "name_by_user" in changes:
                _update_entry_title()
                return

            if "primary_config_entry" in changes:
                _check_primary_config_entry(changes["primary_config_entry"])
                return

    _update_entry_title()
    _check_primary_config_entry(device_entry.primary_config_entry)

    unsub = async_track_device_registry_updated_event(
        hass, [device_id], _async_device_registry_updated
    )
    entry.async_on_unload(unsub)

    await hass.config_entries.async_forward_entry_setups(
        entry, [Platform.BINARY_SENSOR]
    )

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""

    _LOGGER.info("Unload entry")
    await hass.config_entries.async_unload_platforms(entry, [Platform.BINARY_SENSOR])

    unsub_runtime = getattr(entry, "runtime_data", None)
    if unsub_runtime:
        unsub_runtime()

    return True


async def async_reload_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
) -> bool:
    """Reload this config entry."""

    await async_unload_entry(hass, entry)
    await async_setup_entry(hass, entry)

    return True
