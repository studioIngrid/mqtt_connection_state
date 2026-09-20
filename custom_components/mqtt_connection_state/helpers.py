"""Helpers for MQTT connection state custom integration."""

from __future__ import annotations

from collections import Counter
import json
import logging
from typing import Any

from homeassistant.components.mqtt import debug_info
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import device_registry as dr, issue_registry as ir

from .const import CONF_DEVICE_ID, CONF_TOPIC, DOMAIN, ISSUE_DUPLICATE_ENTRIES

_LOGGER = logging.getLogger(__name__)


def _is_own_or_unknown_entry(hass: HomeAssistant, config_entry_id: str | None) -> bool:
    """Return True if the config entry is this integration's own, or unknown."""
    if not config_entry_id:
        return True
    entry = hass.config_entries.async_get_entry(config_entry_id)
    return entry is None or entry.domain == DOMAIN


def resolve_source_device_id(
    hass: HomeAssistant,
    device_id: str | None,
) -> str | None:
    """Resolve a stored device reference to the real MQTT device it should link to.

    Config entries created before Home Assistant 2026.8 stored the id of the
    device as it existed while Home Assistant still merged devices from several
    integrations into one. The 2026.8 device-registry migration split every such
    device into one device per config entry, so the stored id can now point at a
    read-only "composite" id (no concrete device) or at this integration's own
    split. Re-resolve it to the concrete device that carries the same hardware
    identity and is owned by another integration (normally ``mqtt``).

    Returns ``None`` when no such device exists.
    """
    if not device_id:
        return None

    device_registry = dr.async_get(hass)

    composite_id: str | None = None
    device = device_registry.async_get(
        device_id, include_child_devices=False, include_composite_devices=False
    )
    if device is not None:
        if not _is_own_or_unknown_entry(hass, device.primary_config_entry):
            return device_id
        composite_id = device.composite_device_id
    else:
        # Not a concrete device: this is a pre-2026.8 merged-device id.
        composite_id = device_id

    if composite_id is not None:
        for split in device_registry.async_get_devices_for_composite_device_id(
            composite_id
        ):
            if not _is_own_or_unknown_entry(hass, split.primary_config_entry):
                return split.id

    # Last resort: match hardware identity against a concrete device.
    reference = device_registry.async_get(device_id, include_child_devices=False)
    if reference is not None:
        for candidate in device_registry.async_get_devices(
            identifiers=reference.identifiers, connections=reference.connections
        ):
            if not _is_own_or_unknown_entry(hass, candidate.primary_config_entry):
                return candidate.id

    return None


def entry_source_key(hass: HomeAssistant, entry: ConfigEntry) -> str | None:
    """Return the identity key of the device a config entry tracks.

    Uses the resolved concrete device id when available so entries created for
    the same physical device before and after the Home Assistant 2026.8
    device-registry migration collapse onto the same key.
    """
    stored = entry.data.get(CONF_DEVICE_ID)
    return resolve_source_device_id(hass, stored) or stored


def configured_source_device_ids(hass: HomeAssistant) -> set[str]:
    """Return the identity keys of every device already configured here."""
    return {
        key
        for entry in hass.config_entries.async_entries(DOMAIN)
        if (key := entry_source_key(hass, entry))
    }


def find_duplicate_entries(
    hass: HomeAssistant,
) -> tuple[list[ConfigEntry], list[ConfigEntry]]:
    """Group this integration's config entries by the device they track.

    Returns ``(keep, remove)``: for every device with more than one entry the
    oldest entry is kept and the rest are returned for removal. Entries whose
    device cannot be identified are never proposed for removal.
    """
    groups: dict[str, list[ConfigEntry]] = {}
    for entry in hass.config_entries.async_entries(DOMAIN):
        key = entry_source_key(hass, entry)
        if not key:
            continue
        groups.setdefault(key, []).append(entry)

    keep: list[ConfigEntry] = []
    remove: list[ConfigEntry] = []
    for entries in groups.values():
        if len(entries) < 2:
            continue
        entries.sort(key=lambda candidate: candidate.created_at)
        keep.append(entries[0])
        remove.extend(entries[1:])
    return keep, remove


@callback
def async_sync_duplicate_issue(hass: HomeAssistant) -> int:
    """Create or clear the duplicate-entries repair issue. Returns the count."""
    _keep, remove = find_duplicate_entries(hass)
    if remove:
        ir.async_create_issue(
            hass,
            DOMAIN,
            ISSUE_DUPLICATE_ENTRIES,
            is_fixable=True,
            severity=ir.IssueSeverity.WARNING,
            translation_key=ISSUE_DUPLICATE_ENTRIES,
            translation_placeholders={"count": str(len(remove))},
        )
    else:
        ir.async_delete_issue(hass, DOMAIN, ISSUE_DUPLICATE_ENTRIES)
    return len(remove)


async def async_remove_duplicate_entries(
    hass: HomeAssistant,
) -> tuple[list[ConfigEntry], list[ConfigEntry]]:
    """Remove the duplicate config entries, keeping the oldest of each device.

    Returns ``(removed, failed)`` and refreshes the repair issue.
    """
    _keep, remove = find_duplicate_entries(hass)

    removed: list[ConfigEntry] = []
    failed: list[ConfigEntry] = []
    for entry in remove:
        try:
            await hass.config_entries.async_remove(entry.entry_id)
        except Exception:  # noqa: BLE001
            _LOGGER.exception("Failed to remove duplicate entry %s", entry.entry_id)
            failed.append(entry)
        else:
            removed.append(entry)

    if removed or failed:
        _LOGGER.warning(
            "Removed %d duplicate config entries (%d failed)",
            len(removed),
            len(failed),
        )
    async_sync_duplicate_issue(hass)
    return removed, failed


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


def process_message_payload(
    hass: HomeAssistant,
    topic: str,
    payload: Any,
) -> str | None:
    """Process unsafe payload."""

    if isinstance(payload, (bytes, bytearray)):
        payload_raw = payload.decode("utf-8", errors="ignore").strip()
    elif isinstance(payload, (str, int, float, bool)):
        payload_raw = str(payload).strip()
    else:
        _LOGGER.error(
            "Message received on %s: %s, ERROR unsupported payload type: %s",
            topic,
            payload,
            type(payload),
        )
        return None

    if payload_raw.startswith(("{", "[")):
        try:
            json_payload = json.loads(payload_raw)
        except ValueError:
            _LOGGER.error(
                "Message recieved on %s: %s, ERRROR Invalid JSON",
                topic,
                payload_raw,
            )
            return None

        if json_payload.get("state") is not None:
            message = json_payload.get("state")
        elif json_payload.get("status") is not None:
            message = json_payload.get("status")
        elif json_payload.get("availability") is not None:
            message = json_payload.get("availability")
    else:
        message = payload_raw

    if str(message).strip().lower() in ("online", "on", "true", "1"):
        return "online"
    return "offline"
