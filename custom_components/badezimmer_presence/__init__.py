"""Badezimmer Presence: bathroom occupancy detection for Home Assistant."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry, ConfigEntryState
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import config_validation as cv, device_registry as dr
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util
import voluptuous as vol

from .const import (
    DOMAIN,
    SERVICE_RELEASE,
    SERVICE_RESET_STATISTICS,
    SERVICE_SET_STATISTICS,
    STORAGE_VERSION,
)
from .engine import PERIODS, UsageStats
from .manager import PresenceManager

PLATFORMS: list[Platform] = [
    Platform.BINARY_SENSOR,
    Platform.BUTTON,
    Platform.SENSOR,
    Platform.SWITCH,
]

type BadezimmerConfigEntry = ConfigEntry[PresenceManager]

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

ATTR_DEVICE_ID = "device_id"
ATTR_KIND = "kind"
KINDS = ("usage", "shower", "toilet")

_TARGET = {vol.Required(ATTR_DEVICE_ID): cv.string}

SET_STATISTICS_SCHEMA = vol.Schema(
    {
        **_TARGET,
        vol.Required(ATTR_KIND): vol.In(KINDS),
        vol.Optional("count"): vol.All(vol.Coerce(int), vol.Range(min=0)),
        vol.Optional("total_minutes"): vol.All(vol.Coerce(float), vol.Range(min=0)),
        vol.Optional("last_minutes"): vol.All(vol.Coerce(float), vol.Range(min=0)),
        vol.Optional("max_minutes"): vol.All(vol.Coerce(float), vol.Range(min=0)),
        **{
            vol.Optional(f"{period}_{field}"): vol.All(
                vol.Coerce(int if field == "count" else float), vol.Range(min=0)
            )
            for period in PERIODS
            for field in ("count", "minutes")
        },
    }
)
RESET_STATISTICS_SCHEMA = vol.Schema({**_TARGET, vol.Optional(ATTR_KIND): vol.In(KINDS)})
RELEASE_SCHEMA = vol.Schema(_TARGET)


def _manager_from_call(hass: HomeAssistant, call: ServiceCall) -> PresenceManager:
    registry = dr.async_get(hass)
    device_id = call.data[ATTR_DEVICE_ID]
    for entry in hass.config_entries.async_entries(DOMAIN):
        if entry.state is not ConfigEntryState.LOADED:
            continue
        devices = dr.async_entries_for_config_entry(registry, entry.entry_id)
        if any(device.id == device_id for device in devices):
            return entry.runtime_data
    raise ServiceValidationError(translation_domain=DOMAIN, translation_key="unknown_device")


async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    """Register the services."""

    async def release(call: ServiceCall) -> None:
        _manager_from_call(hass, call).async_release()

    async def set_statistics(call: ServiceCall) -> None:
        manager = _manager_from_call(hass, call)
        kind = call.data[ATTR_KIND]
        stats: UsageStats = getattr(manager.engine, f"stats_{kind}")
        for key in ("count", "total_minutes", "last_minutes", "max_minutes"):
            if key in call.data:
                setattr(stats, key, call.data[key])
        keys = manager.engine.period_keys(dt_util.utcnow())
        for period in PERIODS:
            for field in ("count", "minutes"):
                if (value := call.data.get(f"{period}_{field}")) is not None:
                    stats.periods.setdefault(period, {"key": keys[period]})
                    stats.periods[period]["key"] = keys[period]
                    stats.periods[period][field] = value
        manager.async_changed()

    async def reset_statistics(call: ServiceCall) -> None:
        manager = _manager_from_call(hass, call)
        kinds = [call.data[ATTR_KIND]] if ATTR_KIND in call.data else list(KINDS)
        for kind in kinds:
            manager.engine.import_stats(kind, UsageStats())
        manager.async_changed()

    hass.services.async_register(DOMAIN, SERVICE_RELEASE, release, RELEASE_SCHEMA)
    hass.services.async_register(
        DOMAIN, SERVICE_SET_STATISTICS, set_statistics, SET_STATISTICS_SCHEMA
    )
    hass.services.async_register(
        DOMAIN, SERVICE_RESET_STATISTICS, reset_statistics, RESET_STATISTICS_SCHEMA
    )
    return True


async def async_setup_entry(hass: HomeAssistant, entry: BadezimmerConfigEntry) -> bool:
    """Set up a bathroom from a config entry."""
    manager = PresenceManager(hass, entry)
    entry.runtime_data = manager
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    await manager.async_start()
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: BadezimmerConfigEntry) -> bool:
    """Unload a config entry."""
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        await entry.runtime_data.async_stop()
    return unloaded


async def _async_update_listener(hass: HomeAssistant, entry: BadezimmerConfigEntry) -> None:
    """Reload when options change."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_remove_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Delete the stored state when the entry is removed."""
    await Store(hass, STORAGE_VERSION, f"{DOMAIN}.{entry.entry_id}").async_remove()
