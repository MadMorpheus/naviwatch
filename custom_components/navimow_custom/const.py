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

# Live beobachtet 2026-07-08: ein bestehender REST/MQTT-Status-Mismatch (z.B. waehrend
# stabilem Maehen ohne MQTT-Events) loeste bei jedem weiteren Poll erneut einen erzwungenen
# Reconnect aus, obwohl der erste bereits alles Noetige getan hatte (3x zwischen 13:52 und
# 15:32 fuer denselben Mismatch). Debounce: nach einem erzwungenen Reconnect fuer diese Dauer
# keinen erneuten Reconnect fuer denselben, weiterhin bestehenden Mismatch ausloesen.
WATCHDOG_RECONNECT_DEBOUNCE: Final = timedelta(minutes=5)

MOWER_STATE_TOPIC_CHANNELS: Final = ("state", "event", "attributes")

CONF_DEVICE_ID: Final = "device_id"
