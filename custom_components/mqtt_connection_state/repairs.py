"""Repairs for MQTT connection state custom integration."""

from __future__ import annotations

from homeassistant import data_entry_flow
from homeassistant.components.repairs import ConfirmRepairFlow, RepairsFlow
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant


class OrphanedDeviceRepairFlow(RepairsFlow):
    """Repair flow for orphaned device connection sensor."""

    def __init__(self, entry: ConfigEntry) -> None:
        """Create flow."""
        # self.entry = entry
        # super().__init__()

    async def async_step_init(self, user_input=None) -> data_entry_flow.FlowResult:
        """Repair flow for orphaned device connection sensor."""
        return await self.async_step_confirm()

    async def async_step_confirm(self, user_input=None) -> data_entry_flow.FlowResult:
        """Repair flow for orphaned device connection sensor."""
        if user_input is not None:
            # On confirm, remove the config entry
            entry_id = self.issue_id.removeprefix("orphaned_")
            entry = self.hass.config_entries.async_get_entry(entry_id)
            if entry:
                await self.hass.config_entries.async_remove(entry.entry_id)
            return self.async_create_entry(title="", data={})

        return self.async_show_form(step_id="confirm")


async def async_create_fix_flow(
    hass: HomeAssistant,
    issue_id: str,
    data: dict[str, str],
) -> RepairsFlow:
    """Create flow."""
    if issue_id.startswith("orphaned_"):
        return OrphanedDeviceRepairFlow(data)
    return ConfirmRepairFlow()
