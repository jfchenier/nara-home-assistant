import logging
import time
from homeassistant.components.switch import SwitchEntity
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

async def async_setup_entry(hass, entry, async_add_entities):
    """Set up Nara switch platform."""
    _LOGGER.warning("Setting up switch platform!")
    coordinator = hass.data[DOMAIN][entry.entry_id]
    entities = [
        NaraSideSwitch(coordinator, "FEED", "LEFT", "mdi:baby-bottle-outline"),
        NaraSideSwitch(coordinator, "FEED", "RIGHT", "mdi:baby-bottle-outline"),
        NaraPumpSwitch(coordinator, "PUMP", "mdi:water-pump"),
        NaraActivitySwitch(coordinator, "SLEEP", "mdi:bed"),
    ]
    async_add_entities(entities)
    _LOGGER.warning("Finished setting up switch platform!")


class NaraActivitySwitch(CoordinatorEntity, SwitchEntity):
    """Switch to start/stop a simple activity like sleep."""

    def __init__(self, coordinator, activity_type, icon):
        super().__init__(coordinator)
        self.activity_type = activity_type
        email = coordinator.api.email.lower()
        self._attr_name = f"Nara {activity_type.capitalize()}"
        self._attr_unique_id = f"nara_{email}_{activity_type.lower()}_switch"
        self._attr_icon = icon

    @property
    def _active_track(self):
        for key, track in self.coordinator.raw_data.items():
            if track.get("type") == self.activity_type and track.get("endDt") is None:
                track["key"] = key
                return track
        return None

    @property
    def is_on(self):
        return self._active_track is not None

    async def async_turn_on(self, **kwargs):
        if self.activity_type == "SLEEP":
            now = int(time.time() * 1000)
            track_id = await self.hass.async_add_executor_job(self.coordinator.api.start_sleep)
            self.async_write_ha_state()

    async def async_turn_off(self, **kwargs):
        track = self._active_track
        if track and self.activity_type == "SLEEP":
            now = int(time.time() * 1000)
            await self.hass.async_add_executor_job(self.coordinator.api.stop_sleep, track)
            self.async_write_ha_state()


class NaraSideSwitch(CoordinatorEntity, SwitchEntity):
    """Switch to manage pausing and resuming specific sides of a feed or pump."""

    def __init__(self, coordinator, activity_type, side, icon):
        super().__init__(coordinator)
        self.activity_type = activity_type
        self.side = side
        email = coordinator.api.email.lower()
        self._attr_name = f"Nara {activity_type.capitalize()} {side.capitalize()}"
        self._attr_unique_id = f"nara_{email}_{activity_type.lower()}_{side.lower()}_switch"
        self._attr_icon = icon

    @property
    def _active_track(self):
        for key, track in self.coordinator.raw_data.items():
            if track.get("type") == self.activity_type and not track.get("endDt"):
                if self.activity_type in ["FEED", "PUMP"]:
                    if track.get("breastLeftBeginDt") or track.get("breastRightBeginDt"):
                        track["key"] = key
                        return track
        return None

    @property
    def is_on(self):
        track = self._active_track
        if not track:
            return False
        
        # It's ON if this specific side is actively running
        if self.activity_type == "FEED":
            if self.side == "LEFT":
                return bool(track.get("breastLeftBeginDt"))
            else:
                return bool(track.get("breastRightBeginDt"))

    async def async_turn_on(self, **kwargs):
        track = self._active_track
        now = int(time.time() * 1000)
        
        if track:
            if self.activity_type == "FEED":
                await self.hass.async_add_executor_job(self.coordinator.api.resume_breast_feed, track, self.side)
                pass
        else:
            # Start new track
            if self.activity_type == "FEED":
                track_id = await self.hass.async_add_executor_job(self.coordinator.api.start_breast_feed, self.side)
                pass
                
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs):
        track = self._active_track
        _LOGGER.warning(f"async_turn_off called for {self.side}. _active_track is: {track}")
        if not track:
            return
            
        if self.activity_type == "FEED":
            _LOGGER.warning(f"Calling pause_breast_feed for track {track['key']} side {self.side}")
            res = await self.hass.async_add_executor_job(self.coordinator.api.pause_breast_feed, track, self.side)
            _LOGGER.warning(f"pause_breast_feed returned: {res}")
                
        self.async_write_ha_state()

class NaraPumpSwitch(CoordinatorEntity, SwitchEntity):
    """Switch to manage pausing and resuming the single pump timer."""

    def __init__(self, coordinator, activity_type, icon):
        super().__init__(coordinator)
        self.activity_type = activity_type
        email = coordinator.api.email.lower()
        self._attr_name = "Nara Pump"
        self._attr_unique_id = f"nara_{email}_pump_switch"
        self._attr_icon = icon

    @property
    def _active_track(self):
        for key, track in self.coordinator.raw_data.items():
            if track.get("type") == "PUMP" and not track.get("endDt"):
                if track.get("breastLeftBeginDt") or track.get("breastRightBeginDt"):
                    track["key"] = key
                    return track
        return None

    @property
    def is_on(self):
        return self._active_track is not None

    async def async_turn_on(self, **kwargs):
        track = self._active_track
        now = int(time.time() * 1000)
        
        if track:
            await self.hass.async_add_executor_job(self.coordinator.api.resume_pump, track)
            pass
        else:
            # Start new track
            track_id = await self.hass.async_add_executor_job(self.coordinator.api.start_pump)
            pass
                
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs):
        track = self._active_track
        if not track:
            return
            
        await self.hass.async_add_executor_job(self.coordinator.api.stop_pump, track)
        pass
                
        self.async_write_ha_state()
