"""Pure occupancy engine for Badezimmer Presence.

This module has no Home Assistant dependency so the logic can be unit tested
without a running instance. The Home Assistant glue (``manager.py``) feeds
sensor changes into :class:`PresenceEngine` and calls :meth:`PresenceEngine.tick`
whenever :meth:`PresenceEngine.next_deadline` is reached.

The logic reproduces the original set of Home Assistant automations:

* Bad - Entry Fenster starten / Entry Timer stoppen wenn belegt
* Bad - Belegt setzen
* Bad - Freigeben (incl. minute watchdog)
* Bad - Schnell freigeben bei Exit (with re-entry guard)
* Bad - Maximale Belegungszeit Notbremse
* Bad - Neustart Check
* Bad - Nutzung erkannt
* Bad - Dusche EIN / AUS (humidity derivative)
* Bad - Klodeckel X Minuten offen
* Bad - Statistik Nutzung / Dusche / WC (start/end)
"""

from __future__ import annotations

from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Any

# Input names
PRESENCE = "presence"
ENTRY = "entry"
DOOR = "door"
TOILET_LID = "toilet_lid"
HUMIDITY = "humidity"

# Events emitted by the engine (forwarded to the HA event bus by the manager)
EVENT_OCCUPIED = "occupied"
EVENT_RELEASED = "released"
EVENT_SHOWER_STARTED = "shower_started"
EVENT_SHOWER_ENDED = "shower_ended"
EVENT_TOILET_LID_ALERT = "toilet_lid_alert"


class Status(StrEnum):
    """Overall status, same order of precedence as the old template sensor."""

    SENSOR_ERROR = "sensor_error"
    SHOWER = "shower"
    TOILET = "toilet"
    WAITING_FOR_RELEASE = "waiting_for_release"
    OCCUPIED = "occupied"
    ENTRY_DETECTED = "entry_detected"
    FREE = "free"


class ReleaseReason(StrEnum):
    """Why the bathroom was released."""

    NO_PRESENCE = "no_presence"
    QUICK_EXIT = "quick_exit"
    MAX_DURATION = "max_duration"
    STARTUP_CHECK = "startup_check"
    MANUAL = "manual"


class OccupyReason(StrEnum):
    """Why the bathroom was set to occupied."""

    MANUAL = "manual"
    ENTRY_AND_PRESENCE = "entry_and_presence"
    PRESENCE = "presence"
    SHOWER = "shower"
    TOILET_LID = "toilet_lid"


@dataclass
class EngineConfig:
    """Tunable parameters. Defaults mirror the original automations."""

    has_entry_sensor: bool = True
    has_door_sensor: bool = True
    has_toilet_lid: bool = True
    has_humidity: bool = True
    # Bad - Entry Fenster starten: timer duration
    entry_window: timedelta = timedelta(minutes=1)
    # Bad - Freigeben: presence off "for"
    release_delay: timedelta = timedelta(minutes=3)
    # Bad - Schnell freigeben: wait for presence off / re-entry guard
    exit_wait_for_absence: timedelta = timedelta(minutes=1)
    exit_reentry_guard: timedelta = timedelta(seconds=20)
    # Bad - Maximale Belegungszeit Notbremse
    max_occupancy: timedelta = timedelta(hours=2)
    max_occupancy_absence: timedelta = timedelta(minutes=5)
    # Bad - Neustart Check: delay after start
    startup_check_delay: timedelta = timedelta(minutes=1)
    # Dusche derivative (former derivative helper) and thresholds
    humidity_window: timedelta = timedelta(minutes=3)
    shower_on_rate: float = 0.7
    shower_on_duration: timedelta = timedelta(minutes=1)
    shower_off_rate: float = 0.15
    shower_off_duration: timedelta = timedelta(minutes=5)
    # Improvement: a shower that never ends (e.g. humidity sensor stuck) is
    # cleared after this time. The old setup only did that in the Notbremse.
    shower_max_duration: timedelta = timedelta(hours=1)
    # Bad - Klodeckel X Minuten offen
    toilet_lid_alert: timedelta = timedelta(minutes=40)


