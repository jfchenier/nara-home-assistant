import logging
from homeassistant.components.binary_sensor import BinarySensorEntity, BinarySensorDeviceClass
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

TIMER_TYPES = {
    "FEED": {"name": "Feed Active", "icon": "mdi:baby-bottle-outline"},
    "SLEEP": {"name": "Sleep Active", "icon": "mdi:bed"},
    "PUMP": {"name": "Pump Active", "icon": "mdi:water-pump"},
}

async def async_setup_entry(hass, entry, async_add_entities):
    """Set up Nara binary sensor platform."""
    coordinator = hass.data[DOMAIN][entry.entry_id]
    entities = [NaraActiveBinarySensor(coordinator, key, info) for key, info in TIMER_TYPES.items()]
    async_add_entities(entities)

class NaraActiveBinarySensor(CoordinatorEntity, BinarySensorEntity):
    """Binary sensor that indicates if an activity is actively running or paused."""

    def __init__(self, coordinator, activity_type, info):
        """Initialize the binary sensor."""
        super().__init__(coordinator)
        self.activity_type = activity_type
        email = coordinator.api.email.lower()
        self._attr_name = f"Nara {info['name']}"
        self._attr_unique_id = f"nara_{email}_{activity_type.lower()}_active"
        self._attr_device_class = BinarySensorDeviceClass.RUNNING
        self._attr_icon = info["icon"]

    @property
    def _active_track(self):
        """Find the active track of this type."""
        for key, track in self.coordinator.raw_data.items():
            if track.get("type") == self.activity_type and not track.get("endDt"):
                if self.activity_type in ["FEED", "PUMP"]:
                    if track.get("breastLeftBeginDt") or track.get("breastRightBeginDt"):
                        track["key"] = key
                        return track
                elif self.activity_type == "SLEEP":
                    if track.get("beginDt"):
                        track["key"] = key
                        return track
        return None

    @property
    def is_on(self):
        """Return true if there is an active track of this type."""
        return self._active_track is not None

    @property
    def extra_state_attributes(self):
        """Return details about the active track."""
        track = self._active_track
        if not track:
            return {}
            
        attrs = {"track_id": track.get("key")}
        
        # Add running side details if applicable
        if self.activity_type in ["FEED", "PUMP"]:
            running_side = None
            if track.get("breastLeftBeginDt"):
                running_side = "LEFT"
            elif track.get("breastRightBeginDt"):
                running_side = "RIGHT"
                
            attrs["running_side"] = running_side
            attrs["status"] = "Running" if running_side else "Paused"
            
            # Cumulative durations
            attrs["left_duration_ms"] = track.get("breastLeftDuration", 0)
            attrs["right_duration_ms"] = track.get("breastRightDuration", 0)
            
        return attrs
