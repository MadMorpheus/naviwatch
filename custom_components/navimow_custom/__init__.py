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
    try:
        await coordinator.async_config_entry_first_refresh()
    except Exception:
        # async_setup() hat bereits einen verbundenen MQTT-Client gestartet (eigener
        # Hintergrund-Thread). Schlaegt der erste Refresh fehl (typischerweise
        # ConfigEntryNotReady), bricht async_setup_entry() hier ab, BEVOR der Coordinator
        # unten in hass.data landet - ohne dieses explizite Shutdown wuerde niemand je
        # disconnect() auf diesem MQTT-Client aufrufen. HAs automatischer Setup-Retry baut
        # dann bei jedem Versuch einen weiteren, ebenfalls verbundenen Client, waehrend die
        # alten als Zombies weiterlaufen - live beobachtet als sich aufschaukelnder
        # Reconnect-Sturm mit wachsender Zahl gleichzeitiger MQTT-Verbindungen (2026-07-24).
        await coordinator.async_shutdown()
        raise

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # Der Update-Listener feuert bei JEDER Aenderung am Entry, nicht nur bei Options-
    # Aenderungen - auch wenn OAuth2Session den stuendlich rotierten Token in entry.data
    # zurueckschreibt. Ohne diesen Vergleich wurde die Integration dadurch jede Stunde
    # komplett neu geladen (live beobachtet 2026-10-13: alle Entitaeten ~1 s unavailable,
    # Zone/Fortschritt danach minutenlang unknown, jedes Mal ein neuer MQTT-Client).
    loaded_options = dict(entry.options)

    async def _async_update_listener(hass: HomeAssistant, updated_entry: ConfigEntry) -> None:
        """Options (z.B. Poll-Intervall) geaendert -> Entry neu laden."""
        if dict(updated_entry.options) == loaded_options:
            return
        await hass.config_entries.async_reload(updated_entry.entry_id)

    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        coordinator: NavimowCoordinator = hass.data[DOMAIN].pop(entry.entry_id)
        await coordinator.async_shutdown()
    return unload_ok
