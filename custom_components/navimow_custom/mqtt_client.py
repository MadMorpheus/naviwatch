"""MQTT (WSS) client for Navimow real-time updates.

Baut auf dem Ansatz von sdk-reference/mower_sdk/sdk.py (NavimowSDK) auf, NICHT auf
mower_sdk/cloud.py - letzteres hat einen Topic-Parsing-Bug (erwartet 'navimow/{id}/{channel}',
tatsaechlich genutzt wird '/downlink/vehicle/{id}/realtimeDate/{channel}'), der echte
Nachrichten nie an Callbacks weiterleiten wuerde. Details: dokumentation/sdk-notizen.md.
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from collections.abc import Callable
from typing import Any
from urllib.parse import urlparse

from paho.mqtt import client as mqtt_client

from .const import MQTT_KEEPALIVE_SECONDS, MQTT_RECONNECT_MAX_DELAY, MQTT_RECONNECT_MIN_DELAY

_LOGGER = logging.getLogger(__name__)


def _build_client_id() -> str:
    return f"ha_navimow_{uuid.uuid4().hex[:12]}"


class NavimowMqttClient:
    """Persistente WSS-Verbindung zum Navimow-MQTT-Broker.

    Live verifiziert (2026-07-08): Topic-Schema /downlink/vehicle/{id}/realtimeDate/{channel},
    Push ist rein ereignisgesteuert (keine periodische Telemetrie waehrend stabilem Zustand).
    Root-Wildcard-Subscribe ("#") wird von der Multi-Tenant-Broker-ACL leer beantwortet -
    nur konkrete Topic-Strings abonnieren, keine Wildcards auf oberster Ebene.
    """

    def __init__(
        self,
        loop: asyncio.AbstractEventLoop,
        on_message: Callable[[str, Any, str], None],
        on_connection_changed: Callable[[bool], None] | None = None,
    ) -> None:
        self._loop = loop
        self._on_message = on_message
        self._on_connection_changed = on_connection_changed
        self._client_id = _build_client_id()
        self._device_ids: list[str] = []
        self._host: str | None = None
        self._port = 443
        self._ws_path: str | None = None
        self._username: str | None = None
        self._password: str | None = None
        self._access_token: str | None = None
        self._client: mqtt_client.Client | None = None
        self.is_connected = False
        # Verhindert, dass ein stuendlicher Watchdog-Reconnect (force_reconnect) und die
        # ebenfalls stuendliche OAuth-Token-Rotation (update_credentials) gleichzeitig eigene,
        # konkurrierende connect()-Ablaeufe starten und sich gegenseitig self._client
        # ueberschreiben (live beobachtet 2026-07-09: REST-Poll blieb danach dauerhaft stehen,
        # ohne sich selbst zu erholen - vermutlich genau diese Race Condition).
        self._connect_lock = asyncio.Lock()

    def configure(
        self,
        mqtt_host: str,
        mqtt_url: str,
        username: str | None,
        password: str | None,
        access_token: str,
        device_ids: list[str],
    ) -> None:
        parsed = urlparse(mqtt_host)
        self._host = parsed.hostname or mqtt_host
        self._port = parsed.port or 443
        self._ws_path = mqtt_url
        self._username = username
        self._password = password
        self._access_token = access_token
        self._device_ids = device_ids

    def _build_client(self) -> mqtt_client.Client:
        client = mqtt_client.Client(
            callback_api_version=mqtt_client.CallbackAPIVersion.VERSION1,
            client_id=self._client_id,
            transport="websockets",
        )
        if self._username and self._password:
            client.username_pw_set(self._username, self._password)
        if self._ws_path:
            client.ws_set_options(
                path=self._ws_path, headers={"Authorization": f"Bearer {self._access_token}"}
            )
        client.tls_set()
        client.reconnect_delay_set(min_delay=MQTT_RECONNECT_MIN_DELAY, max_delay=MQTT_RECONNECT_MAX_DELAY)
        client.on_connect = self._on_connect
        client.on_disconnect = self._on_disconnect
        client.on_message = self._on_mqtt_message
        return client

    async def connect(self) -> None:
        async with self._connect_lock:
            await self._connect_locked()

    async def _connect_locked(self) -> None:
        """Eigentlicher Verbindungsaufbau - Aufrufer muss self._connect_lock bereits halten."""
        if not self._host:
            raise RuntimeError("configure() muss vor connect() aufgerufen werden")
        # _build_client() ruft intern client.tls_set() auf, das synchron Zertifikatsspeicher
        # von der Platte liest (load_default_certs/set_default_verify_paths) - blockiert sonst
        # den Event-Loop (von HAs Blocking-Call-Detektor live gemeldet, 2026-07-08). Deshalb im
        # Executor-Thread bauen, nicht direkt im Event-Loop.
        self._client = await self._loop.run_in_executor(None, self._build_client)
        self._client.connect_async(self._host, self._port, MQTT_KEEPALIVE_SECONDS)
        self._client.loop_start()

    async def disconnect(self) -> None:
        # loop_stop() wartet laut paho-Doku, bis der Netzwerk-Thread sich beendet hat - haengt
        # dieser Thread selbst fest (z.B. blockierender Socket-Read), blockiert ein synchroner
        # Aufruf hier den GESAMTEN HA-Event-Loop, nicht nur diese Coroutine. Live beobachtet
        # 2026-07-09: genau das erklaert, warum selbst ein asyncio.timeout() um den Coordinator-
        # Zyklus nicht half - ein blockierter Event-Loop kann keine Timeouts mehr auswerten.
        # Deshalb wie _build_client() im Executor-Thread ausfuehren.
        client = self._client
        if client is not None:
            await self._loop.run_in_executor(None, self._disconnect_client, client)
        self.is_connected = False

    @staticmethod
    def _disconnect_client(client: mqtt_client.Client) -> None:
        client.loop_stop()
        client.disconnect()

    async def force_reconnect(self) -> None:
        """Fuer den Watchdog: erzwungener Neuaufbau, wenn REST-Poll eine Diskrepanz zeigt.

        paho's ws_set_options wirkt nur vor Verbindungsaufbau, daher Client komplett neu
        aufbauen statt nur reconnect() aufzurufen (uebernommen aus mower_sdk-Kommentaren).
        """
        _LOGGER.info("Navimow MQTT: erzwungener Reconnect (Watchdog-Diskrepanz erkannt)")
        async with self._connect_lock:
            await self.disconnect()
            await self._connect_locked()

    async def update_credentials(
        self,
        username: str | None = None,
        password: str | None = None,
        access_token: str | None = None,
    ) -> None:
        """Neue Zugangsdaten uebernehmen, ohne eine bestehende Verbindung aktiv zu trennen.

        Alle Parameter optional (None = unveraendert lassen) - erlaubt z.B. dem Coordinator,
        bei jedem REST-Poll nur den rotierenden access_token durchzureichen, ohne username/
        password erneut abfragen zu muessen. Vermeidet unnoetige Reconnects durch die
        stuendliche OAuth-Token-Rotation - der Broker trennt selbst nach ~1h Inaktivitaet,
        danach greifen die neuen Daten beim naechsten Verbindungsaufbau automatisch
        (siehe sdk-notizen.md, Freeze-Bug-Hypothese).
        """
        changed = False
        if username is not None and username != self._username:
            self._username = username
            changed = True
        if password is not None and password != self._password:
            self._password = password
            changed = True
        if access_token is not None and access_token != self._access_token:
            self._access_token = access_token
            changed = True
        if not changed:
            return
        async with self._connect_lock:
            if self._client is not None and self._client.is_connected():
                _LOGGER.debug("Navimow MQTT credentials updated, wird beim naechsten Reconnect uebernommen")
                return
            _LOGGER.debug("Navimow MQTT credentials updated waehrend getrennt, baue Client neu auf")
            await self._connect_locked()

    def _subscribe_all(self, client: mqtt_client.Client) -> None:
        # "location" ist nicht Teil des offiziellen SDK-Kanalsatzes, liefert aber laut
        # oeffentlich einsehbarem Fork-Code (pgoutsos/NavimowHA) Position/Zone/Fortschritt -
        # noch nicht selbst live verifiziert (siehe location.py, dokumentation/sdk-notizen.md).
        channels = ("state", "event", "attributes", "location")
        if not self._device_ids:
            for channel in channels:
                client.subscribe(f"/downlink/vehicle/+/realtimeDate/{channel}")
            return
        for device_id in self._device_ids:
            for channel in channels:
                client.subscribe(f"/downlink/vehicle/{device_id}/realtimeDate/{channel}")

    def _on_connect(self, client: mqtt_client.Client, _userdata: Any, _flags: Any, rc: int) -> None:
        if rc != 0:
            _LOGGER.warning("Navimow MQTT connect failed: rc=%s", rc)
            return
        _LOGGER.debug("Navimow MQTT connected")
        self._subscribe_all(client)
        self.is_connected = True
        if self._on_connection_changed:
            self._loop.call_soon_threadsafe(self._on_connection_changed, True)

    def _on_disconnect(self, _client: mqtt_client.Client, _userdata: Any, rc: int) -> None:
        _LOGGER.debug("Navimow MQTT disconnected (rc=%s)", rc)
        self.is_connected = False
        if self._on_connection_changed:
            self._loop.call_soon_threadsafe(self._on_connection_changed, False)

    def _parse_topic(self, topic: str) -> str | None:
        parts = topic.split("/")
        if parts and parts[0] == "":
            parts = parts[1:]
        if len(parts) != 5 or parts[0] != "downlink" or parts[1] != "vehicle" or parts[3] != "realtimeDate":
            return None
        return parts[2]  # device_id

    def _on_mqtt_message(self, _client: mqtt_client.Client, _userdata: Any, msg: Any) -> None:
        device_id = self._parse_topic(msg.topic)
        if device_id is None:
            return
        try:
            payload = json.loads(msg.payload.decode("utf-8"))
        except (UnicodeDecodeError, ValueError):
            _LOGGER.debug("Navimow MQTT payload not JSON: topic=%s", msg.topic)
            return
        # state/event/attributes liefern ein JSON-Objekt, location ein JSON-Array (siehe
        # location.py) - beide Formen durchreichen, alles andere verwerfen.
        if not isinstance(payload, (dict, list)):
            return
        if isinstance(payload, dict):
            payload.setdefault("device_id", device_id)
        self._loop.call_soon_threadsafe(self._on_message, msg.topic, payload, device_id)
