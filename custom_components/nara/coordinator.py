import logging
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

class NaraDataUpdateCoordinator(DataUpdateCoordinator):
    """Class to manage fetching Nara data from the API."""

    def __init__(self, hass, api, trends_helper):
        """Initialize."""
        self.api = api
        self.trends_helper = trends_helper
        self.raw_data = {}
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=None, # Update is handled via SSE push
        )

    async def _handle_stream_event(self, track_data):
        """Handle incoming real-time update from Firebase."""
        if not track_data:
            return
            
        track_id = track_data.get("key")
        if not track_id:
            return
            
        _LOGGER.debug(f"Received real-time update for track {track_id}")
        
        # Merge partial updates into existing track
        if track_data.get("_deleted"):
            if track_id in self.raw_data:
                del self.raw_data[track_id]
        elif track_data.get("_replace"):
            track_data.pop("_replace", None)
            self.raw_data[track_id] = track_data
        elif track_id in self.raw_data:
            self.raw_data[track_id].update(track_data)
        else:
            if "type" not in track_data:
                # We can't use an unknown orphan partial track
                return
            self.raw_data[track_id] = track_data
            
        # Trigger an update to all entities
        self.hass.add_job(self.async_set_updated_data, self.data)

    async def _async_update_data(self):
        """Fetch data from Nara API."""
        try:
            def fetch():
                import logging
                _LOGGER.warning("Fetching trends...")
                trends = self.trends_helper.get_trends()
                _LOGGER.warning("Fetching raw data...")
                self.raw_data = self.api.get_data()
                _LOGGER.warning("Fetch complete!")
                return trends
                
            return await self.hass.async_add_executor_job(fetch)
        except Exception as err:
            raise UpdateFailed(f"Error communicating with API: {err}")
