"""Binary sensors for Badezimmer Presence."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import BadezimmerConfigEntry
from .engine import PresenceEngine
from .entity import BadezimmerEntity


@dataclass(frozen=True, kw_only=True)
class BadezimmerBinarySensorDescription(BinarySensorEntityDescription):
    """Describes a binary sensor."""

    is_on_fn: Callable[[PresenceEngine], bool]
    attrs_fn: Callable[[PresenceEngine], dict[str, Any]] | None = None
    available_fn: Callable[[PresenceEngine], bool] = lambda e: True


def _occupied_attrs(engine: PresenceEngine) -> dict[str, Any]:
    return {
        "occupied_since": engine.occupied_since,
        "occupy_reason": engine.occupy_reason,
        "last_release_reason": engine.release_reason,
        "entry_window_active": engine.entry_window_active,
    }


DESCRIPTIONS: tuple[BadezimmerBinarySensorDescription, ...] = (
    BadezimmerBinarySensorDescription(
        key="occupied",
        device_class=BinarySensorDeviceClass.OCCUPANCY,
        is_on_fn=lambda e: e.occupied,
        attrs_fn=_occupied_attrs,
    ),
    BadezimmerBinarySensorDescription(
        key="shower",
        device_class=BinarySensorDeviceClass.RUNNING,
        is_on_fn=lambda e: e.shower,
        attrs_fn=lambda e: {"shower_since": e.shower_since},
        available_fn=lambda e: e.config.has_humidity,
    ),
    BadezimmerBinarySensorDescription(
        key="usage_detected",
        is_on_fn=lambda e: e.usage_detected,
    ),
    BadezimmerBinarySensorDescription(
        key="entry_window",
        is_on_fn=lambda e: e.entry_window_active,
        entity_category=EntityCategory.DIAGNOSTIC,
        attrs_fn=lambda e: {"until": e.entry_window_until},
    ),
    BadezimmerBinarySensorDescription(
        key="toilet_lid_open_too_long",
        device_class=BinarySensorDeviceClass.PROBLEM,
        is_on_fn=lambda e: e.toilet_lid_alert_active,
        available_fn=lambda e: e.config.has_toilet_lid,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: BadezimmerConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up binary sensors."""
    manager = entry.runtime_data
    async_add_entities(
        BadezimmerBinarySensor(manager, desc)
        for desc in DESCRIPTIONS
        if desc.available_fn(manager.engine)
    )


class BadezimmerBinarySensor(BadezimmerEntity, BinarySensorEntity):
    """Binary sensor backed by the engine."""

    entity_description: BadezimmerBinarySensorDescription

    def __init__(self, manager, description: BadezimmerBinarySensorDescription) -> None:
        """Initialize."""
        super().__init__(manager, description.key)
        self.entity_description = description

    @property
    def is_on(self) -> bool:
        """Return the state."""
        return self.entity_description.is_on_fn(self.engine)

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Return extra attributes."""
        if self.entity_description.attrs_fn is None:
            return None
        return self.entity_description.attrs_fn(self.engine)
