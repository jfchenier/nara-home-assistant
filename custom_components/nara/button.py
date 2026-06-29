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
        NaraLogDiaperButton(coordinator, "Nara Diaper Wet", pee=True, poop=False, dry=False),
        NaraLogDiaperButton(coordinator, "Nara Diaper Dirty", pee=False, poop=True, dry=False),
        NaraLogDiaperButton(coordinator, "Nara Diaper Mixed", pee=True, poop=True, dry=False),
        NaraLogDiaperButton(coordinator, "Nara Diaper Dry", pee=False, poop=False, dry=True),
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
                # If it's a ghost track (both sides paused, but no endDt), ignore it!
                if self.activity_type == "FEED":
                    left = track.get("breastLeftBeginDt")
                    right = track.get("breastRightBeginDt")
                    if not left and not right:
                        continue
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
            
        # Optimistic update
        track["endDt"] = now
        self.async_write_ha_state()

class NaraLogDiaperButton(CoordinatorEntity, ButtonEntity):
    """Button to log a specific type of diaper."""

    def __init__(self, coordinator, name, pee, poop, dry):
        super().__init__(coordinator)
        self.coordinator = coordinator
        self.pee = pee
        self.poop = poop
        self.dry = dry
        email = coordinator.api.email.lower()
        
        self._attr_name = name
        
        safe_name = name.lower().replace(" ", "_")
        self._attr_unique_id = f"nara_{email}_{safe_name}_button"
        
        if poop:
            self._attr_icon = "mdi:emoticon-poop"
        elif dry:
            self._attr_icon = "mdi:water-off"
        else:
            self._attr_icon = "mdi:water"

    async def async_press(self) -> None:
        """Handle the button press."""
        await self.hass.async_add_executor_job(
            self.coordinator.api.log_diaper,
            self.pee,
            self.poop,
            self.dry
        )
