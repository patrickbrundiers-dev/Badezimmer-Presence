"""Sensors for Badezimmer Presence."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import EntityCategory, UnitOfTime
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import BadezimmerConfigEntry
from .engine import PERIODS, PresenceEngine, Status, UsageStats
from .entity import BadezimmerEntity


@dataclass(frozen=True, kw_only=True)
class BadezimmerSensorDescription(SensorEntityDescription):
    """Describes a sensor."""

    value_fn: Callable[[PresenceEngine], Any]
    attrs_fn: Callable[[PresenceEngine], dict[str, Any]] | None = None
    available_fn: Callable[[PresenceEngine], bool] = lambda e: True


def _stats_descriptions(
    kind: str, available_fn: Callable[[PresenceEngine], bool]
) -> tuple[BadezimmerSensorDescription, ...]:
    def stats(engine: PresenceEngine) -> UsageStats:
        return getattr(engine, f"stats_{kind}")

    def start(engine: PresenceEngine):
        running = {
            "usage": engine.occupied_since,
            "shower": engine.shower_since,
            "toilet": engine.toilet_since,
        }[kind]
        return running or stats(engine).last_start

    periods: list[BadezimmerSensorDescription] = []
    for period in PERIODS:
        periods.extend(
            (
                BadezimmerSensorDescription(
                    key=f"{kind}_count_{period}",
                    state_class=SensorStateClass.TOTAL_INCREASING,
                    value_fn=lambda e, p=period: stats(e).period_count(p),
                    available_fn=available_fn,
                ),
                BadezimmerSensorDescription(
                    key=f"{kind}_minutes_{period}",
                    device_class=SensorDeviceClass.DURATION,
                    native_unit_of_measurement=UnitOfTime.MINUTES,
                    state_class=SensorStateClass.TOTAL_INCREASING,
                    suggested_display_precision=1,
                    value_fn=lambda e, p=period: stats(e).period_minutes(p),
                    available_fn=available_fn,
                ),
                BadezimmerSensorDescription(
                    key=f"{kind}_average_{period}",
                    device_class=SensorDeviceClass.DURATION,
                    native_unit_of_measurement=UnitOfTime.MINUTES,
                    state_class=SensorStateClass.MEASUREMENT,
                    suggested_display_precision=1,
                    value_fn=lambda e, p=period: stats(e).period_average(p),
                    available_fn=available_fn,
                ),
            )
        )

    return (
        *periods,
        BadezimmerSensorDescription(
            key=f"{kind}_start",
            device_class=SensorDeviceClass.TIMESTAMP,
            value_fn=start,
            available_fn=available_fn,
        ),
        BadezimmerSensorDescription(
            key=f"{kind}_count",
            state_class=SensorStateClass.TOTAL_INCREASING,
            value_fn=lambda e: stats(e).count,
            available_fn=available_fn,
        ),
        BadezimmerSensorDescription(
            key=f"{kind}_minutes",
            device_class=SensorDeviceClass.DURATION,
            native_unit_of_measurement=UnitOfTime.MINUTES,
            state_class=SensorStateClass.TOTAL_INCREASING,
            suggested_display_precision=1,
            value_fn=lambda e: stats(e).total_minutes,
            available_fn=available_fn,
        ),
        BadezimmerSensorDescription(
            key=f"{kind}_last_duration",
            device_class=SensorDeviceClass.DURATION,
            native_unit_of_measurement=UnitOfTime.MINUTES,
            suggested_display_precision=1,
            value_fn=lambda e: stats(e).last_minutes,
            attrs_fn=lambda e: {
                "start": stats(e).last_start,
                "end": stats(e).last_end,
            },
            available_fn=available_fn,
        ),
        BadezimmerSensorDescription(
            key=f"{kind}_max_duration",
            device_class=SensorDeviceClass.DURATION,
            native_unit_of_measurement=UnitOfTime.MINUTES,
            suggested_display_precision=1,
            value_fn=lambda e: stats(e).max_minutes,
            available_fn=available_fn,
        ),
        BadezimmerSensorDescription(
            key=f"{kind}_average_duration",
            device_class=SensorDeviceClass.DURATION,
            native_unit_of_measurement=UnitOfTime.MINUTES,
            state_class=SensorStateClass.MEASUREMENT,
            suggested_display_precision=1,
            value_fn=lambda e: (
                round(stats(e).total_minutes / stats(e).count, 1) if stats(e).count else None
            ),
            available_fn=available_fn,
        ),
    )


DESCRIPTIONS: tuple[BadezimmerSensorDescription, ...] = (
    BadezimmerSensorDescription(
        key="status",
        device_class=SensorDeviceClass.ENUM,
        options=[s.value for s in Status],
        value_fn=lambda e: e.status.value,
    ),
    BadezimmerSensorDescription(
        key="humidity_rate",
        native_unit_of_measurement="%/min",
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda e: e.humidity_rate,
        available_fn=lambda e: e.config.has_humidity,
    ),
    *_stats_descriptions("usage", lambda e: True),
    *_stats_descriptions("shower", lambda e: e.config.has_humidity),
    *_stats_descriptions("toilet", lambda e: e.config.has_toilet_lid),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: BadezimmerConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up sensors."""
    manager = entry.runtime_data
    async_add_entities(
        BadezimmerSensor(manager, desc)
        for desc in DESCRIPTIONS
        if desc.available_fn(manager.engine)
    )


class BadezimmerSensor(BadezimmerEntity, SensorEntity):
    """Sensor backed by the engine."""

    entity_description: BadezimmerSensorDescription

    def __init__(self, manager, description: BadezimmerSensorDescription) -> None:
        """Initialize."""
        super().__init__(manager, description.key)
        self.entity_description = description

    @property
    def native_value(self) -> Any:
        """Return the state."""
        return self.entity_description.value_fn(self.engine)

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Return extra attributes."""
        if self.entity_description.attrs_fn is None:
            return None
        return self.entity_description.attrs_fn(self.engine)
