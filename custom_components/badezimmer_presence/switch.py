"""Switch to set the bathroom occupied or free by hand."""

from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import BadezimmerConfigEntry
from .entity import BadezimmerEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: BadezimmerConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the switch."""
    async_add_entities([OccupiedSwitch(entry.runtime_data, "occupied_switch")])


class OccupiedSwitch(BadezimmerEntity, SwitchEntity):
    """Replaces the former ``input_boolean`` for manual control.

    The detection keeps running: a manually occupied bathroom is released
    by the normal rules once nobody is present any more.
    """

    @property
    def is_on(self) -> bool:
        """Return True if occupied."""
        return self.engine.occupied

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Set occupied."""
        self.manager.async_occupy()

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Release."""
        self.manager.async_release()