@dataclass
class UsageStats:
    """Statistics for one usage type (Nutzung, Dusche, WC)."""

    count: int = 0
    total_minutes: float = 0.0
    last_minutes: float | None = None
    max_minutes: float | None = None
    last_start: datetime | None = None
    last_end: datetime | None = None
    # today / week / month: {"key": period id, "count": int, "minutes": float}
    periods: dict[str, dict[str, Any]] = field(
        default_factory=lambda: {p: _empty_period(None) for p in PERIODS}
    )

    def roll(self, keys: dict[str, str]) -> bool:
        """Reset periods whose id changed (new day/week/month). Returns True if any."""
        changed = False
        for period, key in keys.items():
            current = self.periods.get(period)
            if current is None or current.get("key") != key:
                # first run after an update keeps imported values for this period
                if current is not None and current.get("key") is None:
                    current["key"] = key
                else:
                    self.periods[period] = _empty_period(key)
                changed = True
        return changed

    def period_count(self, period: str) -> int:
        """Count in the given period."""
        return int(self.periods.get(period, {}).get("count") or 0)

    def period_minutes(self, period: str) -> float:
        """Minutes in the given period."""
        return float(self.periods.get(period, {}).get("minutes") or 0.0)

    def period_average(self, period: str) -> float | None:
        """Average duration in the given period."""
        count = self.period_count(period)
        return round(self.period_minutes(period) / count, 1) if count else None

    def record(self, start: datetime, end: datetime) -> None:
        """Record one finished usage."""
        minutes = round(max((end - start).total_seconds(), 0) / 60, 1)
        for period in self.periods.values():
            period["count"] = int(period.get("count") or 0) + 1
            period["minutes"] = round(float(period.get("minutes") or 0.0) + minutes, 1)
        self.count += 1
        self.total_minutes = round(self.total_minutes + minutes, 1)
        self.last_minutes = minutes
        self.max_minutes = minutes if self.max_minutes is None else max(self.max_minutes, minutes)
        self.last_start = start
        self.last_end = end

    def as_dict(self) -> dict[str, Any]:
        """Serialize for storage."""
        return {
            "count": self.count,
            "total_minutes": self.total_minutes,
            "last_minutes": self.last_minutes,
            "max_minutes": self.max_minutes,
            "last_start": self.last_start.isoformat() if self.last_start else None,
            "last_end": self.last_end.isoformat() if self.last_end else None,
            "periods": {k: dict(v) for k, v in self.periods.items()},
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> UsageStats:
        """Deserialize from storage."""
        if not data:
            return cls()
        return cls(
            count=int(data.get("count") or 0),
            total_minutes=float(data.get("total_minutes") or 0.0),
            last_minutes=data.get("last_minutes"),
            max_minutes=data.get("max_minutes"),
            last_start=_parse_dt(data.get("last_start")),
            last_end=_parse_dt(data.get("last_end")),
            periods={
                p: {**_empty_period(None), **((data.get("periods") or {}).get(p) or {})}
                for p in PERIODS
            },
        )


PERIODS = ("today", "week", "month")


def _empty_period(key: str | None) -> dict[str, Any]:
    return {"key": key, "count": 0, "minutes": 0.0}


def default_period_keys(now: datetime) -> dict[str, str]:
    """Period ids for ``now`` (the manager passes local time)."""
    iso = now.isocalendar()
    return {
        "today": now.date().isoformat(),
        "week": f"{iso.year}-W{iso.week:02d}",
        "month": f"{now.year}-{now.month:02d}",
    }


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


@dataclass
class _Input:
    """Last known state of a binary input. ``None`` means unavailable."""

    value: bool | None = None
    since: datetime | None = None


@dataclass
class PresenceEngine:
    """Bathroom occupancy state machine."""

    config: EngineConfig
    now: datetime
    on_event: Callable[[str, dict[str, Any]], None] | None = None
    period_keys: Callable[[datetime], dict[str, str]] = default_period_keys

    occupied: bool = False
    occupied_since: datetime | None = None
    occupy_reason: OccupyReason | None = None
    release_reason: ReleaseReason | None = None
    shower: bool = False
    shower_since: datetime | None = None
    usage_detected: bool = False
    entry_window_until: datetime | None = None
    toilet_lid_alert_active: bool = False

    stats_usage: UsageStats = field(default_factory=UsageStats)
    stats_shower: UsageStats = field(default_factory=UsageStats)
    stats_toilet: UsageStats = field(default_factory=UsageStats)

    humidity: float | None = None
    humidity_rate: float | None = None

    _inputs: dict[str, _Input] = field(default_factory=dict)
    _humidity_samples: deque[tuple[datetime, float]] = field(default_factory=deque)
    _rate_above_since: datetime | None = None
    _rate_below_since: datetime | None = None
    _toilet_since: datetime | None = None
    # quick exit: phase is "wait_absence" or "guard"
    _exit_phase: str | None = None
    _exit_until: datetime | None = None
    _startup_check_at: datetime | None = None

    def __post_init__(self) -> None:
        for name in (PRESENCE, ENTRY, DOOR, TOILET_LID):
            self._inputs.setdefault(name, _Input())
        self._startup_check_at = self.now + self.config.startup_check_delay

    # ------------------------------------------------------------------ inputs

    def is_on(self, name: str) -> bool:
        """Return True if the binary input is on."""
        return self._inputs[name].value is True

    def is_off(self, name: str) -> bool:
        """Return True if the binary input is known to be off."""
        return self._inputs[name].value is False

    def input_available(self, name: str) -> bool:
        """Return True when the input has a known state."""
        return self._inputs[name].value is not None

    def _off_for(self, name: str, duration: timedelta) -> bool:
        inp = self._inputs[name]
        return inp.value is False and inp.since is not None and self.now - inp.since >= duration

    @property
    def toilet_lid_open(self) -> bool:
        """Return True if the toilet lid is open."""
        return self.config.has_toilet_lid and self.is_on(TOILET_LID)

    @property
    def entry_window_active(self) -> bool:
        """Return True while the entry window is running."""
        return self.entry_window_until is not None and self.now < self.entry_window_until

    @property
    def usage_blocks_release(self) -> bool:
        """A running shower or an open toilet lid keeps the room occupied."""
        return self.shower or self.toilet_lid_open

    def set_initial(self, name: str, value: bool | None, since: datetime | None) -> None:
        """Set an input without running edge triggered logic (used on setup)."""
        self._inputs[name] = _Input(value, since or self.now)
        if name == TOILET_LID and value:
            self._toilet_since = since or self.now

    def update_binary(self, name: str, value: bool | None, now: datetime) -> None:
        """Feed a new state of a binary input."""
        self.now = now
        old = self._inputs[name].value
        if old == value:
            return
        self._inputs[name] = _Input(value, now)
        rising = old is False and value is True
        falling = old is True and value is False

        if name == ENTRY and value is True:
            self._on_entry()
        elif name == DOOR and rising:
            self._on_door_opened()
        elif name == PRESENCE:
            if value is True:
                self._on_presence_on(rising)
            elif value is False:
                self._on_presence_off()
        elif name == TOILET_LID:
            if rising:
                self._on_toilet_lid_opened()
            elif falling:
                self._on_toilet_lid_closed()
        self._evaluate()

    def update_humidity(self, value: float | None, now: datetime) -> None:
        """Feed a new humidity reading."""
        self.now = now
        if value is not None:
            self.humidity = value
            self._humidity_samples.append((now, value))
        self._evaluate()

    def tick(self, now: datetime) -> None:
        """Advance time and run all time based rules."""
        self.now = now
        self._evaluate()

    # ------------------------------------------------------------ edge events

    def _on_entry(self) -> None:
        # Bad - Entry Fenster starten (mode restart): only while free
        if not self.occupied:
            self.entry_window_until = self.now + self.config.entry_window
            self._try_occupy(OccupyReason.ENTRY_AND_PRESENCE)
        elif self._exit_phase == "guard":
            # re-entry during quick-exit guard
            self._cancel_exit()

    def _on_door_opened(self) -> None:
        # Without an entry sensor the door contact starts the entry window.
        if not self.config.has_entry_sensor and not self.occupied:
            self.entry_window_until = self.now + self.config.entry_window
            self._try_occupy(OccupyReason.ENTRY_AND_PRESENCE)
            return
        # Bad - Schnell freigeben bei Exit (mode restart)
        self._cancel_exit()
        if self.occupied and not self.usage_blocks_release and self.is_on(PRESENCE):
            self._exit_phase = "wait_absence"
            self._exit_until = self.now + self.config.exit_wait_for_absence

    def _on_presence_on(self, rising: bool) -> None:
        if self._exit_phase == "guard":
            # mirror / re-entry: abort quick exit
            self._cancel_exit()
        if rising:
            self._try_occupy(OccupyReason.ENTRY_AND_PRESENCE)

    def _on_presence_off(self) -> None:
        if self._exit_phase == "wait_absence":
            self._exit_phase = "guard"
            self._exit_until = self.now + self.config.exit_reentry_guard

    def _on_toilet_lid_opened(self) -> None:
        self._toilet_since = self.now
        self.usage_detected = True
        self._cancel_exit()
        self._try_occupy(OccupyReason.TOILET_LID)

    def _on_toilet_lid_closed(self) -> None:
        if self._toilet_since is not None:
            self._record(self.stats_toilet, self._toilet_since)
        self._toilet_since = None
        self.toilet_lid_alert_active = False

    def _cancel_exit(self) -> None:
        self._exit_phase = None
        self._exit_until = None

    # --------------------------------------------------------- state changes

    def _try_occupy(self, reason: OccupyReason) -> None:
        """Bad - Belegt setzen."""
        if self.occupied:
            return
        if reason in (OccupyReason.SHOWER, OccupyReason.TOILET_LID):
            ok = (reason is OccupyReason.SHOWER and self.shower) or (
                reason is OccupyReason.TOILET_LID and self.toilet_lid_open
            )
        else:
            if not self.is_on(PRESENCE):
                return
            if self.config.has_entry_sensor or self.config.has_door_sensor:
                ok = self.entry_window_active
            else:
                # no entry / door sensor at all: presence alone is enough
                ok = True
                reason = OccupyReason.PRESENCE
        if not ok:
            return
        self.occupied = True
        self.occupied_since = self.now
        self.occupy_reason = reason
        self.release_reason = None
        # Bad - Entry Timer stoppen wenn belegt
        self.entry_window_until = None
        self._emit(EVENT_OCCUPIED, {"reason": reason.value})

    def release(self, reason: ReleaseReason) -> None:
        """Bad - Freigeben (and all other release paths)."""
        if not self.occupied:
            return
        start = self.occupied_since or self.now
        self._record(self.stats_usage, start)
        self.occupied = False
        self.occupied_since = None
        self.release_reason = reason
        # Bad - Nutzung erkannt: reset on release
        self.usage_detected = False
        self._cancel_exit()
        self._emit(
            EVENT_RELEASED,
            {
                "reason": reason.value,
                "duration_minutes": self.stats_usage.last_minutes,
            },
        )

    def _set_shower(self, on: bool) -> None:
        if on == self.shower:
            return
        self.shower = on
        if on:
            self.shower_since = self.now
            self.usage_detected = True
            self._cancel_exit()
            self._emit(EVENT_SHOWER_STARTED, {})
            self._try_occupy(OccupyReason.SHOWER)
        else:
            start = self.shower_since or self.now
            self._record(self.stats_shower, start)
            self.shower_since = None
            self._rate_above_since = None
            self._rate_below_since = None
            self._emit(
                EVENT_SHOWER_ENDED,
                {"duration_minutes": self.stats_shower.last_minutes},
            )

    # ------------------------------------------------------------- evaluation

    def _record(self, stats: UsageStats, start: datetime) -> None:
        self._roll_periods()
        stats.record(start, self.now)

    def _roll_periods(self) -> None:
        keys = self.period_keys(self.now)
        for stats in (self.stats_usage, self.stats_shower, self.stats_toilet):
            stats.roll(keys)

    @property
    def toilet_since(self) -> datetime | None:
        """Start of the running toilet usage."""
        return self._toilet_since if self.toilet_lid_open else None

    def occupy_manually(self, now: datetime) -> None:
        """Set occupied by hand (switch)."""
        self.now = now
        if self.occupied:
            return
        self.occupied = True
        self.occupied_since = now
        self.occupy_reason = OccupyReason.MANUAL
        self.release_reason = None
        self.entry_window_until = None
        self._emit(EVENT_OCCUPIED, {"reason": OccupyReason.MANUAL.value})
        self._evaluate()

    def _evaluate(self) -> None:
        now = self.now
        self._roll_periods()

        # Entry window expired
        if self.entry_window_until is not None and now >= self.entry_window_until:
            self.entry_window_until = None

        self._evaluate_shower()

        # Toilet lid open too long (notify once)
        if (
            self.toilet_lid_open
            and not self.toilet_lid_alert_active
            and self._toilet_since is not None
            and now - self._toilet_since >= self.config.toilet_lid_alert
        ):
            self.toilet_lid_alert_active = True
            self._emit(
                EVENT_TOILET_LID_ALERT,
                {"minutes": round((now - self._toilet_since).total_seconds() / 60)},
            )

        if not self.occupied:
            self._startup_check_at = None
            return

        # Quick exit state machine
        if self._exit_phase is not None and self._exit_until is not None:
            if self.usage_blocks_release:
                self._cancel_exit()
            elif now >= self._exit_until:
                if self._exit_phase == "guard" and self.is_off(PRESENCE):
                    self.release(ReleaseReason.QUICK_EXIT)
                    return
                self._cancel_exit()

        # Bad - Neustart Check
        if self._startup_check_at is not None and now >= self._startup_check_at:
            self._startup_check_at = None
            if (
                self.is_off(PRESENCE)
                and not self.usage_blocks_release
                and not self.entry_window_active
            ):
                self.release(ReleaseReason.STARTUP_CHECK)
                return

        # Bad - Freigeben
        if (
            not self.usage_blocks_release
            and not self.entry_window_active
            and self._off_for(PRESENCE, self.config.release_delay)
            # e.g. switched on by hand while nobody is there: give it the delay
            and (
                self.occupied_since is None
                or now - self.occupied_since >= self.config.release_delay
            )
        ):
            self.release(ReleaseReason.NO_PRESENCE)
            return

        # Bad - Maximale Belegungszeit Notbremse
        if (
            self.occupied_since is not None
            and now - self.occupied_since >= self.config.max_occupancy
            and self._off_for(PRESENCE, self.config.max_occupancy_absence)
        ):
            self._set_shower(False)
            self.release(ReleaseReason.MAX_DURATION)

    def _evaluate_shower(self) -> None:
        if not self.config.has_humidity:
            return
        now = self.now
        self.humidity_rate = self._compute_rate()
        rate = self.humidity_rate

        if rate is not None and rate > self.config.shower_on_rate:
            if self._rate_above_since is None:
                self._rate_above_since = now
        else:
            self._rate_above_since = None

        if rate is not None and rate < self.config.shower_off_rate:
            if self._rate_below_since is None:
                self._rate_below_since = now
        else:
            self._rate_below_since = None

        if (
            not self.shower
            and self._rate_above_since is not None
            and now - self._rate_above_since >= self.config.shower_on_duration
        ):
            self._set_shower(True)
        elif self.shower and (
            (
                self._rate_below_since is not None
                and now - self._rate_below_since >= self.config.shower_off_duration
            )
            or (
                self.shower_since is not None
                and now - self.shower_since >= self.config.shower_max_duration
            )
        ):
            self._set_shower(False)

    def _compute_rate(self) -> float | None:
        """Humidity change in %/min over the configured window.

        Like the former derivative helper with time_window 3 min: the value at
        the start of the window is compared to the current value.
        """
        samples = self._humidity_samples
        if not samples or self.humidity is None:
            return None
        window_start = self.now - self.config.humidity_window
        # keep one sample at/before window start as anchor
        while len(samples) >= 2 and samples[1][0] <= window_start:
            samples.popleft()
        anchor_time, anchor_value = samples[0]
        start = max(anchor_time, window_start)
        elapsed = (self.now - start).total_seconds() / 60
        if elapsed < 0.5:
            return 0.0 if len(samples) == 1 else None
        return round((self.humidity - anchor_value) / elapsed, 2)

    # ------------------------------------------------------------- scheduling

    def next_deadline(self) -> datetime | None:
        """Return the next point in time at which tick() must run."""
        cfg = self.config
        candidates: list[datetime] = []
        if self.entry_window_until is not None:
            candidates.append(self.entry_window_until)
        if self._exit_until is not None:
            candidates.append(self._exit_until)
        if self.occupied:
            if self._startup_check_at is not None:
                candidates.append(self._startup_check_at)
            presence = self._inputs[PRESENCE]
            if presence.value is False and presence.since is not None:
                candidates.append(presence.since + cfg.release_delay)
                if self.occupied_since is not None:
                    candidates.append(self.occupied_since + cfg.release_delay)
                candidates.append(presence.since + cfg.max_occupancy_absence)
            if self.occupied_since is not None:
                candidates.append(self.occupied_since + cfg.max_occupancy)
        if self.toilet_lid_open and not self.toilet_lid_alert_active and self._toilet_since:
            candidates.append(self._toilet_since + cfg.toilet_lid_alert)
        if cfg.has_humidity:
            if self._rate_above_since is not None and not self.shower:
                candidates.append(self._rate_above_since + cfg.shower_on_duration)
            if self.shower:
                if self._rate_below_since is not None:
                    candidates.append(self._rate_below_since + cfg.shower_off_duration)
                if self.shower_since is not None:
                    candidates.append(self.shower_since + cfg.shower_max_duration)
        future = [c for c in candidates if c > self.now]
        # Deadlines in the past were already handled by the evaluation that ran
        # at ``self.now`` (e.g. presence off for long while the lid is open), so
        # only future deadlines matter. Returning ``now`` here would spin.
        return min(future) if future else None

    # ----------------------------------------------------------------- status

    @property
    def status(self) -> Status:
        """Overall status (former template sensor ``sensor.badezimmer``)."""
        if not self.input_available(PRESENCE) or (
            self.config.has_toilet_lid and not self.input_available(TOILET_LID)
        ):
            return Status.SENSOR_ERROR
        if self.shower:
            return Status.SHOWER
        if self.toilet_lid_open:
            return Status.TOILET
        if self.occupied and self.is_off(PRESENCE):
            return Status.WAITING_FOR_RELEASE
        if self.occupied:
            return Status.OCCUPIED
        if self.entry_window_active:
            return Status.ENTRY_DETECTED
        return Status.FREE

    # ------------------------------------------------------------ persistence

    def as_dict(self) -> dict[str, Any]:
        """Serialize the persistent part of the state."""
        return {
            "occupied": self.occupied,
            "occupied_since": self.occupied_since.isoformat() if self.occupied_since else None,
            "occupy_reason": self.occupy_reason.value if self.occupy_reason else None,
            "usage_detected": self.usage_detected,
            "shower": self.shower,
            "shower_since": self.shower_since.isoformat() if self.shower_since else None,
            "stats": {
                "usage": self.stats_usage.as_dict(),
                "shower": self.stats_shower.as_dict(),
                "toilet": self.stats_toilet.as_dict(),
            },
        }

    def restore(self, data: dict[str, Any] | None) -> None:
        """Restore state saved with :meth:`as_dict`."""
        if not data:
            return
        self.occupied = bool(data.get("occupied"))
        self.occupied_since = _parse_dt(data.get("occupied_since"))
        if self.occupied and self.occupied_since is None:
            self.occupied_since = self.now
        reason = data.get("occupy_reason")
        self.occupy_reason = (
            OccupyReason(reason) if reason in OccupyReason._value2member_map_ else None
        )
        self.usage_detected = bool(data.get("usage_detected"))
        self.shower = bool(data.get("shower"))
        self.shower_since = _parse_dt(data.get("shower_since"))
        if self.shower and self.shower_since is None:
            self.shower_since = self.now
        stats = data.get("stats") or {}
        self.stats_usage = UsageStats.from_dict(stats.get("usage"))
        self.stats_shower = UsageStats.from_dict(stats.get("shower"))
        self.stats_toilet = UsageStats.from_dict(stats.get("toilet"))
        self._startup_check_at = self.now + self.config.startup_check_delay

    def import_stats(self, kind: str, stats: UsageStats) -> None:
        """Replace statistics (used to take over the old helper values)."""
        setattr(self, f"stats_{kind}", stats)

    def _emit(self, event: str, data: dict[str, Any]) -> None:
        if self.on_event is not None:
            self.on_event(event, data)
