"""
Climate Platform Device for Wiser Rooms.

https://github.com/asantaga/wiserHomeAssistantPlatform
Angelosantagata@gmail.com

"""
import logging
from .events import fire_events
import voluptuous as vol

from homeassistant.components.climate.const import (
    HVACAction,
    HVACMode,
    ClimateEntityFeature,
)
from homeassistant.components.climate import ClimateEntity
from homeassistant.const import ATTR_TEMPERATURE, TEMP_CELSIUS
from homeassistant.core import callback
from homeassistant.helpers import entity_platform
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from aioWiserHeatAPI.wiserhub import TEMP_MINIMUM, TEMP_MAXIMUM, TEMP_OFF
from .const import (
    DATA,
    DOMAIN,
    MANUFACTURER,
    ROOM,
    WISER_BOOST_PRESETS,
    WISER_SERVICES,
    WISER_SETPOINT_MODES,
)
from .helpers import get_device_name, get_identifier
from .schedules import WiserScheduleEntity

_LOGGER = logging.getLogger(__name__)

ATTR_COPYTO_ENTITY_ID = "to_entity_id"
ATTR_FILENAME = "filename"
ATTR_TIME_PERIOD = "time_period"
ATTR_TEMPERATURE_DELTA = "temperature_delta"

STATUS_AWAY = "Away Mode"
STATUS_AWAY_BOOST = "Away Boost"
STATUS_AWAY_OVERRIDE = "Away Override"
STATUS_BOOST = "Boost"
STATUS_COMFORT = "Comfort"
STATUS_ECO = "EcoIQ"
STATUS_OVERRIDE = "Override"
STATUS_BLANK = ""

WISER_PRESET_TO_HASS = {
    "FromAwayMode": STATUS_AWAY,
    "FromManualMode": STATUS_BLANK,
    "FromBoost": STATUS_BOOST,
    "FromManualOverrideDuringAway": STATUS_AWAY_OVERRIDE,
    "FromBoostDuringAway": STATUS_AWAY_BOOST,
    "FromManualOverride": STATUS_OVERRIDE,
    "FromEcoIQ": STATUS_ECO,
    "FromSchedule": STATUS_BLANK,
    "FromComfortMode": STATUS_COMFORT,
    "FromNoControl": STATUS_BLANK,
}

WISER_PRESETS = {"Advance Schedule": 0, "Cancel Overrides": 0}
WISER_PRESETS.update(WISER_BOOST_PRESETS)

HVAC_MODE_WISER_TO_HASS = {
    "Auto": HVACMode.AUTO,
    "Manual": HVACMode.HEAT,
    "Off": HVACMode.OFF,
}

HVAC_MODE_HASS_TO_WISER = {
    HVACMode.AUTO: "Auto",
    HVACMode.HEAT: "Manual",
    HVACMode.OFF: "Off",
}

SUPPORT_FLAGS = (
    ClimateEntityFeature.TARGET_TEMPERATURE | ClimateEntityFeature.PRESET_MODE
)


async def async_setup_entry(hass, config_entry, async_add_entities):
    """Set up Wiser climate device."""
    coordinator = hass.data[DOMAIN][config_entry.entry_id][DATA]  # Get coordinator

    if coordinator.wiserhub.rooms:
        _LOGGER.debug("Setting up Room climate entities")
        wiser_rooms = [
            WiserRoom(hass, coordinator, room.id)
            for room in coordinator.wiserhub.rooms.all
            if len(room.devices) > 0
        ]
        async_add_entities(wiser_rooms, True)

        # Setup services
        platform = entity_platform.async_get_current_platform()

        platform.async_register_entity_service(
            WISER_SERVICES["SERVICE_BOOST_HEATING"],
            {
                vol.Required(
                    ATTR_TIME_PERIOD, default=coordinator.boost_time
                ): vol.Coerce(int),
                vol.Any(
                    vol.Optional(ATTR_TEMPERATURE_DELTA, default=0),
                    vol.Optional(ATTR_TEMPERATURE, default=0),
                ): vol.Coerce(float),
            },
            "async_boost_heating",
        )


