import logging
from homeassistant.components.sensor import SensorEntity, SensorDeviceClass, SensorStateClass
from homeassistant.const import UnitOfTime, UnitOfVolume
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

WINDOWS = {
    "1_day": "1 Day",
    "7_days": "7 Days",
    "14_days": "14 Days"
}

SENSOR_TYPES = {
    "sleep_total": {
        "name": "Total Sleep",
        "icon": "mdi:sleep",
        "device_class": SensorDeviceClass.DURATION,
        "native_unit_of_measurement": UnitOfTime.HOURS,
        "state_class": SensorStateClass.TOTAL,
        "value_fn": lambda d: round((d.get("sleep", {}).get("total_duration_ms", 0) / 3600000.0), 2)
    },
    "sleep_day": {
        "name": "Day Sleep",
        "icon": "mdi:sun-clock",
        "device_class": SensorDeviceClass.DURATION,
        "native_unit_of_measurement": UnitOfTime.HOURS,
        "state_class": SensorStateClass.TOTAL,
        "value_fn": lambda d: round((d.get("sleep", {}).get("day_duration_ms", 0) / 3600000.0), 2)
    },
    "sleep_night": {
        "name": "Night Sleep",
        "icon": "mdi:moon-waxing-crescent",
        "device_class": SensorDeviceClass.DURATION,
        "native_unit_of_measurement": UnitOfTime.HOURS,
        "state_class": SensorStateClass.TOTAL,
        "value_fn": lambda d: round(((d.get("sleep", {}).get("total_duration_ms", 0) - d.get("sleep", {}).get("day_duration_ms", 0)) / 3600000.0), 2)
    },
    "nap_count": {
        "name": "Nap Count",
        "icon": "mdi:bed",
        "state_class": SensorStateClass.TOTAL,
        "value_fn": lambda d: d.get("sleep", {}).get("nap_count", 0)
    },
    "diaper_total": {
        "name": "Total Diapers",
        "icon": "mdi:baby-carriage",
        "state_class": SensorStateClass.TOTAL,
        "value_fn": lambda d: d.get("diaper", {}).get("total", 0)
    },
    "diaper_pee": {
        "name": "Pee Diapers",
        "icon": "mdi:water",
        "state_class": SensorStateClass.TOTAL,
        "value_fn": lambda d: d.get("diaper", {}).get("pee", 0)
    },
    "diaper_poop": {
        "name": "Poop Diapers",
        "icon": "mdi:emoticon-poop",
        "state_class": SensorStateClass.TOTAL,
        "value_fn": lambda d: d.get("diaper", {}).get("poop", 0)
    },
    "feed_bf_duration": {
        "name": "Breastfeed Duration",
        "icon": "mdi:mother-nurse",
        "device_class": SensorDeviceClass.DURATION,
        "native_unit_of_measurement": UnitOfTime.HOURS,
        "state_class": SensorStateClass.TOTAL,
        "value_fn": lambda d: round((d.get("feed", {}).get("total_bf_ms", 0) / 3600000.0), 2)
    },
    "feed_bottle_volume": {
        "name": "Bottle Volume",
        "icon": "mdi:baby-bottle",
        "device_class": SensorDeviceClass.VOLUME,
        "native_unit_of_measurement": UnitOfVolume.FLUID_OUNCES,
        "state_class": SensorStateClass.TOTAL,
        "value_fn": lambda d: round(d.get("feed", {}).get("bottle_vol_floz", 0), 1)
    },
    "pump_volume": {
        "name": "Pump Volume",
        "icon": "mdi:pump",
        "device_class": SensorDeviceClass.VOLUME,
        "native_unit_of_measurement": UnitOfVolume.FLUID_OUNCES,
        "state_class": SensorStateClass.TOTAL,
        "value_fn": lambda d: round(d.get("pump", {}).get("total_vol_floz", 0), 1)
    }
}

async def async_setup_entry(hass, entry, async_add_entities):
    """Set up Nara sensor platform."""
    coordinator = hass.data[DOMAIN][entry.entry_id]

    sensors = []
    for window_key, window_name in WINDOWS.items():
        for sensor_id, sensor_info in SENSOR_TYPES.items():
            sensors.append(NaraSensor(coordinator, window_key, window_name, sensor_id, sensor_info))

    sensors.append(NaraTimeSinceSensor(coordinator, "FEED", "Last Feed", "mdi:baby-bottle"))
    sensors.append(NaraTimeSinceSensor(coordinator, "DIAPER", "Last Diaper", "mdi:baby-carriage"))
    sensors.append(NaraTimeSinceSensor(coordinator, "SLEEP", "Wake Window Start", "mdi:eye-outline"))

    async_add_entities(sensors)


class NaraSensor(CoordinatorEntity, SensorEntity):
    """Representation of a Nara Sensor."""

    def __init__(self, coordinator, window_key, window_name, sensor_id, sensor_info):
        """Initialize the sensor."""
        super().__init__(coordinator)
        self.window_key = window_key
        self.sensor_id = sensor_id
        self.sensor_info = sensor_info

        # Use the email as the unique identifier namespace
        email = coordinator.api.email.lower()
        self._attr_unique_id = f"nara_{email}_{window_key}_{sensor_id}"
        self._attr_name = f"Nara {window_name} {sensor_info['name']}"
        self._attr_icon = sensor_info.get("icon")
        self._attr_device_class = sensor_info.get("device_class")
        self._attr_native_unit_of_measurement = sensor_info.get("native_unit_of_measurement")
        self._attr_state_class = sensor_info.get("state_class")

    @property
    def native_value(self):
        """Return the state of the sensor."""
        if not self.coordinator.data:
            return None
        
        window_data = self.coordinator.data.get(self.window_key, {})
        return self.sensor_info["value_fn"](window_data)

import datetime
from homeassistant.util import dt as dt_util

class NaraTimeSinceSensor(CoordinatorEntity, SensorEntity):
    """Sensor that outputs the timestamp of the last activity of a given type."""

    def __init__(self, coordinator, activity_type, name, icon):
        super().__init__(coordinator)
        self.activity_type = activity_type
        email = coordinator.api.email.lower()
        self._attr_name = f"Nara {name}"
        self._attr_unique_id = f"nara_{email}_time_since_{activity_type.lower()}"
        self._attr_device_class = SensorDeviceClass.TIMESTAMP
        self._attr_icon = icon

    @property
    def native_value(self):
        """Find the latest track of this type and return its end time as a timestamp."""
        raw_data = self.coordinator.raw_data
        
        latest_time = None
        for track in raw_data.values():
            if track.get("type") == self.activity_type:
                # Use endDt if available, else beginDt
                dt_val = track.get("endDt") or track.get("beginDt")
                if dt_val:
                    if latest_time is None or dt_val > latest_time:
                        latest_time = dt_val
                        
        if latest_time:
            return dt_util.utc_from_timestamp(latest_time / 1000.0)
        return None
