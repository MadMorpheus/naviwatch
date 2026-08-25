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

from .const import (
    MQTT_KEEPALIVE_SECONDS,
    MQTT_RECONNECT_MAX_DELAY,
    MQTT_RECONNECT_MIN_DELAY,
    MQTT_TEARDOWN_TIMEOUT,
)

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
        # mid (message id von client.subscribe()) -> Topic, nur um on_subscribe-Antworten
        # (SUBACK) im Log dem jeweiligen Kanal zuordnen zu koennen. Wird pro Eintrag beim
        # Empfang der Bestaetigung wieder entfernt.
        self._pending_subscriptions: dict[int, str] = {}
        # Verhindert, dass ein stuendlicher Watchdog-Reconnect (force_reconnect) und die
        # ebenfalls stuendliche OAuth-Token-Rotation (update_credentials) gleichzeitig eigene,
        # konkurrierende connect()-Ablaeufe starten und sich gegenseitig self._client
        # ueberschreiben (live beobachtet 2026-07-09: REST-Poll blieb danach dauerhaft stehen,
        # ohne sich selbst zu erholen - vermutlich genau diese Race Condition).
        self._connect_lock = asyncio.Lock()
        # Einweg-Flag, gesetzt von disconnect(). Ein Reload legt ohnehin eine neue
        # NavimowMqttClient-Instanz an, es muss also nie zurueckgesetzt werden.
        self._closed = False

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
        client.on_subscribe = self._on_subscribe
        return client

    async def connect(self) -> None:
        async with self._connect_lock:
            await self._connect_locked()

    async def _connect_locked(self) -> None:
        """Eigentlicher Verbindungsaufbau - Aufrufer muss self._connect_lock bereits halten."""
        if self._closed:
            # Nach disconnect() nie wieder aufbauen. _async_refresh_mqtt_credentials() wird im
            # Coordinator ueber hass.async_create_task() gestartet und ueberlebt damit das
            # Entladen des Entry; ohne diese Bremse wuerde ein solcher Task nach dem Shutdown
            # ueber update_credentials() einen frischen Client samt Netzwerk-Thread bauen, den
            # niemand mehr stoppen kann - genau der Zombie, den diese Klasse gerade vermeidet.
            _LOGGER.debug("Navimow MQTT: Verbindungsaufbau nach disconnect() verworfen")
            return
        if not self._host:
            raise RuntimeError("configure() muss vor connect() aufgerufen werden")
        # Einen bereits gebauten Client IMMER zuerst vollstaendig stoppen. paho's
        # loop_start()-Thread laeuft in loop_forever() und baut nach einem unerwarteten
        # Disconnect selbsttaetig neu auf - nur ein explizites disconnect() beendet ihn.
        # Wird self._client also einfach ueberschrieben, laeuft der alte Client als Zombie
        # weiter: er ruft weiterhin unsere gebundenen Callbacks auf (jeder seiner Disconnects
        # stoesst ueber den Coordinator einen weiteren Zugangsdaten-Refresh an), und
        # async_shutdown() erreicht nur noch den juengsten self._client - alle aelteren
        # verschwinden erst mit einem Neustart von Home Assistant.
        # Verschaerfend teilen sich alle Clients dieselbe self._client_id: der Broker wirft
        # bei jedem Connect die gleichnamige Session hinaus (MQTT Session Takeover), Zombie
        # und aktiver Client werfen sich also gegenseitig endlos hinaus, und jede dieser
        # Trennungen erzeugt wieder einen Refresh.
        await self._async_teardown_client()
        # _build_client() ruft intern client.tls_set() auf, das synchron Zertifikatsspeicher
        # von der Platte liest (load_default_certs/set_default_verify_paths) - blockiert sonst
        # den Event-Loop (von HAs Blocking-Call-Detektor live gemeldet, 2026-07-08). Deshalb im
        # Executor-Thread bauen, nicht direkt im Event-Loop.
        client = await self._loop.run_in_executor(None, self._build_client)
        self._client = client
        try:
            client.connect_async(self._host, self._port, MQTT_KEEPALIVE_SECONDS)
            client.loop_start()
        except Exception:
            # Ab der Zuweisung oben zeigt self._client auf den neuen Client. Scheitert der
            # Start danach (loop_start() findet z.B. keinen freien OS-Thread), bliebe sonst
            # ein nie gestarteter Client stehen, den update_credentials() faelschlich fuer
            # lebendig haelt - und auf dem Setup-Pfad, wo __init__.py async_setup() ausserhalb
            # seines try/except mit async_shutdown() aufruft, wuerde ihn nie jemand abraeumen.
            await self._async_teardown_client()
            raise

    async def disconnect(self) -> None:
        """Endgueltig herunterfahren - diese Instanz baut danach keine Verbindung mehr auf."""
        # Muss denselben Lock nehmen wie jeder andere Weg, der self._client anfasst. Sonst
        # kann disconnect() genau dann laufen, wenn ein _connect_locked() im Executor auf
        # _build_client() wartet: self._client ist in diesem Moment bereits None, disconnect()
        # findet nichts zum Abraeumen und meldet Vollzug - und der wartende Aufbau startet
        # danach einen Client, auf den niemand mehr eine Referenz hat.
        # (Frueher konnte disconnect() den Lock nicht nehmen, weil force_reconnect() es
        # haltend aufrief; das tut es nicht mehr, _connect_locked() raeumt selbst ab.)
        async with self._connect_lock:
            self._closed = True
            await self._async_teardown_client()

    async def _async_teardown_client(self) -> None:
        """Aktuellen Client samt Netzwerk-Thread beenden und die Referenz freigeben.

        Muss vor jedem Neuaufbau laufen (siehe _connect_locked) - sonst bleibt der alte
        paho-Thread im Hintergrund am Reconnecten. Aufrufer muss self._connect_lock halten.
        """
        client = self._client
        # Referenz VOR dem Stoppen loeschen: waehrend des Executor-Aufrufs unten laeuft der
        # Event-Loop weiter, und die Callbacks des sterbenden Clients pruefen ueber
        # _is_current(), ob sie noch fuer den aktuellen Client sprechen.
        self._client = None
        self.is_connected = False
        if client is None:
            return
        # loop_stop() wartet laut paho-Doku, bis der Netzwerk-Thread sich beendet hat - haengt
        # dieser Thread selbst fest (z.B. blockierender Socket-Read), blockiert ein synchroner
        # Aufruf hier den GESAMTEN HA-Event-Loop, nicht nur diese Coroutine. Live beobachtet
        # 2026-07-09: genau das erklaert, warum selbst ein asyncio.timeout() um den Coordinator-
        # Zyklus nicht half - ein blockierter Event-Loop kann keine Timeouts mehr auswerten.
        # Deshalb wie _build_client() im Executor-Thread ausfuehren.
        #
        # Und mit Obergrenze: der Aufrufer haelt den _connect_lock, hinter dem inzwischen
        # JEDER Verbindungsweg steht (connect, disconnect, force_reconnect,
        # update_credentials). Ein festhaengender Netzwerk-Thread wuerde diesen Lock sonst
        # dauerhaft blockieren und Unload, Reload und jeden kuenftigen Reconnect mit ihm -
        # also genau das "hilft nur ein HA-Neustart", das dieser Patch beseitigen soll.
        # loop_stop() hat _thread_terminate zu diesem Zeitpunkt bereits gesetzt, der Thread
        # beendet sich also selbst, sobald er wieder freilaeuft; der Executor-Thread bleibt
        # bis dahin belegt. self._client ist oben schon geloest, der Client ist damit auch im
        # Timeout-Fall aus dem Weg.
        try:
            async with asyncio.timeout(MQTT_TEARDOWN_TIMEOUT) as timeout:
                await self._loop.run_in_executor(None, self._disconnect_client, client)
        except TimeoutError:
            # socket.timeout ist seit Python 3.10 derselbe eingebaute Typ wie asyncio's
            # TimeoutError, ein Timeout IM Client waere hier also nicht von unserer eigenen
            # Obergrenze zu unterscheiden. expired() trennt die beiden Faelle, damit die
            # Warnung nicht die falsche Ursache nennt.
            if timeout.expired():
                _LOGGER.warning(
                    "Navimow MQTT: Client liess sich nicht innerhalb von %ss stoppen, "
                    "weiter ohne ihn (er beendet sich selbst, sobald sein Thread freilaeuft)",
                    MQTT_TEARDOWN_TIMEOUT,
                )
            else:
                _LOGGER.debug("Navimow MQTT: Timeout beim Stoppen des Clients")

    @staticmethod
    def _disconnect_client(client: mqtt_client.Client) -> None:
        # Reihenfolge ist wichtig: disconnect() ZUERST, dann loop_stop(). disconnect() setzt
        # den Client auf MQTT_CS_DISCONNECTING und stellt das DISCONNECT-Paket in die
        # Sendewarteschlange; der noch laufende Netzwerk-Thread schreibt es und schliesst den
        # Socket direkt in _packet_write(). Umgekehrt beendet loop_stop() den Thread ueber
        # _thread_terminate, und dieser Pfad in loop_forever() schliesst den Socket NICHT -
        # der Broker wuerde die tote Sitzung dann bis zum Keepalive-Timeout offenhalten
        # (MQTT_KEEPALIVE_SECONDS). loop_stop() beendet den Thread erst, wenn dessen
        # Sendewarteschlange leer ist, das DISCONNECT geht also nicht verloren. Und selbst
        # wenn gar kein Socket mehr offen ist, setzt disconnect() den Zustand, was den
        # laufenden Reconnect-Backoff (_reconnect_wait()) sofort beendet.
        client.disconnect()
        try:
            client.loop_stop()
        except RuntimeError:
            # loop_stop() joint den Netzwerk-Thread. Wurde der nie gestartet - genau der Fall,
            # in dem loop_start() selbst geworfen hat -, wirft join(); zu stoppen ist dann
            # ohnehin nichts.
            _LOGGER.debug("Navimow MQTT: loop_stop() ohne laufenden Netzwerk-Thread")

    def _is_current(self, client: mqtt_client.Client) -> bool:
        """True, wenn ein Callback vom aktuell gueltigen Client stammt.

        paho reicht den ausloesenden Client an jeden Callback durch, unsere Callbacks sind
        aber an self gebunden und liefen sonst auch fuer einen laengst abgeraeumten Client
        weiter - ein sterbender Client kann z.B. noch ein spaetes CONNACK zustellen und damit
        is_connected faelschlich auf True setzen. Waehrend und nach _async_teardown_client()
        ist self._client None, solche Callbacks werden hier also verworfen.
        """
        return client is self._client

    async def force_reconnect(self) -> None:
        """Fuer den Watchdog: erzwungener Neuaufbau, wenn REST-Poll eine Diskrepanz zeigt.

        paho's ws_set_options wirkt nur vor Verbindungsaufbau, daher Client komplett neu
        aufbauen statt nur reconnect() aufzurufen (uebernommen aus mower_sdk-Kommentaren).
        """
        _LOGGER.info("Navimow MQTT: erzwungener Reconnect (Watchdog-Diskrepanz erkannt)")
        async with self._connect_lock:
            # Kein separates disconnect() mehr noetig - _connect_locked() raeumt den alten
            # Client selbst ab, und zwar auf JEDEM Pfad, nicht nur hier.
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
        # Auch ohne geaenderte Zugangsdaten weitermachen, wenn gar kein Client existiert:
        # scheitert ein Neuaufbau in _connect_locked(), raeumt der seinen halbfertigen Client
        # ab und hinterlaesst self._client None. Ohne diese Bedingung wuerde der naechste Poll
        # hier abbrechen, solange sich der Token nicht geaendert hat, und die Integration
        # haette keinen Client bis zur naechsten stuendlichen Token-Rotation. Der Poll laeuft
        # deutlich haeufiger und holt den Aufbau so bei jedem Durchgang nach.
        if not changed and self._client is not None:
            return
        async with self._connect_lock:
            if self._client is not None and self._client.is_connected():
                _LOGGER.debug("Navimow MQTT credentials updated, wird beim naechsten Reconnect uebernommen")
                return
            # Genau hier entstanden bisher die Zombie-Clients: der alte Client war nicht
            # verbunden, aber sein Netzwerk-Thread lief noch und versuchte weiter zu
            # reconnecten, waehrend self._client ueberschrieben wurde. _connect_locked()
            # stoppt ihn jetzt zuerst.
            _LOGGER.debug("Navimow MQTT credentials updated waehrend getrennt, baue Client neu auf")
            await self._connect_locked()

    def _subscribe_all(self, client: mqtt_client.Client) -> None:
        # "location" ist nicht Teil des offiziellen SDK-Kanalsatzes, liefert aber laut
        # oeffentlich einsehbarem Fork-Code (pgoutsos/NavimowHA) Position/Zone/Fortschritt -
        # noch nicht selbst live verifiziert (siehe location.py, dokumentation/sdk-notizen.md).
        channels = ("state", "event", "attributes", "location")
        if not self._device_ids:
            for channel in channels:
                topic = f"/downlink/vehicle/+/realtimeDate/{channel}"
                self._subscribe_and_track(client, topic)
            return
        for device_id in self._device_ids:
            for channel in channels:
                topic = f"/downlink/vehicle/{device_id}/realtimeDate/{channel}"
                self._subscribe_and_track(client, topic)

    def _subscribe_and_track(self, client: mqtt_client.Client, topic: str) -> None:
        _result, mid = client.subscribe(topic)
        self._pending_subscriptions[mid] = topic

    def _on_connect(self, client: mqtt_client.Client, _userdata: Any, _flags: Any, rc: int) -> None:
        if not self._is_current(client):
            return
        if rc != 0:
            _LOGGER.warning("Navimow MQTT connect failed: rc=%s", rc)
            return
        _LOGGER.debug("Navimow MQTT connected")
        self._subscribe_all(client)
        self.is_connected = True
        if self._on_connection_changed:
            self._loop.call_soon_threadsafe(self._on_connection_changed, True)

    def _on_disconnect(self, client: mqtt_client.Client, _userdata: Any, rc: int) -> None:
        if not self._is_current(client):
            return
        _LOGGER.debug("Navimow MQTT disconnected (rc=%s)", rc)
        self.is_connected = False
        if self._on_connection_changed:
            self._loop.call_soon_threadsafe(self._on_connection_changed, False)

    def _on_subscribe(
        self, client: mqtt_client.Client, _userdata: Any, mid: int, granted_qos: list[int]
    ) -> None:
        if not self._is_current(client):
            return
        # Ohne diesen Callback ist aus dem Log nicht erkennbar, ob der Broker ein Subscribe
        # (z.B. fuer den undokumentierten 'location'-Kanal) tatsaechlich per ACL gewaehrt oder
        # mit Failure-Code 0x80/128 abgelehnt hat - beides sieht sonst identisch "still" aus.
        topic = self._pending_subscriptions.pop(mid, "<unbekanntes Topic>")
        if any(qos == 128 for qos in granted_qos):
            _LOGGER.warning(
                "Navimow MQTT: Subscribe fuer Topic '%s' vom Broker abgelehnt (granted_qos=%s)",
                topic,
                granted_qos,
            )
        else:
            _LOGGER.debug(
                "Navimow MQTT: Subscribe fuer Topic '%s' bestaetigt (granted_qos=%s)",
                topic,
                granted_qos,
            )

    def _parse_topic(self, topic: str) -> str | None:
        parts = topic.split("/")
        if parts and parts[0] == "":
            parts = parts[1:]
        if len(parts) != 5 or parts[0] != "downlink" or parts[1] != "vehicle" or parts[3] != "realtimeDate":
            return None
        return parts[2]  # device_id

    def _on_mqtt_message(self, client: mqtt_client.Client, _userdata: Any, msg: Any) -> None:
        if not self._is_current(client):
            return
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
