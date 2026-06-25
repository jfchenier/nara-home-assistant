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

    async def _async_update_data(self):
        """Fetch data from Nara API."""
        try:
            def fetch():
                trends = self.trends_helper.get_trends()
                self.raw_data = self.api.get_data()
                return trends
                
            return await self.hass.async_add_executor_job(fetch)
        except Exception as err:
            raise UpdateFailed(f"Error communicating with API: {err}")
