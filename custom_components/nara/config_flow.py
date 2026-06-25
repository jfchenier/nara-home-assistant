import logging
import os
import sys
import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResult
from homeassistant.exceptions import HomeAssistantError

from .const import DOMAIN, CONF_EMAIL, CONF_PASSWORD

_LOGGER = logging.getLogger(__name__)

from .api.nara import NaraAPI

STEP_USER_DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_EMAIL): str,
        vol.Required(CONF_PASSWORD): str,
    }
)

async def validate_input(hass: HomeAssistant, data: dict[str, str]) -> dict[str, str]:
    """Validate the user input allows us to connect."""
    email = data[CONF_EMAIL]
    password = data[CONF_PASSWORD]
    
    try:
        # NaraAPI makes synchronous requests in __init__, so we must run it in an executor
        api = await hass.async_add_executor_job(
            NaraAPI, email, password
        )
    except Exception as e:
        _LOGGER.error("Failed to authenticate with Nara Baby: %s", e)
        raise InvalidAuth from e

    # Return info that you want to store in the config entry.
    return {"title": f"Nara Baby ({email})"}

class NaraConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Nara Baby Tracker."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, str] | None = None
    ) -> FlowResult:
        """Handle the initial step."""
        errors: dict[str, str] = {}
        if user_input is not None:
            # Prevent duplicate entries for the same email
            await self.async_set_unique_id(user_input[CONF_EMAIL].lower())
            self._abort_if_unique_id_configured()

            try:
                info = await validate_input(self.hass, user_input)
            except InvalidAuth:
                errors["base"] = "invalid_auth"
            except Exception:  # pylint: disable=broad-except
                _LOGGER.exception("Unexpected exception")
                errors["base"] = "unknown"
            else:
                return self.async_create_entry(title=info["title"], data=user_input)

        return self.async_show_form(
            step_id="user", data_schema=STEP_USER_DATA_SCHEMA, errors=errors
        )

class InvalidAuth(HomeAssistantError):
    """Error to indicate there is invalid auth."""