class WiserRoom(CoordinatorEntity, ClimateEntity, WiserScheduleEntity):
    """WiserRoom ClientEntity Object."""

    def __init__(self, hass, coordinator, room_id):
        """Initialize the sensor."""
        super().__init__(coordinator)
        self._hass = hass
        self._data = coordinator
        self._room_id = room_id
        self._room = self._data.wiserhub.rooms.get_by_id(self._room_id)
        self._hvac_modes_list = [modes for modes in HVAC_MODE_HASS_TO_WISER.keys()]
        self._is_heating = self._room.is_heating
        self._schedule = self._room.schedule
        self._previous_target_temp = self.current_temperature

        # Set initial previous target temp based on config setting
        if self._schedule and self._data.previous_target_temp_option == "Schedule":
            self._previous_target_temp = self._room.schedule.current_setting
        elif self._data.previous_target_temp_option == "Minimum":
            self._previous_target_temp = TEMP_MINIMUM

        _LOGGER.debug(f"{self._data.wiserhub.system.name} {self.name} initailise")

    async def async_force_update(self):
        _LOGGER.debug(f"Hub update initiated by {self.name}")
        await self._data.async_refresh()

    @callback
    def _handle_coordinator_update(self) -> None:
        _LOGGER.debug(f"{self.name} updating")
        previous_room_values = self._room
        self._room = self._data.wiserhub.rooms.get_by_id(self._room_id)
        self._schedule = self._room.schedule

        if not self._room.is_boosted:
            self._boosted_time = 0
        self.async_write_ha_state()

        fire_events(
            self._hass,
            self.entity_id,
            previous_room_values,
            self._room,
        )

    @property
    def current_temperature(self):
        """Return current temp from data."""
        return self._room.current_temperature

    @property
    def current_humidity(self):
        """Return current temp from data."""
        return self._room.current_humidity

    @property
    def device_info(self):
        """Return device specific attributes."""
        return {
            "name": get_device_name(self._data, self._room_id, "room"),
            "identifiers": {
                (DOMAIN, get_identifier(self._data, self._room_id, "room"))
            },
            "manufacturer": MANUFACTURER,
            "model": ROOM.title(),
            "via_device": (DOMAIN, self._data.wiserhub.system.name),
        }

    @property
    def icon(self):
        """Return icon to show if radiator is heating, not heating or set to off."""
        if self._room.mode == "Off":
            return "mdi:radiator-off"
        elif self._room.is_heating:
            return "mdi:radiator"
        else:
            return "mdi:radiator-disabled"

    @property
    def hvac_action(self):
        """Return hvac action from data."""
        return HVACAction.HEATING if self._room.is_heating else HVACAction.IDLE

    @property
    def hvac_mode(self):
        return HVAC_MODE_WISER_TO_HASS[self._room.mode]

    @property
    def hvac_modes(self):
        """Return the list of available operation modes."""
        return self._hvac_modes_list

    async def async_set_hvac_mode(self, hvac_mode):
        """Set new operation mode."""
        _LOGGER.debug(f"Setting HVAC mode to {hvac_mode} for {self._room.name}")
        try:
            if self.hvac_mode == HVACMode.HEAT and self.target_temperature != -20:

                self._previous_target_temp = self._room.current_target_temperature

            await self._room.set_mode(HVAC_MODE_HASS_TO_WISER[hvac_mode])
            # Restore previous manual target temp when coming from Off mode back to Manual
            if hvac_mode == HVACMode.HEAT and self._previous_target_temp:
                await self._room.set_target_temperature(self._previous_target_temp)
            await self.async_force_update()
            return True
        except KeyError:
            _LOGGER.error(f"Invalid HVAC mode.  Options are {self.hvac_modes}")

    @property
    def max_temp(self):
        """Return max temp from data."""
        return TEMP_MAXIMUM

    @property
    def min_temp(self):
        """Return min temp from data."""
        return TEMP_MINIMUM

    @property
    def name(self):
        """Return Name of device."""
        return get_device_name(self._data, self._room_id, "room")

    @property
    def preset_mode(self):
        """Get current preset mode."""
        try:
            if (
                WISER_PRESET_TO_HASS[self._room.target_temperature_origin]
                == STATUS_BOOST
            ):
                if int(self._room.boost_time_remaining / 60) != 0:
                    return f"{STATUS_BOOST} {int(self._room.boost_time_remaining/60)}m"
                else:
                    return STATUS_BOOST
            else:
                return WISER_PRESET_TO_HASS[self._room.target_temperature_origin]
        except KeyError:
            return STATUS_BLANK

    @property
    def preset_modes(self):
        """Return the list of available preset modes."""
        if not self._schedule:
            return [
                mode
                for mode in list(WISER_PRESETS.keys())
                if mode != "Advance Schedule"
            ]
        return list(WISER_PRESETS.keys())

    async def async_set_preset_mode(self, preset_mode: str) -> None:
        """Async call to set preset mode ."""
        _LOGGER.debug(f"Setting Preset Mode {preset_mode} for {self._room.name}")
        if preset_mode == "Advance Schedule":
            await self._room.schedule_advance()
        elif WISER_PRESETS[preset_mode] == 0:
            await self._room.cancel_overrides()
        elif preset_mode.startswith("Boost"):
            boost_time = WISER_PRESETS[preset_mode]
            boost_temp = self._data.boost_temp
            await self._room.boost(boost_temp, boost_time)
        else:
            _LOGGER.error(f"Invalid preset mode.  Options are {self.preset_modes}")

        await self.async_force_update()

    @property
    def state(self):
        """Return state"""
        return HVAC_MODE_WISER_TO_HASS[self._room.mode]

    @property
    def extra_state_attributes(self):
        """Return state attributes."""
        # Generic attributes
        attrs = super().state_attributes

        # Settings
        attrs["window_state"] = self._room.window_state
        attrs["window_detection_active"] = self._room.window_detection_active
        attrs["away_mode_supressed"] = self._room.away_mode_suppressed
        attrs["heating_type"] = self._room.heating_type
        attrs["number_of_heating_actuators"] = self._room.number_of_heating_actuators
        attrs["demand_type"] = self._room.demand_type

        # Status
        attrs["target_temperature_origin"] = self._room.target_temperature_origin
        attrs["is_boosted"] = self._room.is_boosted
        attrs["is_override"] = self._room.is_override
        attrs["is_heating"] = self._room.is_heating
        attrs["control_output_state"] = "On" if self._room.is_heating else "Off"
        attrs["heating_rate"] = self._room.heating_rate

        # If boosted show boost end time
        if self._room.is_boosted:
            attrs["boost_end"] = self._room.boost_end_time

        attrs["boost_time_remaining"] = int(self._room.boost_time_remaining / 60)
        attrs["percentage_demand"] = self._room.percentage_demand
        attrs["comfort_mode_score"] = self._room.comfort_mode_score
        attrs["control_direction"] = self._room.control_direction
        attrs["displayed_setpoint"] = self._room.displayed_setpoint

        # Room can have no schedule
        if self._room.schedule:
            attrs["schedule_id"] = self._room.schedule.id
            attrs["schedule_name"] = self._room.schedule.name
            attrs["current_schedule_temp"] = self._room.schedule.current_setting
            attrs["next_day_change"] = str(self._room.schedule.next.day)
            attrs["next_schedule_change"] = str(self._room.schedule.next.time)
            attrs["next_schedule_datetime"] = str(self._room.schedule.next.datetime)
            attrs["next_schedule_temp"] = self._room.schedule.next.setting

        return attrs

    @property
    def supported_features(self):
        """Return the list of supported features."""
        return SUPPORT_FLAGS

    @property
    def target_temperature(self):
        """Return target temp."""
        if (
            self._room.mode == "Off"
            or self._room.current_target_temperature == TEMP_OFF
        ):
            return None
        return self._room.current_target_temperature

    async def async_set_temperature(self, **kwargs):
        """Set new target temperatures."""
        target_temperature = kwargs.get(ATTR_TEMPERATURE)

        if target_temperature is None:
            return False

        if self._data.setpoint_mode == WISER_SETPOINT_MODES["Boost"] or (
            self._data.setpoint_mode == WISER_SETPOINT_MODES["BoostAuto"]
            and self.state == HVACMode.AUTO
        ):
            _LOGGER.info(
                f"Setting temperature for {self.name} to {target_temperature} using boost"
            )
            await self._room.set_target_temperature_for_duration(
                target_temperature, self._data.boost_time
            )
        else:
            _LOGGER.info(f"Setting temperature for {self.name} to {target_temperature}")
            await self._room.set_target_temperature(target_temperature)
        await self.async_force_update()
        return True

    @property
    def temperature_unit(self):
        """Return temp units."""
        return TEMP_CELSIUS

    @property
    def unique_id(self):
        """Return unique Id."""
        return (
            f"{self._data.wiserhub.system.name}-WiserRoom-{self._room_id}-{self.name}"
        )

    @callback
    async def async_boost_heating(
        self, time_period: int, temperature_delta=0, temperature=0
    ) -> None:
        """Boost heating for room"""
        # If neither temperature_delta or temperature set then use config boost temp. Issue #216
        if temperature_delta == 0 and temperature == 0:
            temperature_delta = self._data.boost_temp

        if temperature_delta > 0:
            _LOGGER.info(
                f"Boosting heating for {self._room.name} by {temperature_delta}C for {time_period}m "
            )
            await self._room.boost(temperature_delta, time_period)
        if temperature > 0 and temperature_delta == 0:
            _LOGGER.info(
                f"Boosting heating for {self._room.name} to {temperature}C for {time_period}m "
            )
            await self._room.set_target_temperature_for_duration(
                temperature, time_period
            )
        await self.async_force_update()
