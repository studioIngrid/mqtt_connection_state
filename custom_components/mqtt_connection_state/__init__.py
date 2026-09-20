"""MQTT connection state custom integration."""

from __future__ import annotations

import json
import logging

import voluptuous as vol

from homeassistant.components.mqtt import (
    async_subscribe,
    async_wait_for_mqtt_client,
    models,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import (
    Event,
    EventStateChangedData,
    HomeAssistant,
    ServiceCall,
    ServiceResponse,
    SupportsResponse,
    callback,
)
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.event import (
    async_track_device_registry_updated_event,
    async_track_time_interval,
)
from homeassistant.helpers.helper_integration import async_remove_helper_devices
from homeassistant.helpers.service import async_register_admin_service
from homeassistant.helpers.start import async_at_started
from homeassistant.helpers.typing import ConfigType

from .const import (
    CONF_DEVICE_ID,
    CONF_DISCOVERY_INTERVAL,
    CONF_TOPIC,
    DOMAIN,
    SERV_ADD_NEW_DEVICES,
)
from .discovery import async_discover_devices, async_trigger_discovery
from .helpers import async_sync_duplicate_issue, resolve_source_device_id
from .services import async_setup_services

_LOGGER = logging.getLogger(__name__)

SCHEMA_NEW_CONFIG_ENTRY = vol.Schema({vol.Required("list"): str})


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Set up discovery once."""

    hass.data.setdefault(DOMAIN, {})

    if hass.data[DOMAIN].get("_initialized"):  # already setup
        return True
    hass.data[DOMAIN]["_initialized"] = True

    if "new_devices" not in hass.data[DOMAIN]:
        hass.data[DOMAIN]["new_devices"] = []
    if "seen_device_ids" not in hass.data[DOMAIN]:
        hass.data[DOMAIN]["seen_device_ids"] = set()

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

    # Register custom services in services.py
    async_setup_services(hass)

    async def async_handle_add_config_entry(call: ServiceCall) -> ServiceResponse:
        """Service handler for adding a config entry."""

        _LOGGER.debug("Run add devices action")
        try:
            payload = json.loads(call.data.get("list"))

        except ValueError as Err:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="Invalid JSON string",
                translation_placeholders={},
            ) from Err

        # when flow is completed, call.hass.config_entries.flow._progress is changed, first collect the id's then execute

        ids: set[str] = {item["id"] for item in payload if "id" in item}

        domain_entries = call.hass.config_entries.async_entries(DOMAIN)
        configured_device_ids: set[str] = {
            entry.data["device_id"]
            for entry in domain_entries
            if "device_id" in entry.data
        }
        configured_ids = ids & configured_device_ids

        to_configure: list[dict] = []
        for flow in list(call.hass.config_entries.flow._progress.values()): # noqa: SLF001
            if flow.handler is not DOMAIN:
                continue

            device_id = flow.init_data.get("device_id")
            if device_id in (ids - configured_device_ids):
                to_configure.append(
                    {
                        "flow_id": flow.flow_id,
                        "user_input": flow.init_data,
                    }
                )

        created: set[str] = set()
        failed: set[str] = set()

        for flow in to_configure:
            result = await call.hass.config_entries.flow._async_configure(  # noqa: SLF001
                flow["flow_id"],
                flow["user_input"],
            )
            device_id = flow["user_input"].get("device_id")

            if result["type"] == FlowResultType.CREATE_ENTRY:
                created.add(device_id)
            else:
                failed.add(device_id)

        return {
            "response": {
                "devices_requested": len(ids),
                "devices_already_configured": len(configured_ids),
                "devices_to_configure": len(to_configure),
                "devices_configure_success": len(created),
                "devices_configure_fail": len(failed),
                "device_ids": {"success": created, "failed": failed},
            }
        }

    _LOGGER.debug("Setup admin services")
    async_register_admin_service(
        hass,
        DOMAIN,
        SERV_ADD_NEW_DEVICES,
        async_handle_add_config_entry,
        schema=SCHEMA_NEW_CONFIG_ENTRY,
        supports_response=SupportsResponse.OPTIONAL,
    )

    @callback
    def _report_state(_hass: HomeAssistant) -> None:
        """Summarise migration state once everything has loaded."""
        healed = hass.data[DOMAIN].get("healed", 0)
        if healed:
            _LOGGER.info(
                "Healed %d stale device reference(s) from before the Home Assistant "
                "2026.8 device-registry migration",
                healed,
            )
        count = async_sync_duplicate_issue(hass)
        if count:
            _LOGGER.info(
                "%d duplicate config entries can be removed - see Settings > Repairs",
                count,
            )

    async_at_started(hass, _report_state)

    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up a config entry."""

    _LOGGER.debug(
        "Setup entry: %s, listening to topic: %s",
        entry.title,
        entry.data.get(CONF_TOPIC),
    )
    hass.data.setdefault(DOMAIN, {})
    device_id = entry.data.get(CONF_DEVICE_ID)

    # The stored device id may be a pre-2026.8 merged-device id that the 2026.8
    # device-registry migration turned into a non-concrete "composite". Resolve
    # it to the current concrete MQTT device and heal the entry, so discovery
    # stops treating this device as unconfigured and offering it again.
    resolved_device_id = resolve_source_device_id(hass, device_id)
    if resolved_device_id and resolved_device_id != device_id:
        _LOGGER.debug("Heal device reference: %s -> %s", device_id, resolved_device_id)
        hass.data[DOMAIN]["healed"] = hass.data[DOMAIN].get("healed", 0) + 1
        updates: dict = {"data": {**entry.data, CONF_DEVICE_ID: resolved_device_id}}
        # Also move the unique id, unless another entry already claims it (a
        # duplicate entry the cleanup action will remove).
        others = {
            other.unique_id
            for other in hass.config_entries.async_entries(DOMAIN)
            if other.entry_id != entry.entry_id
        }
        if entry.unique_id != resolved_device_id and resolved_device_id not in others:
            updates["unique_id"] = resolved_device_id
        hass.config_entries.async_update_entry(entry, **updates)
        device_id = resolved_device_id

    # Home Assistant 2026.8 restricts a device to a single config entry. Earlier
    # versions merged this helper's binary sensor onto the source MQTT device via
    # shared identifiers; that merge now produces a separate duplicate device
    # owned by this config entry. Remove it and relink our entity (including one
    # left detached by an earlier attempt) to the real device. Idempotent.
    async_remove_helper_devices(
        hass,
        helper_config_entry_id=entry.entry_id,
        source_device_id=device_id,
        remove_all_devices=True,
    )

    device_registry = dr.async_get(hass)
    tracked_device_id = device_id

    def _update_entry_title() -> None:
        new_device_entry = device_registry.async_get(tracked_device_id)
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

    @callback
    def _async_device_registry_updated(event: Event[EventStateChangedData]) -> None:
        if event.data.get("action") == "update":
            changes = event.data.get("changes", {})
            if "name" in changes or "name_by_user" in changes:
                _update_entry_title()

    _update_entry_title()

    unsub = async_track_device_registry_updated_event(
        hass, [tracked_device_id], _async_device_registry_updated
    )
    entry.async_on_unload(unsub)

    await hass.config_entries.async_forward_entry_setups(
        entry, [Platform.BINARY_SENSOR]
    )

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""

    _LOGGER.debug("Unload entry")
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
