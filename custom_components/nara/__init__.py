import asyncio
import logging
import os
import sys
import threading

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, ServiceCall

from .const import DOMAIN, CONF_EMAIL, CONF_PASSWORD, PLATFORMS, DEBOUNCE_TIME
from .coordinator import NaraDataUpdateCoordinator

_LOGGER = logging.getLogger(__name__)

from .api.nara import NaraAPI
from .api.trends import TrendsHelper

class SSEListener(threading.Thread):
    """Background thread to listen to Nara SSE stream."""
    def __init__(self, api, callback):
        super().__init__(daemon=True)
        self.api = api
        self.callback = callback

    def run(self):
        _LOGGER.debug("Starting Nara SSE stream listener...")
        try:
            self.api.stream_activities(self.callback)
        except Exception as e:
            _LOGGER.error("Nara SSE stream disconnected: %s", e)

class Debouncer:
    """Debounces rapidly firing events."""
    def __init__(self, hass: HomeAssistant, delay: float, callback):
        self.hass = hass
        self.delay = delay
        self.callback = callback
        self._task = None

    def trigger(self):
        if self._task is not None:
            self._task.cancel()
        self._task = self.hass.async_create_task(self._debounced_run())

    async def _debounced_run(self):
        try:
            await asyncio.sleep(self.delay)
            await self.callback()
        except asyncio.CancelledError:
            pass

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Nara Baby Tracker from a config entry."""
    email = entry.data[CONF_EMAIL]
    password = entry.data[CONF_PASSWORD]

    # Initialize the API and TrendsHelper in the executor
    api = await hass.async_add_executor_job(NaraAPI, email, password)
    trends_helper = await hass.async_add_executor_job(TrendsHelper, email, password)

    coordinator = NaraDataUpdateCoordinator(hass, api, trends_helper)

    # Initial data fetch
    await coordinator.async_config_entry_first_refresh()

    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = coordinator

    def _on_sse_event(activity):
        _LOGGER.debug("Received SSE event: %s", activity)
        hass.loop.call_soon_threadsafe(
            lambda: hass.async_create_task(coordinator._handle_stream_event(activity))
        )

    # Start SSE thread
    sse_thread = SSEListener(api, _on_sse_event)
    sse_thread.start()

    # Forward the setup to platforms
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # Register HA Services
    async def log_diaper(call: ServiceCall):
        await hass.async_add_executor_job(
            api.log_diaper,
            call.data.get("pee", True),
            call.data.get("poop", False),
            call.data.get("dry", False),
            call.data.get("rash", False),
            call.data.get("blowout", False),
            call.data.get("color"),
            call.data.get("texture"),
            None, # begin_dt
            call.data.get("note")
        )

    async def log_sleep(call: ServiceCall):
        await hass.async_add_executor_job(
            api.log_sleep,
            int(call.data["begin_dt"]),
            int(call.data["end_dt"]),
            note=call.data.get("note")
        )

    async def log_bottle_feed(call: ServiceCall):
        await hass.async_add_executor_job(
            api.log_bottle_feed,
            call.data.get("breast_milk", True),
            float(call.data["volume_floz"]),
            call.data.get("formula_name"),
            None, # begin_dt
            note=call.data.get("note")
        )

    async def log_breast_feed(call: ServiceCall):
        await hass.async_add_executor_job(
            api.log_breast_feed,
            call.data.get("side", "LEFT"),
            float(call.data["duration_minutes"]),
            None, # begin_dt
            note=call.data.get("note")
        )

    hass.services.async_register(DOMAIN, "log_diaper", log_diaper)
    hass.services.async_register(DOMAIN, "log_sleep", log_sleep)
    hass.services.async_register(DOMAIN, "log_bottle_feed", log_bottle_feed)
    hass.services.async_register(DOMAIN, "log_breast_feed", log_breast_feed)

    async def log_solid_feed(call: ServiceCall):
        await hass.async_add_executor_job(
            api.log_solid_feed,
            None, # begin_dt
            note=call.data.get("note")
        )

    async def log_growth(call: ServiceCall):
        await hass.async_add_executor_job(
            api.log_growth,
            call.data.get("weight_lb"),
            call.data.get("height_in"),
            call.data.get("head_in")
        )

    async def log_health(call: ServiceCall):
        await hass.async_add_executor_job(
            api.log_health,
            call.data.get("medicine_name"),
            call.data.get("temp_f")
        )

    async def log_milestone(call: ServiceCall):
        await hass.async_add_executor_job(
            api.log_milestone,
            call.data["milestone_name"]
        )

    hass.services.async_register(DOMAIN, "log_solid_feed", log_solid_feed)
    hass.services.async_register(DOMAIN, "log_growth", log_growth)
    hass.services.async_register(DOMAIN, "log_health", log_health)
    hass.services.async_register(DOMAIN, "log_milestone", log_milestone)

    return True

async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id)

    # Clean up services if no more entries exist
    if not hass.data[DOMAIN]:
        hass.services.async_remove(DOMAIN, "log_diaper")
        hass.services.async_remove(DOMAIN, "log_sleep")
        hass.services.async_remove(DOMAIN, "log_bottle_feed")
        hass.services.async_remove(DOMAIN, "log_breast_feed")
        hass.services.async_remove(DOMAIN, "log_solid_feed")
        hass.services.async_remove(DOMAIN, "log_growth")
        hass.services.async_remove(DOMAIN, "log_health")
        hass.services.async_remove(DOMAIN, "log_milestone")

    return unload_ok
