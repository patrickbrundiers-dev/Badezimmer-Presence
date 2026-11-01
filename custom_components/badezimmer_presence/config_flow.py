"""Config flow for Badezimmer Presence."""

from __future__ import annotations

from typing import Any

from homeassistant.components.binary_sensor import DOMAIN as BINARY_SENSOR_DOMAIN
from homeassistant.components.sensor import DOMAIN as SENSOR_DOMAIN, SensorDeviceClass
from homeassistant.config_entries import ConfigEntry, ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.const import CONF_NAME
from homeassistant.core import callback
from homeassistant.helpers import selector
import voluptuous as vol

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
    SENSOR_KEYS,
)

_BINARY = selector.EntitySelector(selector.EntitySelectorConfig(domain=BINARY_SENSOR_DOMAIN))
_HUMIDITY = selector.EntitySelector(
    selector.EntitySelectorConfig(domain=SENSOR_DOMAIN, device_class=SensorDeviceClass.HUMIDITY)
)


def _number(minimum: float, maximum: float, step: float, unit: str) -> selector.NumberSelector:
    return selector.NumberSelector(
        selector.NumberSelectorConfig(
            min=minimum,
            max=maximum,
            step=step,
            unit_of_measurement=unit,
            mode=selector.NumberSelectorMode.BOX,
        )
    )


def _sensor_schema(defaults: dict[str, Any], with_name: bool) -> vol.Schema:
    schema: dict[Any, Any] = {}
    if with_name:
        schema[vol.Required(CONF_NAME, default=defaults.get(CONF_NAME, "Badezimmer"))] = (
            selector.TextSelector()
        )
    schema[
        vol.Required(
            CONF_PRESENCE_SENSOR,
            description={"suggested_value": defaults.get(CONF_PRESENCE_SENSOR)},
        )
    ] = _BINARY
    for key in (CONF_ENTRY_SENSOR, CONF_DOOR_SENSOR, CONF_TOILET_LID_SENSOR):
        schema[vol.Optional(key, description={"suggested_value": defaults.get(key)})] = _BINARY
    schema[
        vol.Optional(
            CONF_HUMIDITY_SENSOR,
            description={"suggested_value": defaults.get(CONF_HUMIDITY_SENSOR)},
        )
    ] = _HUMIDITY
    return vol.Schema(schema)


def _options_schema(options: dict[str, Any]) -> vol.Schema:
    opts = {**DEFAULT_OPTIONS, **options}
    fields: dict[str, selector.NumberSelector] = {
        CONF_ENTRY_WINDOW: _number(10, 600, 5, "s"),
        CONF_RELEASE_DELAY: _number(10, 3600, 10, "s"),
        CONF_EXIT_WAIT: _number(5, 600, 5, "s"),
        CONF_EXIT_GUARD: _number(0, 300, 1, "s"),
        CONF_MAX_OCCUPANCY: _number(10, 1440, 5, "min"),
        CONF_MAX_OCCUPANCY_ABSENCE: _number(1, 120, 1, "min"),
        CONF_HUMIDITY_WINDOW: _number(1, 30, 1, "min"),
        CONF_SHOWER_ON_RATE: _number(0.05, 10, 0.05, "%/min"),
        CONF_SHOWER_ON_DURATION: _number(0, 600, 10, "s"),
        CONF_SHOWER_OFF_RATE: _number(-5, 5, 0.05, "%/min"),
        CONF_SHOWER_OFF_DURATION: _number(1, 60, 1, "min"),
        CONF_SHOWER_MAX_DURATION: _number(10, 300, 5, "min"),
        CONF_TOILET_LID_ALERT: _number(1, 600, 1, "min"),
    }
    return vol.Schema({vol.Required(key, default=opts[key]): sel for key, sel in fields.items()})


def _validate(user_input: dict[str, Any]) -> dict[str, str]:
    errors: dict[str, str] = {}
    used = [user_input.get(k) for k in SENSOR_KEYS if user_input.get(k)]
    if len(used) != len(set(used)):
        errors["base"] = "duplicate_sensor"
    return errors


def _clean(user_input: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in user_input.items() if v not in (None, "")}


class BadezimmerPresenceConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow."""

    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Choose the sensors."""
        errors: dict[str, str] = {}
        if user_input is not None:
            errors = _validate(user_input)
            if not errors:
                data = _clean(user_input)
                await self.async_set_unique_id(data[CONF_PRESENCE_SENSOR])
                self._abort_if_unique_id_configured()
                name = data.pop(CONF_NAME)
                return self.async_create_entry(title=name, data=data, options=dict(DEFAULT_OPTIONS))
        return self.async_show_form(
            step_id="user",
            data_schema=_sensor_schema(user_input or {}, with_name=True),
            errors=errors,
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Change the sensors of an existing bathroom."""
        entry = self._get_reconfigure_entry()
        errors: dict[str, str] = {}
        if user_input is not None:
            errors = _validate(user_input)
            if not errors:
                return self.async_update_reload_and_abort(entry, data=_clean(user_input))
        return self.async_show_form(
            step_id="reconfigure",
            data_schema=_sensor_schema(user_input or dict(entry.data), with_name=False),
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        """Return the options flow."""
        return BadezimmerPresenceOptionsFlow()


class BadezimmerPresenceOptionsFlow(OptionsFlow):
    """Timings and thresholds."""

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Manage the options."""
        if user_input is not None:
            return self.async_create_entry(data=user_input)
        return self.async_show_form(
            step_id="init", data_schema=_options_schema(dict(self.config_entry.options))
        )
