"""Discovery for MQTT connection state custom integration."""

from __future__ import annotations

import logging

from homeassistant.config_entries import SOURCE_INTEGRATION_DISCOVERY
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import device_registry as dr, discovery_flow
from homeassistant.helpers.device_registry import DeviceEntry

from .const import CONF_DEVICE_ID, DOMAIN
from .helpers import find_connection_topic

_LOGGER = logging.getLogger(__name__)


async def async_discover_devices(hass: HomeAssistant) -> list[DeviceEntry]:
    """Discover MQTT devices not yet configured for this integration."""
    _LOGGER.debug("Run discover devices")

    discovered_devices: list[DeviceEntry] = []

    seen_device_ids = hass.data[DOMAIN]["seen_device_ids"]
    new_devices = hass.data[DOMAIN]["new_devices"]

    # Get already configured device IDs for this integration
    domain_entries = hass.config_entries.async_entries(DOMAIN) or []
    known_devices = {
        entry.data.get(CONF_DEVICE_ID)
        for entry in domain_entries
        if entry.data.get(CONF_DEVICE_ID)
    }

    device_registry = dr.async_get(hass)

    for device_entry in device_registry.devices.values():
        # Skip disabled devices
        if device_entry.disabled:
            continue

        # Skip devices already configured for this integration
        if device_entry.id in known_devices:
            continue

        if device_entry.id in seen_device_ids:
            continue

        # Skip devices without identifiers
        if not device_entry.identifiers:
            continue

        # Only consider devices coming from MQTT integration
        if not any(identifier[0] == "mqtt" for identifier in device_entry.identifiers):
            continue

        # skip devices without topic
        connection_topic = find_connection_topic(hass, device_entry.id, log=False)
        if not connection_topic:
            continue

        seen_device_ids.add(device_entry.id)
        new_devices.append({"id": device_entry.id, "name": device_entry.name})
        discovered_devices.append(device_entry)

    _LOGGER.debug(
        "Discovered %d new MQTT devices",
        len(discovered_devices),
    )

    return discovered_devices


@callback
def async_trigger_discovery(
    hass: HomeAssistant,
    discovered_devices: list[DeviceEntry],
) -> None:
    """Trigger config flows for discovered devices."""
    for device_entry in discovered_devices:
        _LOGGER.debug(
            "Start discovery flow for new device: %s",
            device_entry.name,
        )

        discovery_flow.async_create_flow(
            hass,
            DOMAIN,
            context={"source": SOURCE_INTEGRATION_DISCOVERY},
            data={
                "name": device_entry.name,
                "manufacturer": device_entry.manufacturer,
                "model": device_entry.model,
                CONF_DEVICE_ID: device_entry.id,
            },
        )
