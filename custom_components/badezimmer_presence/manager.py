"""Home Assistant glue between sensor states and the presence engine."""

from __future__ import annotations

from datetime import datetime, timedelta
import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import STATE_ON, STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import (
    CALLBACK_TYPE,
    Event,
    EventStateChangedData,
    HomeAssistant,
    State,
    callback,
)
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.event import (
    async_track_point_in_utc_time,
    async_track_state_change_event,
)
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from .const import (
    CONF_DOOR_SENSOR,
    CONF_ENTRY_SENSOR,
    CONF_ENTRY_WINDOW,
    CONF_EXIT_GUARD,
    CONF_EXIT_WAIT,
    CONF_HUMIDITY_SENSOR,
    CONF_HUMIDITY_WINDOW,
    CONF_MAX_OCCUPANCY,
    CONF_MAX_OCCUPANCY_ABSENCE,
    CONF_PRESENCE_SENSOR,
    CONF_RELEASE_DELAY,
    CONF_SHOWER_MAX_DURATION,
    CONF_SHOWER_OFF_DURATION,
    CONF_SHOWER_OFF_RATE,
    CONF_SHOWER_ON_DURATION,
    CONF_SHOWER_ON_RATE,
    CONF_TOILET_LID_ALERT,
    CONF_TOILET_LID_SENSOR,
    DEFAULT_OPTIONS,
    DOMAIN,
    EVENT_NAME,
    SIGNAL_UPDATE,
    STORAGE_VERSION,
)
from .engine import (
    DOOR,
    ENTRY,
    PRESENCE,
    TOILET_LID,
    EngineConfig,
    PresenceEngine,
    ReleaseReason,
)

_LOGGER = logging.getLogger(__name__)

BINARY_INPUTS = {
    CONF_PRESENCE_SENSOR: PRESENCE,
    CONF_ENTRY_SENSOR: ENTRY,
    CONF_DOOR_SENSOR: DOOR,
    CONF_TOILET_LID_SENSOR: TOILET_LID,
}

SAVE_DELAY = 10


def build_engine_config(entry: ConfigEntry) -> EngineConfig:
    """Create the engine configuration from a config entry."""
    data = entry.data
    opts = {**DEFAULT_OPTIONS, **entry.options}
    return EngineConfig(
        has_entry_sensor=bool(data.get(CONF_ENTRY_SENSOR)),
        has_door_sensor=bool(data.get(CONF_DOOR_SENSOR)),
        has_toilet_lid=bool(data.get(CONF_TOILET_LID_SENSOR)),
        has_humidity=bool(data.get(CONF_HUMIDITY_SENSOR)),
        entry_window=timedelta(seconds=opts[CONF_ENTRY_WINDOW]),
        release_delay=timedelta(seconds=opts[CONF_RELEASE_DELAY]),
        exit_wait_for_absence=timedelta(seconds=opts[CONF_EXIT_WAIT]),
        exit_reentry_guard=timedelta(seconds=opts[CONF_EXIT_GUARD]),
        max_occupancy=timedelta(minutes=opts[CONF_MAX_OCCUPANCY]),
        max_occupancy_absence=timedelta(minutes=opts[CONF_MAX_OCCUPANCY_ABSENCE]),
        humidity_window=timedelta(minutes=opts[CONF_HUMIDITY_WINDOW]),
        shower_on_rate=float(opts[CONF_SHOWER_ON_RATE]),
        shower_on_duration=timedelta(seconds=opts[CONF_SHOWER_ON_DURATION]),
        shower_off_rate=float(opts[CONF_SHOWER_OFF_RATE]),
        shower_off_duration=timedelta(minutes=opts[CONF_SHOWER_OFF_DURATION]),
        shower_max_duration=timedelta(minutes=opts[CONF_SHOWER_MAX_DURATION]),
        toilet_lid_alert=timedelta(minutes=opts[CONF_TOILET_LID_ALERT]),
    )


def _binary_value(state: State | None) -> bool | None:
    if state is None or state.state in (STATE_UNAVAILABLE, STATE_UNKNOWN):
        return None
    return state.state == STATE_ON


def _float_value(state: State | None) -> float | None:
    if state is None:
        return None
    try:
        return float(state.state)
    except (TypeError, ValueError):
        return None


