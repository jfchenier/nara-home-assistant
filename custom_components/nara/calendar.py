import datetime
import logging

from homeassistant.components.calendar import CalendarEntity, CalendarEvent
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

async def async_setup_entry(hass, entry, async_add_entities):
    """Set up the Nara calendar platform."""
    coordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([NaraCalendarEntity(coordinator)])

class NaraCalendarEntity(CoordinatorEntity, CalendarEntity):
    """Representation of the Nara Baby Calendar."""

    def __init__(self, coordinator):
        """Initialize the calendar."""
        super().__init__(coordinator)
        email = coordinator.api.email.lower()
        self._attr_name = "Nara Baby Activities"
        self._attr_unique_id = f"nara_calendar_{email}"

    @property
    def event(self) -> CalendarEvent | None:
        """Return the next or most recent event."""
        # Get events for the last day to find the most recent one
        now = dt_util.utcnow()
        start = now - datetime.timedelta(days=1)
        events = self._get_events(start, now)
        if events:
            return events[-1]
        return None

    async def async_get_events(
        self, hass, start_date: datetime.datetime, end_date: datetime.datetime
    ) -> list[CalendarEvent]:
        """Return calendar events within a datetime range."""
        # This runs in the event loop, but _get_events is purely in-memory filtering.
        return self._get_events(start_date, end_date)

    def _get_events(self, start_date: datetime.datetime, end_date: datetime.datetime) -> list[CalendarEvent]:
        """Filter the raw tracks and return standard CalendarEvents."""
        events = []
        raw_data = self.coordinator.raw_data
        
        start_ms = start_date.timestamp() * 1000
        end_ms = end_date.timestamp() * 1000

        for key, track in raw_data.items():
            begin = track.get("beginDt", 0)
            end = track.get("endDt", begin)
            
            # Point in time events (diapers, etc.) might have begin == end
            if begin > end_ms or end < start_ms:
                continue
                
            t_type = track.get("type", "UNKNOWN")
            title = t_type.replace("_", " ").title()
            
            if t_type == "FEED":
                f_type = track.get("feedType", "")
                title = f"{f_type.title()} Feed"
            elif t_type == "DIAPER":
                pee = track.get("diaperTypePee", False)
                poop = track.get("diaperTypePoop", False)
                if pee and poop:
                    title = "Diaper (Pee & Poop)"
                elif pee:
                    title = "Diaper (Pee)"
                elif poop:
                    title = "Diaper (Poop)"

            # Convert to HA's timezone-aware UTC datetime
            start_dt = dt_util.utc_from_timestamp(begin / 1000.0)
            
            if begin == end:
                # Point in time event, give it a 15 minute duration so it shows up clearly on the calendar UI
                end_dt = start_dt + datetime.timedelta(minutes=15)
            else:
                end_dt = dt_util.utc_from_timestamp(end / 1000.0)

            events.append(CalendarEvent(
                summary=title,
                start=start_dt,
                end=end_dt,
                description=track.get("note", "")
            ))
            
        # Sort events chronologically
        events.sort(key=lambda e: e.start)
        return events
