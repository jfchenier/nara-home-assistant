import logging
import time
from homeassistant.components.button import ButtonEntity
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

async def async_setup_entry(hass, entry, async_add_entities):
    """Set up Nara button platform."""
    coordinator = hass.data[DOMAIN][entry.entry_id]
    entities = [
        NaraFinishButton(coordinator, "FEED", "mdi:check-circle-outline"),
        NaraFinishButton(coordinator, "PUMP", "mdi:check-circle-outline"),
    ]
    async_add_entities(entities)


class NaraFinishButton(CoordinatorEntity, ButtonEntity):
    """Button to finalize and log an active tracking session."""

    def __init__(self, coordinator, activity_type, icon):
        super().__init__(coordinator)
        self.activity_type = activity_type
        email = coordinator.api.email.lower()
        self._attr_name = f"Nara Finish {activity_type.capitalize()}"
        self._attr_unique_id = f"nara_{email}_{activity_type.lower()}_finish_button"
        self._attr_icon = icon

    @property
    def _active_track(self):
        for key, track in self.coordinator.raw_data.items():
            if track.get("type") == self.activity_type and track.get("endDt") is None:
                track["key"] = key
                return track
        return None

    @property
    def available(self):
        """Button is only available (clickable) if there is an active track to finish."""
        return self._active_track is not None

    async def async_press(self) -> None:
        track = self._active_track
        if not track:
            return
            
        now = int(time.time() * 1000)
        if self.activity_type == "FEED":
            await self.hass.async_add_executor_job(self.coordinator.api.stop_breast_feed, track["key"])
        elif self.activity_type == "PUMP":
            await self.hass.async_add_executor_job(self.coordinator.api.stop_pump, track["key"], 0, 0)
            
        # Optimistic update
        track["endDt"] = now
        self.async_write_ha_state()
