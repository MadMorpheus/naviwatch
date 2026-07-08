"""DataUpdateCoordinator for the Navimow (custom) integration.

Architektur (Details/Begruendung in dokumentation/sdk-notizen.md):
- REST-Poll (alle REST_POLL_INTERVAL) ist die Ground-Truth-Quelle UND der Watchdog-Trigger.
- MQTT-Push liefert schnellere Updates zwischen den Polls (live verifiziert: Reaktion
  innerhalb von Sekunden auf echte Zustandswechsel), ist aber rein ereignisgesteuert -
  laengeres Schweigen allein ist KEIN verlaessliches Freeze-Signal (auch bei stabilem
  Maehen 120s ganz ohne MQTT-Nachrichten live beobachtet).
- Watchdog vergleicht deshalb bei jedem REST-Poll den REST-Status mit dem zuletzt per MQTT
  bekannten Status: weichen sie ab, hat der MQTT-Kanal einen echten Zustandswechsel verpasst
  -> das ist das eigentliche Freeze-Symptom, nicht blosse Stille. Erzwingt dann Reconnect.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .api import NavimowApiClient, NavimowApiError
from .const import DOMAIN, REST_POLL_INTERVAL, WATCHDOG_RECONNECT_DEBOUNCE
from .mqtt_client import NavimowMqttClient

_LOGGER = logging.getLogger(__name__)

# Live verifiziert 2026-07-08 (siehe sdk-notizen.md) + Werte aus der HomeAss-Projekt-Historie
# der Fremd-Integration (nicht alle selbst beobachtet, aber derselbe Werteraum zu erwarten).
_RAW_STATE_MAP: dict[str, str] = {
    "isDocked": "docked",
    "isIdle": "idle",
    "isIdel": "idle",  # Tippfehler in der Segway-Firmware, live beobachtet
    "isMapping": "mowing",
    "isRunning": "mowing",
    "isPaused": "paused",
    "isDocking": "returning",
    "isLifted": "error",
    "Error": "error",
    "error": "error",
    "inSoftwareUpdate": "paused",
    "Self-Checking": "idle",
    "Self-checking": "idle",
    "Offline": "unknown",
    "offline": "unknown",
}


def _canonical_state(raw_state: Any) -> str:
    if not isinstance(raw_state, str):
        return "unknown"
    return _RAW_STATE_MAP.get(raw_state, "unknown")


def _extract_battery(status: dict[str, Any]) -> int:
    if "battery" in status:
        try:
            return int(status["battery"])
        except (TypeError, ValueError):
            return 0
    capacity_remaining = status.get("capacityRemaining")
    if isinstance(capacity_remaining, list):
        for item in capacity_remaining:
            if isinstance(item, dict) and str(item.get("unit", "")).upper() == "PERCENTAGE":
                try:
                    return int(item["rawValue"])
                except (TypeError, ValueError, KeyError):
                    continue
    return 0


@dataclass
class NavimowData:
    """Aktueller, dem Nutzer/den Entities praesentierter Zustand."""

    device_id: str
    state: str
    raw_state: str
    battery: int
    mqtt_connected: bool
    last_rest_update: datetime
    last_mqtt_update: datetime | None


class NavimowCoordinator(DataUpdateCoordinator[NavimowData]):
    """Kombiniert REST-Poll und MQTT-Push, mit Watchdog gegen den bekannten Freeze-Bug."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, api_client: NavimowApiClient) -> None:
        poll_seconds = entry.options.get("poll_interval_seconds", int(REST_POLL_INTERVAL.total_seconds()))
        super().__init__(hass, _LOGGER, name=DOMAIN, update_interval=timedelta(seconds=poll_seconds))
        self.entry = entry
        self.api = api_client
        self.device_id: str | None = None
        self.device_info_raw: dict[str, Any] = {}
        self._mqtt: NavimowMqttClient | None = None
        self._last_mqtt_update: datetime | None = None
        self._mqtt_connected = False
        self._last_watchdog_reconnect: datetime | None = None

    async def async_setup(self) -> None:
        """Geraet ermitteln und MQTT-Verbindung initial aufbauen. Vor dem ersten Refresh aufrufen."""
        try:
            devices = await self.api.async_get_devices()
        except NavimowApiError as err:
            raise ConfigEntryNotReady(f"Navimow API nicht erreichbar: {err}") from err
        if not devices:
            raise ConfigEntryNotReady("Kein Navimow-Geraet im Account gefunden")

        # Bisher nur mit einem Geraet im Account getestet (siehe CLAUDE.md) - erstes Geraet
        # verwenden, mehrere Geraete sind aktuell nicht vorgesehen.
        self.device_info_raw = devices[0]
        self.device_id = devices[0]["id"]

        self._mqtt = NavimowMqttClient(
            loop=self.hass.loop,
            on_message=self._handle_mqtt_message,
            on_connection_changed=self._handle_mqtt_connection_changed,
        )
        await self._async_connect_mqtt()

    async def _async_connect_mqtt(self) -> None:
        assert self._mqtt is not None
        mqtt_info = await self.api.async_get_mqtt_user_info()
        self._mqtt.configure(
            mqtt_host=mqtt_info.get("mqttHost", ""),
            mqtt_url=mqtt_info.get("mqttUrl", ""),
            username=mqtt_info.get("userName"),
            password=mqtt_info.get("pwdInfo"),
            access_token=self.api.access_token,
            device_ids=[self.device_id] if self.device_id else [],
        )
        self._mqtt.connect()

    def _handle_mqtt_connection_changed(self, connected: bool) -> None:
        self._mqtt_connected = connected
        if self.data is not None:
            self.async_set_updated_data(replace(self.data, mqtt_connected=connected))
        if not connected:
            # userName/pwdInfo sind an den OAuth-Token gebunden, nicht account-stabil (durch
            # Gegenlesen von NavimowHAs echtem __init__.py bestaetigt: dort explizit noetig,
            # um CODE_OAUTH_INFO_ILLEGAL beim Reconnect nach Token-Rotation zu vermeiden).
            # Deshalb bei jedem Disconnect frisch abrufen, nicht nur den Token durchreichen.
            self.hass.async_create_task(self._async_refresh_mqtt_credentials())

    async def _async_refresh_mqtt_credentials(self) -> None:
        if self._mqtt is None:
            return
        try:
            mqtt_info = await self.api.async_get_mqtt_user_info()
        except NavimowApiError as err:
            _LOGGER.warning("Navimow: MQTT-Zugangsdaten konnten nicht aufgefrischt werden: %s", err)
            return
        self._mqtt.update_credentials(
            username=mqtt_info.get("userName"),
            password=mqtt_info.get("pwdInfo"),
            access_token=self.api.access_token,
        )

    def _handle_mqtt_message(self, topic: str, payload: dict[str, Any]) -> None:
        if self.device_id and payload.get("device_id") != self.device_id:
            return
        channel = topic.rsplit("/", 1)[-1]
        if channel != "state":
            # event/attributes: in ueber 4 Minuten Live-Test (Dock + aktives Maehen) nie
            # beobachtet (siehe sdk-notizen.md) - trotzdem geloggt fuer spaetere Auswertung.
            _LOGGER.debug("Navimow MQTT %s payload: %s", channel, payload)
            return

        now = dt_util.utcnow()
        self._last_mqtt_update = now
        current = self.data
        raw_state = payload.get("state")
        battery = payload.get("battery")

        new_data = NavimowData(
            device_id=self.device_id or "",
            state=_canonical_state(raw_state),
            raw_state=str(raw_state),
            battery=battery if battery is not None else (current.battery if current else 0),
            mqtt_connected=self._mqtt_connected,
            last_rest_update=current.last_rest_update if current else now,
            last_mqtt_update=now,
        )
        self.async_set_updated_data(new_data)

    async def _async_update_data(self) -> NavimowData:
        if not self.device_id:
            raise UpdateFailed("Kein Navimow-Geraet konfiguriert")

        try:
            statuses = await self.api.async_get_vehicle_status([self.device_id])
        except NavimowApiError as err:
            raise UpdateFailed(f"Navimow API-Fehler: {err}") from err
        if not statuses:
            raise UpdateFailed("Navimow lieferte keinen Geraetestatus")

        now = dt_util.utcnow()
        status = statuses[0]
        raw_state = status.get("vehicleState", "unknown")
        canonical = _canonical_state(raw_state)
        battery = _extract_battery(status)

        current = self.data
        if current is not None and current.state != canonical and self._mqtt is not None:
            since_last_reconnect = (
                now - self._last_watchdog_reconnect if self._last_watchdog_reconnect else None
            )
            if since_last_reconnect is not None and since_last_reconnect < WATCHDOG_RECONNECT_DEBOUNCE:
                _LOGGER.debug(
                    "Navimow Watchdog: Mismatch REST '%s' vs. MQTT '%s' besteht weiter, "
                    "letzter erzwungener Reconnect ist erst %s her - uebersprungen (Debounce).",
                    canonical,
                    current.state,
                    since_last_reconnect,
                )
            else:
                _LOGGER.warning(
                    "Navimow Watchdog: REST-Status '%s' weicht vom zuletzt per MQTT bekannten "
                    "Status '%s' ab - MQTT hat einen Zustandswechsel verpasst, erzwinge Reconnect.",
                    canonical,
                    current.state,
                )
                self._mqtt.force_reconnect()
                self._last_watchdog_reconnect = now
        else:
            # Mismatch aufgeloest (oder erster Poll ueberhaupt) - Debounce-Fenster zuruecksetzen,
            # damit ein kuenftiger, neuer Mismatch sofort wieder einen Reconnect ausloesen kann.
            self._last_watchdog_reconnect = None

        # Access-Token rotiert stuendlich - bei jedem Poll an den MQTT-Client durchreichen,
        # kein separates Refresh-Scheduling noetig (Poll-Intervall ist deutlich kuerzer als
        # die Token-Lebensdauer).
        if self._mqtt is not None:
            self._mqtt.update_credentials(access_token=self.api.access_token)

        return NavimowData(
            device_id=self.device_id,
            state=canonical,
            raw_state=str(raw_state),
            battery=battery,
            mqtt_connected=self._mqtt_connected,
            last_rest_update=now,
            last_mqtt_update=self._last_mqtt_update,
        )

    async def async_shutdown(self) -> None:
        if self._mqtt is not None:
            self._mqtt.disconnect()
        await super().async_shutdown()

    async def async_send_command(self, action: str) -> None:
        """Kommando senden und danach zeitnah einen REST-Poll erzwingen (schnelles Feedback).

        Kurze Gnadenfrist vor dem erzwungenen Poll: MQTT reagiert live nachweislich innerhalb
        von Sekunden auf echte Zustandswechsel. Ohne diese Frist wuerde der sofortige
        Ausserplan-Poll fast immer einen Watchdog-Fehlalarm ausloesen (REST zeigt den neuen
        Zustand, bevor MQTT ihn nachgeliefert hat) und einen unnoetigen Reconnect erzwingen.
        """
        if not self.device_id:
            return
        method = getattr(self.api, action)
        try:
            await method(self.device_id)
        except NavimowApiError as err:
            raise UpdateFailed(f"Navimow-Kommando '{action}' fehlgeschlagen: {err}") from err
        await asyncio.sleep(5)
        await self.async_request_refresh()
