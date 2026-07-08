"""The Navimow (custom) integration."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_entry_oauth2_flow

from .api import NavimowApiClient
from .auth import NavimowOAuth2Implementation
from .const import DOMAIN
from .coordinator import NavimowCoordinator

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [Platform.LAWN_MOWER, Platform.SENSOR, Platform.BINARY_SENSOR]


async def async_setup(hass: HomeAssistant, config: dict[str, Any]) -> bool:
    """Komponenten-Setup: OAuth2-Implementierung registrieren.

    Muss bei JEDEM HA-Start passieren, nicht nur waehrend des Config-Flows - die
    Registrierung in config_entry_oauth2_flow lebt nur im Arbeitsspeicher der laufenden
    HA-Instanz. Ohne diese Funktion wuerde async_get_config_entry_implementation() in
    async_setup_entry() nach jedem Neustart fehlschlagen (verifiziert gegen NavimowHAs
    echtes, produktiv laufendes __init__.py - dort exakt so geloest).
    """
    config_entry_oauth2_flow.async_register_implementation(
        hass, DOMAIN, NavimowOAuth2Implementation(hass)
    )
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    implementation = await config_entry_oauth2_flow.async_get_config_entry_implementation(hass, entry)
    oauth_session = config_entry_oauth2_flow.OAuth2Session(hass, entry, implementation)
    api_client = NavimowApiClient(oauth_session)

    coordinator = NavimowCoordinator(hass, entry, api_client)
    await coordinator.async_setup()
    await coordinator.async_config_entry_first_refresh()

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        coordinator: NavimowCoordinator = hass.data[DOMAIN].pop(entry.entry_id)
        await coordinator.async_shutdown()
    return unload_ok


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Options (z.B. Poll-Intervall) geaendert -> Entry neu laden."""
    await hass.config_entries.async_reload(entry.entry_id)
