"""Integration tests running inside Home Assistant."""

from __future__ import annotations

from datetime import timedelta

from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import device_registry as dr, entity_registry as er
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry, async_fire_time_changed

from custom_components.badezimmer_presence.const import (
    CONF_DOOR_SENSOR,
    CONF_ENTRY_SENSOR,
    CONF_HUMIDITY_SENSOR,
    CONF_PRESENCE_SENSOR,
    CONF_RELEASE_DELAY,
    CONF_TOILET_LID_SENSOR,
    DEFAULT_OPTIONS,
    DOMAIN,
    EVENT_NAME,
)

PRESENCE = "binary_sensor.bad_praesenz"
ENTRY = "binary_sensor.bad_eintritt"
DOOR = "binary_sensor.bad_tuer"
LID = "binary_sensor.klodeckel"
HUMIDITY = "sensor.bad_feuchte"


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Enable custom integrations."""
    return


def _set_all(hass: HomeAssistant) -> None:
    for entity in (PRESENCE, ENTRY, DOOR, LID):
        hass.states.async_set(entity, "off")
    hass.states.async_set(HUMIDITY, "50", {"device_class": "humidity", "unit_of_measurement": "%"})


async def test_config_flow(hass: HomeAssistant) -> None:
    """The user flow creates an entry with default options."""
    _set_all(hass)
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {"name": "Großes Bad", CONF_PRESENCE_SENSOR: PRESENCE, CONF_ENTRY_SENSOR: PRESENCE},
    )
    assert result["errors"] == {"base": "duplicate_sensor"}

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            "name": "Großes Bad",
            CONF_PRESENCE_SENSOR: PRESENCE,
            CONF_ENTRY_SENSOR: ENTRY,
            CONF_TOILET_LID_SENSOR: LID,
        },
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Großes Bad"
    assert result["data"] == {
        CONF_PRESENCE_SENSOR: PRESENCE,
        CONF_ENTRY_SENSOR: ENTRY,
        CONF_TOILET_LID_SENSOR: LID,
    }
    assert result["options"] == DEFAULT_OPTIONS
    await hass.async_block_till_done()

    # second bathroom with the same presence sensor is refused
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"name": "Doppelt", CONF_PRESENCE_SENSOR: PRESENCE}
    )
    assert result["type"] is FlowResultType.ABORT


async def _setup(hass: HomeAssistant, **options) -> MockConfigEntry:
    _set_all(hass)
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Bad",
        data={
            CONF_PRESENCE_SENSOR: PRESENCE,
            CONF_ENTRY_SENSOR: ENTRY,
            CONF_DOOR_SENSOR: DOOR,
            CONF_TOILET_LID_SENSOR: LID,
            CONF_HUMIDITY_SENSOR: HUMIDITY,
        },
        options={**DEFAULT_OPTIONS, **options},
        unique_id=PRESENCE,
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


def _id(hass: HomeAssistant, entry: MockConfigEntry, domain: str, key: str) -> str:
    entity_id = er.async_get(hass).async_get_entity_id(domain, DOMAIN, f"{entry.entry_id}_{key}")
    assert entity_id, key
    return entity_id


async def test_occupancy_cycle(hass: HomeAssistant, freezer) -> None:
    """Entry + presence occupies, absence releases, stats and events update."""
    entry = await _setup(hass)
    occupied = _id(hass, entry, "binary_sensor", "occupied")
    status = _id(hass, entry, "sensor", "status")
    count = _id(hass, entry, "sensor", "usage_count")
    events = []
    hass.bus.async_listen(EVENT_NAME, lambda e: events.append(e.data))

    assert hass.states.get(occupied).state == "off"
    assert hass.states.get(status).state == "free"

    hass.states.async_set(ENTRY, "on")
    await hass.async_block_till_done()
    assert hass.states.get(status).state == "entry_detected"

    hass.states.async_set(PRESENCE, "on")
    await hass.async_block_till_done()
    assert hass.states.get(occupied).state == "on"
    assert hass.states.get(status).state == "occupied"

    hass.states.async_set(ENTRY, "off")
    hass.states.async_set(PRESENCE, "off")
    await hass.async_block_till_done()
    assert hass.states.get(status).state == "waiting_for_release"

    freezer.tick(timedelta(minutes=2))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    assert hass.states.get(occupied).state == "on"

    freezer.tick(timedelta(minutes=1, seconds=5))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    assert hass.states.get(occupied).state == "off"
    assert hass.states.get(count).state == "1"
    assert [e["type"] for e in events] == ["occupied", "released"]
    assert events[1]["reason"] == "no_presence"


async def test_release_button_and_services(hass: HomeAssistant) -> None:
    """Manual release and statistics services."""
    entry = await _setup(hass)
    occupied = _id(hass, entry, "binary_sensor", "occupied")
    button = _id(hass, entry, "button", "release")

    hass.states.async_set(LID, "on")
    await hass.async_block_till_done()
    assert hass.states.get(occupied).state == "on"

    await hass.services.async_call("button", "press", {"entity_id": button}, blocking=True)
    await hass.async_block_till_done()
    assert hass.states.get(occupied).state == "off"

    device = dr.async_get(hass).async_get_device(identifiers={(DOMAIN, entry.entry_id)})
    await hass.services.async_call(
        DOMAIN,
        "set_statistics",
        {"device_id": device.id, "kind": "usage", "count": 1681, "total_minutes": 18479.5},
        blocking=True,
    )
    await hass.async_block_till_done()
    assert hass.states.get(_id(hass, entry, "sensor", "usage_count")).state == "1681"
    assert float(
        hass.states.get(_id(hass, entry, "sensor", "usage_average_duration")).state
    ) == pytest.approx(11.0, abs=0.1)

    await hass.services.async_call(
        DOMAIN,
        "set_statistics",
        {"device_id": device.id, "kind": "toilet", "today_count": 5, "today_minutes": 87.8},
        blocking=True,
    )
    await hass.async_block_till_done()
    assert hass.states.get(_id(hass, entry, "sensor", "toilet_count_today")).state == "5"
    assert float(hass.states.get(_id(hass, entry, "sensor", "toilet_average_today")).state) == (
        pytest.approx(17.6)
    )

    switch = _id(hass, entry, "switch", "occupied_switch")
    await hass.services.async_call("switch", "turn_on", {"entity_id": switch}, blocking=True)
    await hass.async_block_till_done()
    assert hass.states.get(occupied).state == "on"
    assert hass.states.get(switch).state == "on"
    await hass.services.async_call("switch", "turn_off", {"entity_id": switch}, blocking=True)
    await hass.async_block_till_done()
    assert hass.states.get(occupied).state == "off"

    await hass.services.async_call(
        DOMAIN, "reset_statistics", {"device_id": device.id}, blocking=True
    )
    await hass.async_block_till_done()
    assert hass.states.get(_id(hass, entry, "sensor", "usage_count")).state == "0"


async def test_state_survives_reload(hass: HomeAssistant) -> None:
    """Occupancy and statistics are restored after a reload."""
    entry = await _setup(hass)
    occupied = _id(hass, entry, "binary_sensor", "occupied")
    hass.states.async_set(LID, "on")
    await hass.async_block_till_done()
    assert hass.states.get(occupied).state == "on"

    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    assert hass.states.get(occupied).state == "on"

    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()


async def test_options_flow(hass: HomeAssistant) -> None:
    """Options can be changed and reload the entry."""
    entry = await _setup(hass)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] is FlowResultType.FORM
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {**DEFAULT_OPTIONS, CONF_RELEASE_DELAY: 120}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()
    assert entry.options[CONF_RELEASE_DELAY] == 120
    assert entry.runtime_data.engine.config.release_delay == timedelta(seconds=120)
