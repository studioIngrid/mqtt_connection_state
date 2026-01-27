"""Config flow for MQTT connection state custom integration."""

from __future__ import annotations

import voluptuous as vol

from homeassistant.config_entries import SOURCE_USER, ConfigFlow, ConfigFlowResult
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr, selector
from homeassistant.helpers.entity_component import DiscoveryInfoType

from .const import CONF_DEVICE_ID, CONF_ERROR_BASE, CONF_TOPIC, DOMAIN
from .helpers import find_connection_topic


class ConfigFlowConfig(ConfigFlow, domain=DOMAIN):
    """Config flow."""

    VERSION = 1

    def __init__(self) -> None:
        """Initialize."""
        self._discovery_info: dict | None = None

    async def async_step_integration_discovery(
        self,
        discovery_info: DiscoveryInfoType,
    ) -> ConfigFlowResult:
        """Handle integration discovery."""
        self._discovery_info = discovery_info

        # Unique ID to allow ignore
        await self.async_set_unique_id(discovery_info[CONF_DEVICE_ID])
        self._abort_if_unique_id_configured()

        self.context["title_placeholders"] = {
            "name": discovery_info.get("name"),
            "manufacturer": discovery_info.get("manufacturer"),
            "model": discovery_info.get("model"),
        }

        return await self.async_step_from_discovery()

    async def async_step_from_discovery(
        self,
        user_input: dict | None = None,
    ) -> ConfigFlowResult:
        """Handle a flow for a device or discovery."""

        assert self._discovery_info is not None
        device_name = self._discovery_info.get("name")

        if not device_name:
            device_registry = dr.async_get(self.hass)
            device = device_registry.async_get(self._discovery_info.get(CONF_DEVICE_ID))
            device_name = device.name if device else "unknown device"

        if user_input is not None:
            check, errors, connection_topic = await validate_input(
                self.hass, self._discovery_info
            )
            if check:
                return self.async_create_entry(
                    title=device_name,
                    data={
                        **self._discovery_info,
                        CONF_TOPIC: connection_topic,
                    },
                )

            return self.async_show_form(
                step_id="from_discovery",
                errors=errors,
                description_placeholders={
                    "device_name": device_name,
                    "connection_topic": connection_topic or "not found",
                },
            )

        connection_topic = find_connection_topic(
            self.hass, self._discovery_info.get(CONF_DEVICE_ID), log=False
        )
        return self.async_show_form(
            step_id="from_discovery",
            description_placeholders={
                "device_name": device_name,
                "connection_topic": connection_topic or "not found",
            },
        )

    async def async_step_user(
        self,
        user_input: dict | None = None,
    ) -> ConfigFlowResult:
        """Handle a flow initialized by the user."""
        errors: dict[str, str] = {}

        if user_input is not None:
            check, errors, connection_topic = await validate_input(
                self.hass, user_input
            )

            if check:
                device_registry = dr.async_get(self.hass)
                device = device_registry.async_get(user_input.get(CONF_DEVICE_ID))
                name = device.name if device else "unknown device"

                return self.async_create_entry(
                    title=name,
                    data={
                        **user_input,
                        CONF_TOPIC: connection_topic,
                    },
                )

        return self.async_show_form(
            step_id=SOURCE_USER,
            data_schema=get_schema(user_input),
            errors=errors,
        )


def get_schema(user_input: dict | None = None) -> vol.Schema:
    """Return the user step schema."""
    if user_input is None:
        user_input = {}

    return vol.Schema(
        {
            vol.Required(
                CONF_DEVICE_ID,
                default=user_input.get(CONF_DEVICE_ID),
            ): selector.DeviceSelector(
                config=selector.DeviceSelectorConfig(
                    filter=[selector.DeviceFilterSelectorConfig(integration="mqtt")]
                )
            )
        }
    )


async def validate_input(
    hass: HomeAssistant, user_input: dict
) -> tuple[bool, dict[str, str], str | None]:
    """Validate the selected device and resolve connection topic."""

    errors: dict[str, str] = {}
    connection_topic: str | None = None

    device_id = user_input.get(CONF_DEVICE_ID, "")
    device_registry = dr.async_get(hass)

    if not device_registry.async_get(device_id):
        errors[CONF_ERROR_BASE] = "device_unknown"
        return False, errors, None

    connection_topic = find_connection_topic(hass, device_id)

    if not connection_topic:
        errors[CONF_ERROR_BASE] = "no_connection_topic"
        return False, errors, None

    return True, errors, connection_topic
