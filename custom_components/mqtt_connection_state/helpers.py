"""Helpers for MQTT connection state custom integration."""

from __future__ import annotations

from collections import Counter
import logging

from homeassistant.components.mqtt import debug_info
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import device_registry as dr

from .const import CONF_TOPIC

_LOGGER = logging.getLogger(__name__)


def find_connection_topic(
    hass: HomeAssistant,
    device_id: str,
    *,
    log: bool = True,
) -> str | None:
    """Find the first connection topic for a device via mqtt debug info.

    Set log=False to disable debug/error logging fom this function.
    """
    device_registry = dr.async_get(hass)
    device = device_registry.async_get(device_id)
    device_name = device.name if device else device_id

    try:
        discovery_info = debug_info.info_for_device(hass, device_id)
    except HomeAssistantError as err:
        if log:
            _LOGGER.debug(
                "Failed to fetch debug info for device %s: %s",
                device_name,
                err,
            )
        return None

    entities = discovery_info.get("entities")
    if not isinstance(entities, list):
        return None

    found_topics: list[str] = []

    for entity in entities:
        subscriptions = entity.get("subscriptions")
        if not isinstance(subscriptions, list):
            continue

        for sub in subscriptions:
            topic = sub.get(CONF_TOPIC)
            if isinstance(topic, str) and topic.endswith("/availability"):
                found_topics.append(topic)

        if not found_topics:
            for sub in subscriptions:
                topic = sub.get(CONF_TOPIC)
                if isinstance(topic, str) and topic.endswith("/status"):
                    found_topics.append(topic)

    if found_topics:
        counts = Counter(found_topics)

        if len(counts) > 1:
            if log:
                _LOGGER.error(
                    "Multiple different connection topics found for device %s. "
                    "Using the last one, but this is ambiguous. Details: %s",
                    device_name,
                    dict(counts),
                )
        else:
            only_topic = next(iter(counts))
            if log:
                _LOGGER.debug(
                    "Single connection topic found for device %s: %s (found %d times)",
                    device_name,
                    only_topic,
                    counts[only_topic],
                )

        return found_topics[-1]

    if log:
        _LOGGER.debug(
            "No connection topics found for device %s",
            device_name,
        )
    return None
