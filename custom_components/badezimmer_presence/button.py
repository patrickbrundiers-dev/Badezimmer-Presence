"""Button to release the bathroom manually."""

from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import BadezimmerConfigEntry
from .entity import BadezimmerEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: BadezimmerConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the button."""
    async_add_entities([ReleaseButton(entry.runtime_data, "release")])


class ReleaseButton(BadezimmerEntity, ButtonEntity):
    """Release the bathroom (former manual toggle of the input_boolean)."""

    async def async_press(self) -> None:
        """Handle the press."""
        self.manager.async_release()
