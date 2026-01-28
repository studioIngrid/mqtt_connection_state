"""Service handlers for MQTT connection state custom integration."""

from __future__ import annotations

import json
import logging

from homeassistant.core import (
    HomeAssistant,
    ServiceCall,
    ServiceResponse,
    SupportsResponse,
    callback,
)

from .const import DOMAIN, SERV_LIST_NEW_DEVICES

_LOGGER = logging.getLogger(__name__)


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


async def _async_list_new_devices(call: ServiceCall) -> ServiceResponse:
    """List new devices."""

    _LOGGER.debug("Run list devices action")
    return {"new_devices": json.dumps(call.hass.data[DOMAIN]["new_devices"], indent=2)}
