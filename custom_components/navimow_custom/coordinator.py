"""DataUpdateCoordinator for the Navimow (custom) integration.

Multi-Geraete-Rewrite: Grundgeruest (dict[device_id, NavimowData], gemeinsamer REST-Poll/
MQTT-Client fuer alle Geraete eines Accounts) von github.com/klarah32 zur Verfuegung
gestellt, hier uebernommen und in einem Punkt angepasst - siehe Command-Verification unten
(siehe CLAUDE.md-Analyse vom 2026-07-25/26). Frueher wurde in
async_setup() nur devices[0] verwendet - bei instabiler API-Reihenfolge konnte das bei
jedem Neustart ein anderes Geraet auswaehlen und verwaiste "Geister"-Devices in der
HA-Registry hinterlassen (live beobachtet: "Eltern", "Gerd" und "Navimow H800" gleichzeitig
in der Registry, aber nur eines davon tatsaechlich aktualisiert).

Jetzt verwaltet EIN Coordinator ALLE Geraete des Accounts gemeinsam:
- self.data ist dict[device_id, NavimowData] statt eines einzelnen NavimowData.
- Ein REST-Poll pro Zyklus fuer alle Geraete (async_get_vehicle_status akzeptiert bereits
  eine Geraeteliste - dafuer musste api.py nicht geaendert werden).
- Ein gemeinsamer MQTT-Client, der auf alle Geraete-IDs abonniert (mqtt_client.py hat das
  bereits unterstuetzt, siehe _subscribe_all - nur der Coordinator hat bisher nie mehr als
  eine ID durchgereicht).
- Nachrichten-Routing anhand der device_id aus dem MQTT-Topic, damit jedes Geraet nur seine
  eigenen Daten bekommt.

Architektur-Grundlagen (REST-Poll als Ground Truth + Watchdog) unveraendert gegenueber der
Einzel-Geraet-Version, jetzt nur pro device_id statt global:
- REST-Poll (alle REST_POLL_INTERVAL) ist die Ground-Truth-Quelle UND der Watchdog-Trigger.
- MQTT-Push liefert schnellere Updates zwischen den Polls (live verifiziert: Reaktion
  innerhalb von Sekunden auf echte Zustandswechsel), ist aber rein ereignisgesteuert -
  laengeres Schweigen allein ist KEIN verlaessliches Freeze-Signal (auch bei stabilem
  Maehen 120s ganz ohne MQTT-Nachrichten live beobachtet).
- Watchdog vergleicht deshalb bei jedem REST-Poll pro Geraet den REST-Status mit dem
  zuletzt per MQTT bekannten Status: weichen sie ab, hat der MQTT-Kanal einen echten
  Zustandswechsel verpasst -> das ist das eigentliche Freeze-Symptom, nicht blosse Stille.
  Erzwingt dann EINEN gemeinsamen Reconnect (der MQTT-Client ist fuer alle Geraete
  gemeinsam - ein Reconnect pro betroffenem Geraet waere redundant).

Command-Verification (siehe COMMAND_VERIFICATION_SPECS in const.py) war in der von
github.com/klarah32 gelieferten Fassung komplett entfernt, ohne das zu erwaehnen (Review
2026-07-27, siehe CLAUDE.md) - das ist die eine Anpassung gegenueber der Vorlage: hier
bewusst wiederhergestellt, jetzt pro device_id statt global (last_command_result ist ein
dict[device_id, ...]). Live gegen den echten Mäher re-verifiziert am 2026-07-27.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .api import NavimowApiClient, NavimowApiError
from .const import (
    COMMAND_VERIFICATION_SPECS,
    COORDINATOR_UPDATE_TIMEOUT,
    DOMAIN,
    REST_POLL_INTERVAL,
    WATCHDOG_RECONNECT_DEBOUNCE,
)
from .location import parse_location_payload
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


def _status_device_id(status: dict[str, Any]) -> str | None:
    """Geraete-ID aus einem einzelnen Eintrag der getVehicleStatus-Antwort.

    "id" ist keine reine Vermutung: der live mitgeschnittene Einzelgeraet-Response
    (dokumentation/sdk-notizen.md) zeigt bereits dieses Feld ("id": "3KCAA2611K0819").
    "deviceId" bleibt als Fallback, falls ein Mehrgeraete-Response davon abweicht - noch
    nicht gegen einen echten Mehrgeraete-Account verifiziert. Falls die Antwort ein anderes
    Feld nutzt, hilft das Debug-Log unten beim Live-Abgleich.
    """
    device_id = status.get("id") or status.get("deviceId")
    return str(device_id) if device_id is not None else None


@dataclass
class NavimowData:
    """Aktueller, dem Nutzer/den Entities praesentierter Zustand - EINES Maehers."""

    device_id: str
    state: str
    raw_state: str
    battery: int
    mqtt_connected: bool
    last_rest_update: datetime
    last_mqtt_update: datetime | None
    # Ueber den undokumentierten "location"-Kanal (siehe location.py) - noch nicht live
    # verifiziert, daher alle optional/None solange keine Nachricht empfangen wurde.
    pos_x: float | None = None
    pos_y: float | None = None
    pos_theta: float | None = None
    zone: int | None = None
    target_zone: int | None = None
    mow_progress_pct: int | None = None
    task_delay: bool | None = None


class NavimowCoordinator(DataUpdateCoordinator[dict[str, NavimowData]]):
    """Kombiniert REST-Poll und MQTT-Push fuer ALLE Maeher eines Accounts gemeinsam.

    self.data: dict[device_id, NavimowData]. Ein Watchdog-Reconnect (siehe
    _async_update_data_impl) betrifft immer den gesamten gemeinsamen MQTT-Client, auch
    wenn nur ein einzelnes Geraet einen Mismatch zeigt.
    """

    # Mindestabstand zwischen zwei MQTT-Zugangsdaten-Refreshes; der Server antwortet
    # bei Ueberlast mit "Request too frequent. Please retry after 1 minute."
    _MQTT_CRED_COOLDOWN = 60.0

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, api_client: NavimowApiClient) -> None:
        poll_seconds = entry.options.get("poll_interval_seconds", int(REST_POLL_INTERVAL.total_seconds()))
        super().__init__(hass, _LOGGER, name=DOMAIN, update_interval=timedelta(seconds=poll_seconds))
        self.entry = entry
        self.api = api_client
        self.device_ids: list[str] = []
        self._devices_info_raw: dict[str, dict[str, Any]] = {}
        self._mqtt: NavimowMqttClient | None = None
        self._last_mqtt_update: dict[str, datetime] = {}
        self._mqtt_connected = False
        self._last_watchdog_reconnect: dict[str, datetime] = {}
        # Pro Geraet, nicht mehr global - jedes Geraet kann unabhaengig ein eigenes
        # Kommando bekommen und braucht daher sein eigenes Verifikationsergebnis.
        self.last_command_result: dict[str, dict[str, Any]] = {}
        self._mqtt_cred_lock = asyncio.Lock()
        self._mqtt_cred_last_attempt = 0.0

    def device_info_raw(self, device_id: str) -> dict[str, Any]:
        """Rohe Account-Metadaten (name/model/firmware) fuer EIN Geraet - fuer entity.py."""
        return self._devices_info_raw.get(device_id, {})

    async def async_setup(self) -> None:
        """Alle Geraete ermitteln und EINEN gemeinsamen MQTT-Client fuer alle aufbauen.

        Vor dem ersten Refresh aufrufen.
        """
        try:
            devices = await self.api.async_get_devices()
        except NavimowApiError as err:
            raise ConfigEntryNotReady(f"Navimow API nicht erreichbar: {err}") from err
        if not devices:
            raise ConfigEntryNotReady("Kein Navimow-Geraet im Account gefunden")

        self._devices_info_raw = {str(d["id"]): d for d in devices}
        self.device_ids = list(self._devices_info_raw.keys())
        _LOGGER.debug("Navimow: %d Geraet(e) im Account gefunden: %s", len(self.device_ids), self.device_ids)

        self._mqtt = NavimowMqttClient(
            loop=self.hass.loop,
            on_message=self._handle_mqtt_message,
            on_connection_changed=self._handle_mqtt_connection_changed,
        )
        try:
            await self._async_connect_mqtt()
        except NavimowApiError as err:
            # Bei der stuendlichen Token-Rotation laedt der Entry neu und holt sofort
            # neue MQTT-Zugangsdaten; Segway rate-limitet diesen Burst
            # ("Request too frequent. Please retry after 1 minute."). Ohne
            # ConfigEntryNotReady wertet Home Assistant das als endgueltigen
            # Setup-Fehler OHNE Retry - die Integration bleibt tot, bis jemand
            # manuell neu laedt. Der Aufruf direkt darueber (async_get_devices)
            # ist bereits genauso abgesichert.
            raise ConfigEntryNotReady(f"MQTT-Zugangsdaten nicht abrufbar: {err}") from err

    async def _async_connect_mqtt(self) -> None:
        assert self._mqtt is not None
        mqtt_info = await self.api.async_get_mqtt_user_info()
        self._mqtt.configure(
            mqtt_host=mqtt_info.get("mqttHost", ""),
            mqtt_url=mqtt_info.get("mqttUrl", ""),
            username=mqtt_info.get("userName"),
            password=mqtt_info.get("pwdInfo"),
            access_token=self.api.access_token,
            device_ids=self.device_ids,
        )
        await self._mqtt.connect()

    def _push_device_data(self, device_id: str, new_data: NavimowData) -> None:
        """Entities EINES Geraets ueber neue Push-Daten informieren, OHNE den REST-Poll-
        Zeitplan zu beeinflussen. async_set_updated_data() wuerde das bei jedem Aufruf tun
        (setzt den naechsten geplanten Poll auf update_interval ab JETZT zurueck) - live
        beobachtet 2026-07-09: bei den alle ~2s eintreffenden "location"-Nachrichten waehrend
        aktivem Maehen verhungerte der REST-Poll dadurch komplett. Gilt jetzt erst recht, da
        JEDES der N Geraete waehrend des Maehens eigene location-Nachrichten schickt.
        """
        current = dict(self.data or {})
        current[device_id] = new_data
        self.data = current
        self.async_update_listeners()

    def _handle_mqtt_connection_changed(self, connected: bool) -> None:
        self._mqtt_connected = connected
        if self.data:
            # Der MQTT-Client ist fuer alle Geraete gemeinsam - ein Verbindungswechsel
            # betrifft daher gleichzeitig alle bekannten Geraete, nicht nur eines.
            updated = {
                device_id: replace(data, mqtt_connected=connected) for device_id, data in self.data.items()
            }
            self.data = updated
            self.async_update_listeners()
        if not connected:
            # userName/pwdInfo sind an den OAuth-Token gebunden, nicht account-stabil (durch
            # Gegenlesen von NavimowHAs echtem __init__.py bestaetigt: dort explizit noetig,
            # um CODE_OAUTH_INFO_ILLEGAL beim Reconnect nach Token-Rotation zu vermeiden).
            # Deshalb bei jedem Disconnect frisch abrufen, nicht nur den Token durchreichen.
            self.hass.async_create_task(self._async_refresh_mqtt_credentials())

    async def _async_refresh_mqtt_credentials(self) -> None:
        if self._mqtt is None:
            return
        # Jeder Disconnect stoesst ueber _handle_mqtt_connection_changed einen eigenen
        # async_create_task an. Ohne Single-Flight-Sperre und Cooldown entsteht bei
        # rate-limitiertem Endpoint eine sich selbst erhaltende Schleife: Refresh
        # scheitert -> Client behaelt die ALTEN Zugangsdaten -> naechster Disconnect
        # -> naechster Refresh. Live beobachtet 2026-08-18: 36 Versuche im Abstand von
        # ~1,6 s, wodurch gerade die Retries das Rate-Limit aufrecht hielten.
        if self._mqtt_cred_lock.locked():
            return
        async with self._mqtt_cred_lock:
            elapsed = time.monotonic() - self._mqtt_cred_last_attempt
            if elapsed < self._MQTT_CRED_COOLDOWN:
                _LOGGER.debug(
                    "Navimow: MQTT-Zugangsdaten-Refresh uebersprungen (%.0fs seit letztem Versuch)",
                    elapsed,
                )
                return
            self._mqtt_cred_last_attempt = time.monotonic()
            try:
                mqtt_info = await self.api.async_get_mqtt_user_info()
            except NavimowApiError as err:
                _LOGGER.warning("Navimow: MQTT-Zugangsdaten konnten nicht aufgefrischt werden: %s", err)
                return
        await self._mqtt.update_credentials(
            username=mqtt_info.get("userName"),
            password=mqtt_info.get("pwdInfo"),
            access_token=self.api.access_token,
        )

    def _handle_mqtt_message(self, topic: str, payload: Any, device_id: str) -> None:
        # Frueher: Vergleich gegen das EINE bekannte self.device_id, alles andere verworfen.
        # Jetzt: jede bekannte device_id wird durchgelassen, unbekannte (z.B. ein Geraet,
        # das erst NACH async_setup() zum Account hinzugefuegt wurde) weiterhin verworfen,
        # bis zum naechsten Neustart/Reload.
        if device_id not in self._devices_info_raw:
            return
        channel = topic.rsplit("/", 1)[-1]

        if channel == "location":
            self._handle_location_message(device_id, payload)
            return

        if channel != "state":
            # event/attributes: in ueber 4 Minuten Live-Test (Dock + aktives Maehen) nie
            # beobachtet (siehe sdk-notizen.md) - trotzdem geloggt fuer spaetere Auswertung.
            _LOGGER.debug("Navimow MQTT %s payload (Geraet %s): %s", channel, device_id, payload)
            return

        now = dt_util.utcnow()
        self._last_mqtt_update[device_id] = now
        current = (self.data or {}).get(device_id)
        raw_state = payload.get("state")
        battery = payload.get("battery")

        if current is None:
            new_data = NavimowData(
                device_id=device_id,
                state=_canonical_state(raw_state),
                raw_state=str(raw_state),
                battery=battery if battery is not None else 0,
                mqtt_connected=self._mqtt_connected,
                last_rest_update=now,
                last_mqtt_update=now,
            )
        else:
            # replace() statt Neubau, damit per "location"-Kanal bekannte Position/Zone
            # (siehe _handle_location_message) hier nicht verworfen werden.
            new_data = replace(
                current,
                state=_canonical_state(raw_state),
                raw_state=str(raw_state),
                battery=battery if battery is not None else current.battery,
                mqtt_connected=self._mqtt_connected,
                last_mqtt_update=now,
            )
        self._push_device_data(device_id, new_data)

    def _handle_location_message(self, device_id: str, payload: Any) -> None:
        """Undokumentierter 'location'-Kanal, siehe location.py - noch nicht live verifiziert."""
        update = parse_location_payload(payload)
        if update is None:
            return
        current = (self.data or {}).get(device_id)
        if current is None:
            # Vor dem ersten REST-Poll gibt es noch kein NavimowData zum Mergen fuer DIESES
            # Geraet - seltener Fall, wird beim naechsten Poll/State-Update nachgeholt.
            return
        self._push_device_data(
            device_id,
            replace(
                current,
                pos_x=update.pos_x if update.pos_x is not None else current.pos_x,
                pos_y=update.pos_y if update.pos_y is not None else current.pos_y,
                pos_theta=update.pos_theta if update.pos_theta is not None else current.pos_theta,
                zone=update.zone if update.zone is not None else current.zone,
                target_zone=update.target_zone if update.target_zone is not None else current.target_zone,
                mow_progress_pct=(
                    update.mow_progress_pct
                    if update.mow_progress_pct is not None
                    else current.mow_progress_pct
                ),
                task_delay=update.task_delay if update.task_delay is not None else current.task_delay,
            ),
        )

    async def _async_update_data(self) -> dict[str, NavimowData]:
        # Generelles Zeitlimit um den GESAMTEN Zyklus (REST-Call fuer ALLE Geraete + ggf.
        # Watchdog-Reconnect + Credential-Refresh) - live beobachtet, dass dieser trotz
        # Einzel-Timeouts (siehe api.py) noch dauerhaft haengen blieb. Damit bekommt der
        # Coordinator garantiert nach spaetestens COORDINATOR_UPDATE_TIMEOUT ein Ergebnis
        # (Erfolg oder Fehler), egal was im Detail haengt - kein dauerhaftes Einfrieren mehr
        # moeglich, auch nicht bei N Geraeten in einem Zyklus.
        try:
            async with asyncio.timeout(COORDINATOR_UPDATE_TIMEOUT):
                return await self._async_update_data_impl()
        except TimeoutError as err:
            raise UpdateFailed(
                f"Navimow-Update haengt seit ueber {COORDINATOR_UPDATE_TIMEOUT}s fest, abgebrochen"
            ) from err

    async def _async_update_data_impl(self) -> dict[str, NavimowData]:
        if not self.device_ids:
            raise UpdateFailed("Kein Navimow-Geraet konfiguriert")

        try:
            # EIN REST-Call fuer ALLE Geraete - async_get_vehicle_status hat eine Geraeteliste
            # schon immer akzeptiert, dafuer war KEINE Aenderung an api.py noetig.
            statuses = await self.api.async_get_vehicle_status(self.device_ids)
        except NavimowApiError as err:
            raise UpdateFailed(f"Navimow API-Fehler: {err}") from err
        if not statuses:
            raise UpdateFailed("Navimow lieferte keinen Geraetestatus")

        now = dt_util.utcnow()
        current_all = self.data or {}
        updated: dict[str, NavimowData] = dict(current_all)
        mismatch_detected = False

        for status in statuses:
            device_id = _status_device_id(status)
            if device_id is None or device_id not in self._devices_info_raw:
                _LOGGER.debug(
                    "Navimow: Status-Eintrag ohne zuordenbare device_id uebersprungen: %s", status
                )
                continue

            raw_state = status.get("vehicleState", "unknown")
            canonical = _canonical_state(raw_state)
            battery = _extract_battery(status)

            current = current_all.get(device_id)
            if current is not None and current.state != canonical:
                last_reconnect = self._last_watchdog_reconnect.get(device_id)
                since_last_reconnect = now - last_reconnect if last_reconnect else None
                if since_last_reconnect is not None and since_last_reconnect < WATCHDOG_RECONNECT_DEBOUNCE:
                    _LOGGER.debug(
                        "Navimow Watchdog (%s): Mismatch REST '%s' vs. MQTT '%s' besteht weiter, "
                        "letzter erzwungener Reconnect ist erst %s her - uebersprungen (Debounce).",
                        device_id,
                        canonical,
                        current.state,
                        since_last_reconnect,
                    )
                else:
                    _LOGGER.warning(
                        "Navimow Watchdog (%s): REST-Status '%s' weicht vom zuletzt per MQTT "
                        "bekannten Status '%s' ab - MQTT hat einen Zustandswechsel verpasst.",
                        device_id,
                        canonical,
                        current.state,
                    )
                    mismatch_detected = True
                    self._last_watchdog_reconnect[device_id] = now
            elif current is not None:
                # Mismatch fuer DIESES Geraet aufgeloest - dessen Debounce-Fenster zuruecksetzen,
                # damit ein kuenftiger, neuer Mismatch bei ihm sofort wieder greift.
                self._last_watchdog_reconnect.pop(device_id, None)

            if current is None:
                updated[device_id] = NavimowData(
                    device_id=device_id,
                    state=canonical,
                    raw_state=str(raw_state),
                    battery=battery,
                    mqtt_connected=self._mqtt_connected,
                    last_rest_update=now,
                    last_mqtt_update=self._last_mqtt_update.get(device_id),
                )
            else:
                # replace() statt Neubau, damit per "location"-Kanal bekannte Position/Zone
                # durch den REST-Poll nicht auf None zurueckgesetzt werden.
                updated[device_id] = replace(
                    current,
                    device_id=device_id,
                    state=canonical,
                    raw_state=str(raw_state),
                    battery=battery,
                    mqtt_connected=self._mqtt_connected,
                    last_rest_update=now,
                    last_mqtt_update=self._last_mqtt_update.get(device_id),
                )

        # EIN gemeinsamer Reconnect fuer ALLE in diesem Zyklus erkannten Mismatches - der
        # MQTT-Client ist fuer alle Geraete gemeinsam, ein Reconnect pro betroffenem Geraet
        # waere redundant (und der zweite wuerde durch den internen _connect_lock in
        # mqtt_client.py ohnehin nur auf den ersten warten).
        if mismatch_detected and self._mqtt is not None:
            await self._mqtt.force_reconnect()

        # Access-Token rotiert stuendlich - bei jedem Poll an den MQTT-Client durchreichen,
        # kein separates Refresh-Scheduling noetig (Poll-Intervall ist deutlich kuerzer als
        # die Token-Lebensdauer). Account-weit, nicht pro Geraet.
        if self._mqtt is not None:
            await self._mqtt.update_credentials(access_token=self.api.access_token)

        return updated

    async def async_shutdown(self) -> None:
        if self._mqtt is not None:
            await self._mqtt.disconnect()
        await super().async_shutdown()

    async def async_send_command(self, device_id: str, action: str) -> None:
        """Kommando an EIN bestimmtes Geraet senden (einmal, kein Retry) und danach das
        Ergebnis fuer GENAU dieses Geraet verifizieren.

        Wiederhergestellt nach dem Multi-Geraete-Umbau (siehe CLAUDE.md, Review
        2026-07-27) - war dort versehentlich komplett entfernt worden. Siehe
        COMMAND_VERIFICATION_SPECS in const.py fuer die Begruendung/Herkunft (inspiriert
        von doctee/symcon-navimow).
        """
        if device_id not in self._devices_info_raw:
            raise UpdateFailed(f"Unbekanntes Navimow-Geraet: {device_id}")
        method = getattr(self.api, action)
        try:
            await method(device_id)
        except NavimowApiError as err:
            raise UpdateFailed(f"Navimow-Kommando '{action}' fuer {device_id} fehlgeschlagen: {err}") from err

        spec = COMMAND_VERIFICATION_SPECS[action]
        if spec["background"]:
            # Dock: bis zu 15 Min Budget, Service-Call soll dafuer nicht blockieren. Geht bei
            # einem HA-Neustart mitten in der Verifikation verloren, das ist unschaedlich
            # (restart-safe wie bei symcon): kein Kommando-Replay noetig, der naechste normale
            # REST-Poll zeigt den echten Zustand ohnehin.
            self.hass.async_create_task(self._async_verify_command(device_id, action, spec))
        else:
            await self._async_verify_command(device_id, action, spec)

    async def _async_verify_command(self, device_id: str, action: str, spec: dict[str, Any]) -> None:
        """Nach einem Kommando pollen, bis der Zielzustand fuer DIESES Geraet erreicht ist
        oder das Zeitbudget auslaeuft. Ohne das kehrte der Service-Call bisher nach einem
        einzigen Poll zurueck, unabhaengig vom tatsaechlichen Ergebnis - ein von der Cloud
        angenommenes, aber vom Maeher aus irgendeinem Grund (Hindernis, Funkloch) nicht
        umgesetztes Kommando waere unbemerkt geblieben.
        """
        deadline = time.monotonic() + spec["timeout"]
        await asyncio.sleep(spec["initial_delay"])
        while True:
            await self.async_request_refresh()
            data = (self.data or {}).get(device_id)
            state = data.state if data is not None else None
            if state in spec["target_states"]:
                self._set_command_result(device_id, action, "verified", state)
                return
            if time.monotonic() >= deadline:
                self._set_command_result(device_id, action, "timeout", state)
                _LOGGER.warning(
                    "Navimow (%s): Verifikation von '%s' nach %ss ohne Zielzustand abgebrochen "
                    "(letzter bekannter Zustand: '%s') - Kommando wurde von der Cloud "
                    "angenommen, aber nicht bestaetigt.",
                    device_id,
                    action,
                    spec["timeout"],
                    state,
                )
                return
            await asyncio.sleep(spec["poll_interval"])

    def _set_command_result(self, device_id: str, action: str, result: str, state: str | None) -> None:
        self.last_command_result[device_id] = {
            "action": action,
            "result": result,
            "state": state,
            "at": dt_util.utcnow().isoformat(),
        }
        if self.data:
            self.async_update_listeners()
