"""Scenario tests for the pure presence engine."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from custom_components.badezimmer_presence.engine import (
    DOOR,
    ENTRY,
    PRESENCE,
    TOILET_LID,
    EngineConfig,
    PresenceEngine,
    ReleaseReason,
    Status,
)

T0 = datetime(2026, 11, 1, 8, 0, tzinfo=UTC)


class Sim:
    """Small simulator driving the engine like the HA manager does."""

    def __init__(self, **cfg) -> None:
        self.now = T0
        self.events: list[tuple[str, dict]] = []
        self.engine = PresenceEngine(
            EngineConfig(**cfg), T0, on_event=lambda e, d: self.events.append((e, d))
        )
        for name in (PRESENCE, ENTRY, DOOR, TOILET_LID):
            self.engine.set_initial(name, False, T0 - timedelta(hours=1))
        self.humidity = 50.0
        self.engine.update_humidity(self.humidity, T0)
        # get past the startup check
        self.advance(seconds=61)
        self.events.clear()

    def set(self, name: str, value: bool | None) -> None:
        self.engine.update_binary(name, value, self.now)

    def advance(
        self, seconds: float = 0, minutes: float = 0, humidity_rate: float | None = None
    ) -> None:
        """Advance time, ticking at every deadline and every 30 s."""
        end = self.now + timedelta(seconds=seconds, minutes=minutes)
        while self.now < end:
            step = min(end, self.now + timedelta(seconds=30))
            deadline = self.engine.next_deadline()
            if deadline is not None and self.now < deadline < step:
                step = deadline
            elapsed = (step - self.now).total_seconds() / 60
            self.now = step
            if humidity_rate is not None:
                self.humidity += humidity_rate * elapsed
                self.engine.update_humidity(round(self.humidity, 2), self.now)
            else:
                self.engine.tick(self.now)

    @property
    def occupied(self) -> bool:
        return self.engine.occupied

    def event_types(self) -> list[str]:
        return [e for e, _ in self.events]


def test_entry_then_presence_occupies_and_releases_after_3_minutes() -> None:
    sim = Sim()
    sim.set(ENTRY, True)
    assert sim.engine.status is Status.ENTRY_DETECTED
    sim.advance(seconds=5)
    sim.set(PRESENCE, True)
    assert sim.occupied
    assert not sim.engine.entry_window_active  # timer cancelled
    sim.set(ENTRY, False)
    sim.advance(minutes=5)
    sim.set(PRESENCE, False)
    assert sim.engine.status is Status.WAITING_FOR_RELEASE
    sim.advance(minutes=2, seconds=50)
    assert sim.occupied
    sim.advance(seconds=15)
    assert not sim.occupied
    assert sim.engine.release_reason is ReleaseReason.NO_PRESENCE
    assert sim.engine.stats_usage.count == 1


def test_presence_then_entry_within_window_occupies() -> None:
    sim = Sim()
    sim.set(PRESENCE, True)  # presence first, e.g. sensor in hallway range
    assert not sim.occupied
    sim.advance(seconds=10)
    sim.set(ENTRY, True)
    assert sim.occupied


def test_presence_without_entry_does_not_occupy() -> None:
    sim = Sim()
    sim.set(PRESENCE, True)
    sim.advance(minutes=5)
    assert not sim.occupied


def test_entry_window_expires() -> None:
    sim = Sim()
    sim.set(ENTRY, True)
    sim.set(ENTRY, False)
    sim.advance(seconds=61)
    assert not sim.engine.entry_window_active
    sim.set(PRESENCE, True)
    assert not sim.occupied


def test_toilet_lid_occupies_and_blocks_release() -> None:
    sim = Sim()
    sim.set(TOILET_LID, True)
    assert sim.occupied
    assert sim.engine.usage_detected
    assert sim.engine.status is Status.TOILET
    sim.advance(minutes=30)
    assert sim.occupied
    sim.set(TOILET_LID, False)
    assert sim.engine.stats_toilet.count == 1
    assert sim.engine.stats_toilet.last_minutes == 30.0
    sim.advance(seconds=1)  # presence off for long already
    assert not sim.occupied
    assert not sim.engine.usage_detected


def test_toilet_lid_alert_once() -> None:
    sim = Sim()
    sim.set(TOILET_LID, True)
    sim.advance(minutes=39)
    assert "toilet_lid_alert" not in sim.event_types()
    sim.advance(minutes=2)
    assert sim.event_types().count("toilet_lid_alert") == 1
    assert sim.engine.toilet_lid_alert_active
    sim.advance(minutes=30)
    assert sim.event_types().count("toilet_lid_alert") == 1
    sim.set(TOILET_LID, False)
    assert not sim.engine.toilet_lid_alert_active


def _occupy(sim: Sim) -> None:
    sim.set(ENTRY, True)
    sim.set(PRESENCE, True)
    sim.set(ENTRY, False)
    assert sim.occupied


def test_quick_exit_releases_after_guard() -> None:
    sim = Sim()
    _occupy(sim)
    sim.advance(minutes=4)
    sim.set(DOOR, True)
    sim.advance(seconds=5)
    sim.set(PRESENCE, False)
    sim.advance(seconds=19)
    assert sim.occupied
    sim.advance(seconds=2)
    assert not sim.occupied
    assert sim.engine.release_reason is ReleaseReason.QUICK_EXIT


def test_quick_exit_aborted_by_mirror_presence() -> None:
    sim = Sim()
    _occupy(sim)
    sim.set(DOOR, True)
    sim.set(PRESENCE, False)
    sim.advance(seconds=10)
    sim.set(PRESENCE, True)  # still inside (e.g. at the mirror)
    sim.advance(seconds=30)
    assert sim.occupied


def test_quick_exit_aborted_by_entry() -> None:
    sim = Sim()
    _occupy(sim)
    sim.set(DOOR, True)
    sim.set(PRESENCE, False)
    sim.advance(seconds=10)
    sim.set(ENTRY, True)
    sim.advance(seconds=30)
    assert sim.occupied


def test_quick_exit_times_out_when_presence_stays() -> None:
    sim = Sim()
    _occupy(sim)
    sim.set(DOOR, True)
    sim.advance(seconds=70)
    sim.set(PRESENCE, False)
    sim.advance(seconds=30)
    assert sim.occupied  # normal 3-min rule applies now
    sim.advance(minutes=3)
    assert not sim.occupied
    assert sim.engine.release_reason is ReleaseReason.NO_PRESENCE


def test_quick_exit_not_started_with_open_lid() -> None:
    sim = Sim()
    _occupy(sim)
    sim.set(TOILET_LID, True)
    sim.set(DOOR, True)
    sim.set(PRESENCE, False)
    sim.advance(minutes=10)
    assert sim.occupied


def test_shower_detection_from_humidity() -> None:
    sim = Sim()
    _occupy(sim)
    sim.advance(minutes=4, humidity_rate=2.0)
    assert sim.engine.shower
    assert sim.engine.status is Status.SHOWER
    sim.set(PRESENCE, False)  # radar loses person behind the glass
    sim.advance(minutes=6, humidity_rate=2.0)
    assert sim.occupied
    # humidity flat -> shower ends after 5 min below 0.15 %/min
    sim.advance(minutes=4, humidity_rate=0.0)
    assert sim.engine.shower
    sim.advance(minutes=6, humidity_rate=0.0)
    assert not sim.engine.shower
    assert sim.engine.stats_shower.count == 1
    # presence was off for a long time already -> released right away
    assert not sim.occupied


def test_shower_alone_occupies() -> None:
    sim = Sim()
    sim.advance(minutes=4, humidity_rate=1.5)
    assert sim.engine.shower
    assert sim.occupied


def test_short_humidity_spike_is_not_a_shower() -> None:
    sim = Sim()
    sim.advance(seconds=30, humidity_rate=3.0)
    sim.advance(minutes=5, humidity_rate=0.0)
    assert not sim.engine.shower


def test_shower_max_duration() -> None:
    sim = Sim(shower_max_duration=timedelta(minutes=20))
    sim.advance(minutes=25, humidity_rate=1.0)
    assert sim.engine.stats_shower.count >= 1


def test_emergency_release_after_max_occupancy() -> None:
    sim = Sim()
    sim.set(TOILET_LID, True)  # lid forgotten open
    sim.advance(minutes=119)
    assert sim.occupied
    sim.advance(minutes=2)
    assert not sim.occupied
    assert sim.engine.release_reason is ReleaseReason.MAX_DURATION


def test_emergency_release_needs_absence() -> None:
    sim = Sim()
    sim.set(TOILET_LID, True)
    sim.set(PRESENCE, True)
    sim.advance(minutes=150)
    assert sim.occupied
    sim.set(PRESENCE, False)
    sim.advance(minutes=4)
    assert sim.occupied
    sim.advance(minutes=2)
    assert not sim.occupied


def test_startup_check_releases_stale_occupancy() -> None:
    engine = PresenceEngine(EngineConfig(), T0)
    engine.restore({"occupied": True, "occupied_since": T0.isoformat()})
    for name in (PRESENCE, ENTRY, DOOR, TOILET_LID):
        engine.set_initial(name, False, T0)
    engine.tick(T0 + timedelta(seconds=30))
    assert engine.occupied
    engine.tick(T0 + timedelta(seconds=61))
    assert not engine.occupied
    assert engine.release_reason is ReleaseReason.STARTUP_CHECK


def test_unavailable_presence_is_sensor_error_and_blocks_release() -> None:
    sim = Sim()
    _occupy(sim)
    sim.set(PRESENCE, None)
    assert sim.engine.status is Status.SENSOR_ERROR
    sim.advance(minutes=10)
    assert sim.occupied


def test_presence_only_setup() -> None:
    sim = Sim(
        has_entry_sensor=False, has_door_sensor=False, has_toilet_lid=False, has_humidity=False
    )
    sim.set(PRESENCE, True)
    assert sim.occupied
    sim.set(PRESENCE, False)
    sim.advance(minutes=3, seconds=5)
    assert not sim.occupied


def test_door_acts_as_entry_without_entry_sensor() -> None:
    sim = Sim(has_entry_sensor=False)
    sim.set(DOOR, True)
    sim.set(PRESENCE, True)
    assert sim.occupied


def test_persistence_roundtrip() -> None:
    sim = Sim()
    sim.set(TOILET_LID, True)
    sim.advance(minutes=2)
    sim.set(TOILET_LID, False)
    sim.advance(minutes=1)
    data = sim.engine.as_dict()
    other = PresenceEngine(EngineConfig(), sim.now)
    other.restore(data)
    assert other.stats_usage.count == 1
    assert other.stats_toilet.count == 1
    assert other.stats_toilet.last_minutes == pytest.approx(2.0)


def test_events() -> None:
    sim = Sim()
    _occupy(sim)
    sim.set(PRESENCE, False)
    sim.advance(minutes=4)
    assert sim.event_types() == ["occupied", "released"]
    assert sim.events[1][1]["reason"] == "no_presence"
