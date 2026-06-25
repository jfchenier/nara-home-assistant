"""Constants for the Nara Baby Tracker integration."""

DOMAIN = "nara"
CONF_EMAIL = "email"
CONF_PASSWORD = "password"

# Update interval is not used for polling since we use SSE,
# but we can provide a debounce time for fetching trends.
DEBOUNCE_TIME = 5

PLATFORMS = ["sensor", "calendar", "binary_sensor", "switch", "button"]
