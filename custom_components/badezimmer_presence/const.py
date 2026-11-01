"""Constants for Badezimmer Presence."""

from __future__ import annotations

from typing import Final

DOMAIN: Final = "badezimmer_presence"

# Config entry data (sensors)
CONF_PRESENCE_SENSOR: Final = "presence_sensor"
CONF_ENTRY_SENSOR: Final = "entry_sensor"
CONF_DOOR_SENSOR: Final = "door_sensor"
CONF_TOILET_LID_SENSOR: Final = "toilet_lid_sensor"
CONF_HUMIDITY_SENSOR: Final = "humidity_sensor"

SENSOR_KEYS: Final = (
    CONF_PRESENCE_SENSOR,
    CONF_ENTRY_SENSOR,
    CONF_DOOR_SENSOR,
    CONF_TOILET_LID_SENSOR,
    CONF_HUMIDITY_SENSOR,
)

# Options (timings in seconds / minutes, thresholds in %/min)
CONF_ENTRY_WINDOW: Final = "entry_window"  # s
CONF_RELEASE_DELAY: Final = "release_delay"  # s
CONF_EXIT_WAIT: Final = "exit_wait_for_absence"  # s
CONF_EXIT_GUARD: Final = "exit_reentry_guard"  # s
CONF_MAX_OCCUPANCY: Final = "max_occupancy"  # min
CONF_MAX_OCCUPANCY_ABSENCE: Final = "max_occupancy_absence"  # min
CONF_SHOWER_ON_RATE: Final = "shower_on_rate"
CONF_SHOWER_ON_DURATION: Final = "shower_on_duration"  # s
CONF_SHOWER_OFF_RATE: Final = "shower_off_rate"
CONF_SHOWER_OFF_DURATION: Final = "shower_off_duration"  # min
CONF_SHOWER_MAX_DURATION: Final = "shower_max_duration"  # min
CONF_HUMIDITY_WINDOW: Final = "humidity_window"  # min
CONF_TOILET_LID_ALERT: Final = "toilet_lid_alert"  # min

DEFAULT_OPTIONS: Final = {
    CONF_ENTRY_WINDOW: 60,
    CONF_RELEASE_DELAY: 180,
    CONF_EXIT_WAIT: 60,
    CONF_EXIT_GUARD: 20,
    CONF_MAX_OCCUPANCY: 120,
    CONF_MAX_OCCUPANCY_ABSENCE: 5,
    CONF_SHOWER_ON_RATE: 0.7,
    CONF_SHOWER_ON_DURATION: 60,
    CONF_SHOWER_OFF_RATE: 0.15,
    CONF_SHOWER_OFF_DURATION: 5,
    CONF_SHOWER_MAX_DURATION: 60,
    CONF_HUMIDITY_WINDOW: 3,
    CONF_TOILET_LID_ALERT: 40,
}

# Event fired on the HA bus, ``type`` attribute holds the engine event name.
EVENT_NAME: Final = f"{DOMAIN}_event"

SIGNAL_UPDATE: Final = f"{DOMAIN}_update_{{}}"

STORAGE_VERSION: Final = 1

SERVICE_RELEASE: Final = "release"
SERVICE_SET_STATISTICS: Final = "set_statistics"
SERVICE_RESET_STATISTICS: Final = "reset_statistics"
