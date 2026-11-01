"""Base entity for Badezimmer Presence."""

from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity import Entity

from .const import DOMAIN
from .manager import PresenceManager


class BadezimmerEntity(Entity):
    """Entity bound to one bathroom (config entry)."""

    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, manager: PresenceManager, key: str) -> None:
        """Initialize."""
        self.manager = manager
        self.entity_description_key = key
        self._attr_unique_id = f"{manager.entry.entry_id}_{key}"
        self._attr_translation_key = key
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, manager.entry.entry_id)},
            name=manager.entry.title,
            manufacturer="Badezimmer Presence",
            model="Virtuelle Präsenzerkennung",
            entry_type=DeviceEntryType.SERVICE,
        )

    @property
    def engine(self):
        """Shortcut to the engine."""
        return self.manager.engine

    async def async_added_to_hass(self) -> None:
        """Subscribe to manager updates."""
        self.async_on_remove(
            async_dispatcher_connect(self.hass, self.manager.signal, self.async_write_ha_state)
        )