class PresenceManager:
    """Runs one :class:`PresenceEngine` for a config entry."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize."""
        self.hass = hass
        self.entry = entry
        self.engine = PresenceEngine(
            config=build_engine_config(entry),
            now=dt_util.utcnow(),
            on_event=self._handle_engine_event,
        )
        self._store: Store[dict[str, Any]] = Store(
            hass, STORAGE_VERSION, f"{DOMAIN}.{entry.entry_id}"
        )
        self._unsubs: list[CALLBACK_TYPE] = []
        self._unsub_timer: CALLBACK_TYPE | None = None
        self._last_saved: dict[str, Any] | None = None
        self._entity_to_input: dict[str, str] = {}
        self._humidity_entity: str | None = entry.data.get(CONF_HUMIDITY_SENSOR)
        for key, name in BINARY_INPUTS.items():
            if entity_id := entry.data.get(key):
                self._entity_to_input[entity_id] = name

    @property
    def signal(self) -> str:
        """Dispatcher signal for entity updates."""
        return SIGNAL_UPDATE.format(self.entry.entry_id)

    async def async_start(self) -> None:
        """Restore state, read current sensor states and start listening."""
        self.engine.restore(await self._store.async_load())
        now = dt_util.utcnow()
        self.engine.now = now
        for entity_id, name in self._entity_to_input.items():
            state = self.hass.states.get(entity_id)
            self.engine.set_initial(
                name, _binary_value(state), state.last_changed if state else now
            )
        if self._humidity_entity:
            self.engine.update_humidity(
                _float_value(self.hass.states.get(self._humidity_entity)), now
            )

        tracked = list(self._entity_to_input)
        if self._humidity_entity:
            tracked.append(self._humidity_entity)
        self._unsubs.append(async_track_state_change_event(self.hass, tracked, self._state_changed))
        self._after_change()

    async def async_stop(self) -> None:
        """Stop listening and persist the state."""
        for unsub in self._unsubs:
            unsub()
        self._unsubs.clear()
        if self._unsub_timer:
            self._unsub_timer()
            self._unsub_timer = None
        await self._store.async_save(self.engine.as_dict())

    @callback
    def _state_changed(self, event: Event[EventStateChangedData]) -> None:
        entity_id = event.data["entity_id"]
        new_state = event.data["new_state"]
        now = dt_util.utcnow()
        if entity_id == self._humidity_entity:
            self.engine.update_humidity(_float_value(new_state), now)
        elif name := self._entity_to_input.get(entity_id):
            self.engine.update_binary(name, _binary_value(new_state), now)
        self._after_change()

    @callback
    def _timer_fired(self, now: datetime) -> None:
        self._unsub_timer = None
        self.engine.tick(max(now, dt_util.utcnow()))
        self._after_change()

    @callback
    def _after_change(self) -> None:
        """Reschedule the timer, notify entities and persist."""
        if self._unsub_timer:
            self._unsub_timer()
            self._unsub_timer = None
        deadline = self.engine.next_deadline()
        # Re-evaluate at least every 30 s while a humidity derivative is
        # running so that the rate decays when the sensor stops reporting.
        if self._humidity_entity:
            fallback = dt_util.utcnow() + timedelta(seconds=30)
            deadline = fallback if deadline is None else min(deadline, fallback)
        if deadline is not None:
            deadline = max(deadline, dt_util.utcnow() + timedelta(milliseconds=500))
            self._unsub_timer = async_track_point_in_utc_time(
                self.hass, self._timer_fired, deadline
            )
        async_dispatcher_send(self.hass, self.signal)
        # only write to disk when something persistent changed
        data = self.engine.as_dict()
        if data != self._last_saved:
            self._last_saved = data
            self._store.async_delay_save(lambda: data, SAVE_DELAY)

    @callback
    def _handle_engine_event(self, event_type: str, data: dict[str, Any]) -> None:
        _LOGGER.debug("%s: %s %s", self.entry.title, event_type, data)
        self.hass.bus.async_fire(
            EVENT_NAME,
            {
                "type": event_type,
                "entry_id": self.entry.entry_id,
                "name": self.entry.title,
                **data,
            },
        )

    @callback
    def async_release(self) -> None:
        """Release the bathroom manually."""
        self.engine.now = dt_util.utcnow()
        self.engine.release(ReleaseReason.MANUAL)
        self._after_change()

    @callback
    def async_changed(self) -> None:
        """Notify entities and save after an external modification."""
        self._after_change()


def get_manager(hass: HomeAssistant, entry_id: str) -> PresenceManager | None:
    """Return the manager of a config entry."""
    entry = hass.config_entries.async_get_entry(entry_id)
    if entry is None or entry.domain != DOMAIN:
        return None
    return getattr(entry, "runtime_data", None)
