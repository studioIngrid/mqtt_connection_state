"""Binary sensor platform for MQTT connection state custom integration."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
import json
import logging
from typing import Any

from homeassistant.components.binary_sensor import (
    DOMAIN as BINARY_SENSOR_DOMAIN,
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.components.mqtt import async_subscribe, models
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.entity import DeviceInfo, async_generate_entity_id
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.event import async_track_device_registry_updated_event

from .const import CONF_DEVICE_ID, CONF_TOPIC
from .helpers import find_connection_topic

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Initialize from the config entry."""
    # _LOGGER.info("Initialize binary_sensor: %s", entry.title)
    async_add_entities([MqttConnectionSensorEntity(hass, entry)])


class MqttConnectionSensorEntity(BinarySensorEntity):
    """Binary Sensor Entity."""

    _attr_should_poll = False
    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_has_entity_name = True
    _attr_translation_key = "connection_state"

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize Sensor."""
        _LOGGER.debug("Setup Binary Sensor: %s", entry.title)

        self.hass = hass
        self.entry = entry
        self.entity_id = async_generate_entity_id(
            BINARY_SENSOR_DOMAIN + ".{}_connection_state", entry.title, hass=hass
        )

        device_id = entry.data[CONF_DEVICE_ID]
        self._device_id = device_id

        device_registry = dr.async_get(hass)
        device_entry = device_registry.async_get(device_id)

        self._attr_device_info = DeviceInfo(
            identifiers=device_entry.identifiers if device_entry else None,
        )

        self._attr_unique_id = f"{entry.entry_id}_connection_state"
        self._attr_is_on = False
        self._attr_available = True
        self._connection_topic: str | None = entry.data.get(CONF_TOPIC)

        self._unsubscribe = None
        self._unsub_device = None
        self._unsub_bridge = None
        self._message_received = None
        self._last_mqtt_message: datetime | None = None

    async def async_added_to_hass(self) -> None:
        """Run when this Entity has been added to HA."""
        device_registry = dr.async_get(self.hass)

        async def _async_delayed_resolve() -> None:
            await asyncio.sleep(1)

            new_topic = find_connection_topic(self.hass, self._device_id, log=False)

            if new_topic and new_topic != self._connection_topic:
                _LOGGER.info(
                    "Connection topic updated via registry: %s -> %s",
                    self._connection_topic,
                    new_topic,
                )

                if self._unsubscribe:
                    self._unsubscribe()
                    self._unsubscribe = None

                self._connection_topic = new_topic
                self.hass.config_entries.async_update_entry(
                    self.entry,
                    data={**self.entry.data, CONF_TOPIC: new_topic},
                )

                self._unsubscribe = await async_subscribe(
                    self.hass,
                    new_topic,
                    self._message_received,
                )

        @callback
        def _on_device_registry_updated(event: Event) -> None:
            if event.data.get("action") == "remove":
                return

            if event.data.get("device_id") != self._device_id:
                return

            new_device_entry = device_registry.async_get(self._device_id)
            if (
                new_device_entry.primary_config_entry if new_device_entry else None
            ) is None:
                return

            _LOGGER.debug(
                "Registry updated, check topic of %s",
                self.device_entry.name,
            )
            self.hass.async_create_task(_async_delayed_resolve())

        async def _on_bridge_state(message: models.ReceiveMessage) -> None:
            try:
                payload = json.loads(message.payload)
            except ValueError:
                return

            if payload["state"] == "online":
                # if a message has been received in the last minute before bride online state don't recheck.
                now = datetime.now(UTC)
                if (
                    self._last_mqtt_message
                    and now - self._last_mqtt_message < timedelta(minutes=1)
                ):
                    return
                # if a massage has been receive in the first minute after bride online state don't recheck.
                await asyncio.sleep(59)
                now2 = datetime.now(UTC)
                if (
                    self._last_mqtt_message
                    and now2 - self._last_mqtt_message < timedelta(minutes=1)
                ):
                    return

                _LOGGER.debug(
                    "Bridge online on %s, check topic of %s",
                    message.topic,
                    self.device_entry.name,
                )
                self.hass.async_create_task(_async_delayed_resolve())

        @callback
        def message_received(message: models.ReceiveMessage) -> None:
            """Receive a MQTT message."""
            self._last_mqtt_message = datetime.now(UTC)

            _LOGGER.debug(
                "Message received on %s: %s",
                message.topic,
                message.payload,
            )

            if not message.payload:
                self._handle_message_updates(None)
                return

            try:
                payload = json.loads(message.payload)
            except ValueError:
                _LOGGER.warning(
                    "Invalid JSON payload on %s: %s",
                    message.topic,
                    message.payload,
                )
                return

            self._handle_message_updates(payload)

        self._message_received = message_received

        _LOGGER.debug(
            "Subscribed to topic %s",
            self._connection_topic,
        )

        self._unsubscribe = await async_subscribe(
            self.hass,
            self._connection_topic,
            message_received,
        )
        self._unsub_device = async_track_device_registry_updated_event(
            self.hass,
            [self._device_id],
            _on_device_registry_updated,
        )

        base = self._connection_topic.split("/", 1)[0]
        self._unsub_bridge = await async_subscribe(
            self.hass,
            f"{base}/bridge/state",
            _on_bridge_state,
        )

    async def async_will_remove_from_hass(self) -> None:
        """When removing unsubscribe all."""

        if self._unsubscribe:
            self._unsubscribe()
            self._unsubscribe = None

        if self._unsub_device:
            self._unsub_device()
            self._unsub_device = None

        if self._unsub_bridge:
            self._unsub_bridge()
            self._unsub_bridge = None

    def _handle_message_updates(self, data: dict[str, Any] | None) -> None:
        old_state = self._attr_is_on
        old_available = self._attr_available

        if not data:
            self._attr_available = False
            if old_available:
                self.async_write_ha_state()
            return

        self._attr_is_on = data.get("state") == "online"
        self._attr_available = True

        if old_state != self._attr_is_on or not old_available:
            self.async_write_ha_state()

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return the state attributes of the sensor."""
        return {
            "topic": self._connection_topic,
        }
