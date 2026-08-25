"""Constants for the Navimow (custom) integration."""

from __future__ import annotations

from datetime import timedelta
from typing import Final

DOMAIN: Final = "navimow_custom"

# OAuth2 / API-Werte, live verifiziert am 2026-07-08 (siehe dokumentation/sdk-notizen.md).
# Aus segwaynavimow/NavimowHA (GitHub) extrahiert, kein eigenes Geheimnis - ein fuer alle
# HA-Installationen gemeinsam genutzter "public client".
OAUTH2_AUTHORIZE: Final = "https://navimow-h5-fra.willand.com/smartHome/login"
OAUTH2_TOKEN: Final = "https://navimow-fra.ninebot.com/openapi/oauth/getAccessToken"
CLIENT_ID: Final = "homeassistant"
CLIENT_SECRET: Final = "57056e15-722e-42be-bbaa-b0cbfb208a52"

API_BASE_URL: Final = "https://navimow-fra.ninebot.com"

# Live beobachtet 2026-07-09: ein REST-Request ohne Timeout kann auf unbestimmte Zeit haengen
# (kein Fehler, keine Exception) und blockiert damit jeden weiteren Poll, da der Coordinator
# den naechsten erst nach Abschluss des aktuellen einplant. 30s ist grosszuegig fuer eine
# Cloud-API, verhindert aber ein dauerhaftes Einfrieren.
REST_REQUEST_TIMEOUT: Final = 30

# Live beobachtet 2026-07-09: der komplette Update-Zyklus (REST-Call + ggf. Watchdog-Reconnect
# + Credential-Refresh) blieb trotz Request-Timeout ein weiteres Mal dauerhaft stehen, diesmal
# zeitgleich mit einem Reconnect - Ursache nicht abschliessend geklärt (vermutlich eine
# subtile Interaktion zwischen dem MQTT-Reconnect-Callback und HAs Poll-Terminplanung).
# Genereller Schutz: der GESAMTE Zyklus bekommt ein hartes Zeitlimit, damit der Coordinator
# so oder so nach jedem Intervall ein Ergebnis bekommt statt fuer immer zu haengen.
COORDINATOR_UPDATE_TIMEOUT: Final = 60

# REST-Poll-Intervall: dient als Ziel-2-Fallback UND als Ziel-1-Watchdog-Grundlage (Abgleich
# gegen den zuletzt per MQTT bekannten Zustand). MQTT liefert Zustandswechsel typischerweise
# innerhalb von Sekunden (live verifiziert) - der Poll ist die Sicherheitsnetz-Frequenz, kein
# primaerer Aktualisierungsweg.
REST_POLL_INTERVAL: Final = timedelta(seconds=120)

# MQTT-Keepalive: 40 Minuten, um vor der beobachteten "1h ohne Traffic"-Trennung des
# Segway-Brokers noch Protokoll-Traffic (PINGREQ/PINGRESP) zu erzeugen (siehe sdk-notizen.md,
# Freeze-Bug-Hypothese aus den mower_sdk-Kommentaren).
MQTT_KEEPALIVE_SECONDS: Final = 2400
MQTT_RECONNECT_MIN_DELAY: Final = 1
MQTT_RECONNECT_MAX_DELAY: Final = 60

# Obergrenze fuer das Stoppen eines MQTT-Clients (_async_teardown_client). loop_stop()
# joint den paho-Netzwerk-Thread; haengt der fest, darf das nicht unbegrenzt den
# _connect_lock halten, hinter dem inzwischen jeder Verbindungsweg steht.
MQTT_TEARDOWN_TIMEOUT: Final = 10

# Live beobachtet 2026-07-08: ein bestehender REST/MQTT-Status-Mismatch (z.B. waehrend
# stabilem Maehen ohne MQTT-Events) loeste bei jedem weiteren Poll erneut einen erzwungenen
# Reconnect aus, obwohl der erste bereits alles Noetige getan hatte (3x zwischen 13:52 und
# 15:32 fuer denselben Mismatch). Debounce: nach einem erzwungenen Reconnect fuer diese Dauer
# keinen erneuten Reconnect fuer denselben, weiterhin bestehenden Mismatch ausloesen.
WATCHDOG_RECONNECT_DEBOUNCE: Final = timedelta(minutes=5)

MOWER_STATE_TOPIC_CHANNELS: Final = ("state", "event", "attributes")

CONF_DEVICE_ID: Final = "device_id"

# Bounded Command-Verification nach dem Vorbild von doctee/symcon-navimow (siehe CLAUDE.md):
# nach dem Senden eines Kommandos wird bis zu "timeout" Sekunden gepollt, ob der Zielzustand
# tatsaechlich erreicht wird - vorher kehrte der Service-Call nach einem einzigen Poll zurueck,
# unabhaengig vom Ergebnis, ein von der Cloud angenommenes aber vom Maeher nicht ausgefuehrtes
# Kommando waere unbemerkt geblieben. "initial_delay" vor dem ersten Poll aus demselben Grund
# wie zuvor: MQTT reagiert nachweislich schneller als ein sofortiger REST-Poll, ohne die Frist
# wuerde der Watchdog faelschlich einen Mismatch sehen. Dock braucht ein deutlich laengeres
# Budget (Rueckfahrt kann mehrere Minuten dauern) und laeuft deshalb im Hintergrund, damit der
# Service-Call nicht minutenlang blockiert - "returning" gilt dabei als gueltiger Zwischenstand.
COMMAND_VERIFICATION_SPECS: Final = {
    "async_start_mowing": {
        "target_states": frozenset({"mowing"}),
        "initial_delay": 5,
        "poll_interval": 10,
        "timeout": 30,
        "background": False,
    },
    "async_pause": {
        "target_states": frozenset({"paused"}),
        "initial_delay": 5,
        "poll_interval": 10,
        "timeout": 30,
        "background": False,
    },
    "async_dock": {
        "target_states": frozenset({"docked"}),
        "initial_delay": 5,
        "poll_interval": 60,
        "timeout": 900,
        "background": True,
    },
}
