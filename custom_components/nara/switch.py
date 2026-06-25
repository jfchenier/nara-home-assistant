import logging
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
        for track in self.coordinator.raw_data.values():
            if track.get("type") == self.activity_type and track.get("endDt") is None:
                return track
        return None

    @property
    def is_on(self):
        return self._active_track is not None

    async def async_turn_on(self, **kwargs):
        if self.activity_type == "SLEEP":
            await self.hass.async_add_executor_job(self.coordinator.api.start_sleep)

    async def async_turn_off(self, **kwargs):
        track = self._active_track
        if track and self.activity_type == "SLEEP":
            await self.hass.async_add_executor_job(self.coordinator.api.stop_sleep, track["key"])


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
        for track in self.coordinator.raw_data.values():
            if track.get("type") == self.activity_type and track.get("endDt") is None:
                return track
        return None

    @property
    def is_on(self):
        track = self._active_track
        if not track:
            return False
        
        # It's ON if this specific side is actively running
        if self.side == "LEFT":
            return track.get("breastLeftBeginDt") is not None
        else:
            return track.get("breastRightBeginDt") is not None

    async def async_turn_on(self, **kwargs):
        track = self._active_track
        if track:
            if self.activity_type == "FEED":
                await self.hass.async_add_executor_job(self.coordinator.api.resume_breast_feed, track["key"], self.side)
            elif self.activity_type == "PUMP":
                await self.hass.async_add_executor_job(self.coordinator.api.resume_pump, track["key"], self.side)
        else:
            # Start new track
            if self.activity_type == "FEED":
                await self.hass.async_add_executor_job(self.coordinator.api.start_breast_feed, self.side)
            elif self.activity_type == "PUMP":
                await self.hass.async_add_executor_job(self.coordinator.api.start_pump, self.side)

    async def async_turn_off(self, **kwargs):
        track = self._active_track
        if track:
            if self.activity_type == "FEED":
                await self.hass.async_add_executor_job(self.coordinator.api.pause_breast_feed, track["key"])
            elif self.activity_type == "PUMP":
                await self.hass.async_add_executor_job(self.coordinator.api.pause_pump, track["key"])
