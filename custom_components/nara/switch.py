import logging
import time
from homeassistant.components.switch import SwitchEntity
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

async def async_setup_entry(hass, entry, async_add_entities):
    """Set up Nara switch platform."""
    coordinator = hass.data[DOMAIN][entry.entry_id]
    entities = [
        NaraSideSwitch(coordinator, "FEED", "LEFT", "mdi:baby-bottle-outline"),
        NaraSideSwitch(coordinator, "FEED", "RIGHT", "mdi:baby-bottle-outline"),
        NaraSideSwitch(coordinator, "PUMP", "LEFT", "mdi:water-pump"),
        NaraSideSwitch(coordinator, "PUMP", "RIGHT", "mdi:water-pump"),
        NaraActivitySwitch(coordinator, "SLEEP", "mdi:bed"),
    ]
    async_add_entities(entities)


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
            # Optimistic update
            self.coordinator.raw_data[track_id] = {
                "type": "SLEEP",
                "beginDt": now,
                "key": track_id
            }
            self.async_write_ha_state()

    async def async_turn_off(self, **kwargs):
        track = self._active_track
        if track and self.activity_type == "SLEEP":
            now = int(time.time() * 1000)
            await self.hass.async_add_executor_job(self.coordinator.api.stop_sleep, track["key"])
            # Optimistic update
            track["endDt"] = now
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
            if track.get("type") == self.activity_type and track.get("endDt") is None:
                # If it's a ghost track (both sides paused, but no endDt), ignore it!
                if self.activity_type == "FEED":
                    left = track.get("breastLeftBeginDt")
                    right = track.get("breastRightBeginDt")
                    if not left and not right:
                        continue
                elif self.activity_type == "PUMP":
                    left = track.get("pumpLeftBeginDt")
                    right = track.get("pumpRightBeginDt")
                    if not left and not right:
                        continue
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
        elif self.activity_type == "PUMP":
            if self.side == "LEFT":
                return bool(track.get("pumpLeftBeginDt"))
            else:
                return bool(track.get("pumpRightBeginDt"))

    async def async_turn_on(self, **kwargs):
        track = self._active_track
        now = int(time.time() * 1000)
        
        if track:
            if self.activity_type == "FEED":
                await self.hass.async_add_executor_job(self.coordinator.api.resume_breast_feed, track["key"], self.side)
                # Optimistic update
                if self.side == "LEFT":
                    track["breastLeftBeginDt"] = now
                else:
                    track["breastRightBeginDt"] = now
            elif self.activity_type == "PUMP":
                await self.hass.async_add_executor_job(self.coordinator.api.resume_pump, track["key"], self.side)
                # Optimistic update
                if self.side == "LEFT":
                    track["pumpLeftBeginDt"] = now
                else:
                    track["pumpRightBeginDt"] = now
        else:
            # Start new track
            if self.activity_type == "FEED":
                track_id = await self.hass.async_add_executor_job(self.coordinator.api.start_breast_feed, self.side)
                # Optimistic update
                self.coordinator.raw_data[track_id] = {
                    "type": "FEED",
                    "feedType": "BREAST",
                    "breastBeginSide": self.side,
                    "breastEndSide": self.side,
                    "breastLeftBeginDt": now if self.side == "LEFT" else None,
                    "breastRightBeginDt": now if self.side == "RIGHT" else None,
                    "key": track_id
                }
            elif self.activity_type == "PUMP":
                track_id = await self.hass.async_add_executor_job(self.coordinator.api.start_pump, self.side)
                # Optimistic update
                self.coordinator.raw_data[track_id] = {
                    "type": "PUMP",
                    "pumpBeginSide": self.side,
                    "pumpEndSide": self.side,
                    "pumpLeftBeginDt": now if self.side == "LEFT" else None,
                    "pumpRightBeginDt": now if self.side == "RIGHT" else None,
                    "key": track_id
                }
                
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs):
        track = self._active_track
        if not track:
            return
            
        if self.activity_type == "FEED":
            await self.hass.async_add_executor_job(self.coordinator.api.pause_breast_feed, track["key"], self.side)
            # Optimistic update
            if self.side == "LEFT":
                track["breastLeftBeginDt"] = None
            else:
                track["breastRightBeginDt"] = None
        elif self.activity_type == "PUMP":
            await self.hass.async_add_executor_job(self.coordinator.api.pause_pump, track["key"], self.side)
            # Optimistic update
            if self.side == "LEFT":
                track["pumpLeftBeginDt"] = None
            else:
                track["pumpRightBeginDt"] = None
                
        self.async_write_ha_state()

