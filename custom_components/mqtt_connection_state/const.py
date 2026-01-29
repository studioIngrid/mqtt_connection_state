"""Constants for MQTT connection state custom integration."""

from datetime import timedelta
import json
from logging import Logger, getLogger
from pathlib import Path

LOGGER: Logger = getLogger(__name__)

manifestfile = Path(__file__).parent / "manifest.json"
with Path(manifestfile).open(encoding="UTF-8") as json_file:
    manifest_data = json.load(json_file)

DOMAIN = manifest_data.get("domain")
DOMAIN_NAME = manifest_data.get("name")
VERSION = manifest_data.get("version")

DOMAIN_NAME = "MQTT connection state"

CONF_DEVICE_ID = "device_id"
CONF_DISCOVERY_INTERVAL = timedelta(minutes=10)
CONF_ERROR_BASE = "base"
CONF_TOPIC = "topic"

SERV_LIST_NEW_DEVICES = "list_new_devices"
SERV_ADD_NEW_DEVICES = "add_new_devices"
