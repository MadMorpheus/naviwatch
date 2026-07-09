# Architektur

🇬🇧 [English](ARCHITECTURE.md) | 🇩🇪 Deutsch

Wie NaviWatch aufgebaut ist — und vor allem, wie oft sich jede Entität tatsächlich aktualisiert und wodurch das ausgelöst wird.

## REST-Poll vs. MQTT-Push

NaviWatch kombiniert zwei Datenquellen:

* **REST-Poll** — die Ground Truth. Läuft in einem festen Intervall (`poll_interval_seconds`-Option, Standard 120s), unabhängig von allem anderen.
* **MQTT-Push** — ereignisgesteuerte Updates von Segways Cloud-Broker. Reagiert innerhalb von Sekunden auf echte Änderungen, aber ohne festen Takt — manche Kanäle können viele Minuten still bleiben.

Ein Watchdog vergleicht beide bei jedem REST-Poll: Weicht der REST-gemeldete Status vom zuletzt per MQTT gemeldeten Status ab, wird ein MQTT-Reconnect erzwungen (mit 5-Minuten-Debounce, damit derselbe anhaltende Mismatch nicht wiederholt auslöst). Das macht die Integration robust gegenüber dem Freeze-Bug anderer Navimow-Integrationen — der REST-Poll wird bewusst unabhängig vom eigenen, nachrichtengetriebenen Update-Timing von MQTT gehalten (siehe „Warum Entity-Updates und der Poll-Zeitplan getrennt gehalten werden" weiter unten, warum diese Unabhängigkeit wichtig ist).

## Update-Auslöser pro Entität

| Entität | Quelle | Intervall/Auslöser |
|---|---|---|
| `lawn_mower` (State, `raw_state`) | REST-Poll **+** MQTT-`state`-Kanal | REST: fest ~120s. MQTT: ereignisgesteuert, nur bei echtem Zustandswechsel (z.B. docked→mowing), meist innerhalb von Sekunden nach der echten Änderung |
| `sensor` Akku | REST-Poll (primär), MQTT-`state`-Kanal (falls im Payload enthalten) | ~120s über REST — die verlässliche, garantierte Quelle |
| `binary_sensor` MQTT-Verbindung | Der MQTT-Client selbst (paho `on_connect`/`on_disconnect`) | Rein ereignisgesteuert — ändert sich nur bei echtem Connect/Disconnect, kein festes Intervall |
| Zone-Sensor (State) | MQTT-`location`-Kanal, Typ-2-Nachricht (`currentMowBoundary`) | Nur wenn der Mäher eine Zonengrenze überquert — nicht kontinuierlich, kann mehrere Minuten dauern |
| Mähfortschritt-Sensor | MQTT-`location`-Kanal, Typ-2-Nachricht (`currentMowProgress`) | Gleiche Nachricht wie Zone-Status, also gleiche (eher seltene) Frequenz |
| Position (`position_x`/`position_y`-Attribute) | MQTT-`location`-Kanal, Typ-1-Nachricht (Pose) | Deutlich häufiger — etwa alle paar Sekunden während aktivem Mähen, seltener im Ruhezustand |
| `target_zone`-Attribut | MQTT-`location`-Kanal, Typ-3-Nachricht | Nur einmal bei Mähstart/Zonenwahl gesetzt, unverändert bis zum nächsten Start |
| `task_delay`-Attribut | MQTT-`location`-Kanal, Typ-4-Nachricht | Nur bei Regen-/Zeitplan-Verzögerung, selten |

**Kurz gesagt:** REST ist der einzige feste Puls (~120s, unabhängig von allem anderen). Alles aus dem `location`-Kanal ist rein ereignisgesteuert und hängt vom tatsächlichen Mäher-Verhalten ab — Position häufig, Zone/Fortschritt/Zielzone/Verzögerung deutlich seltener.

## Der undokumentierte `location`-MQTT-Kanal

Die offizielle Segway-API/das SDK dokumentiert nur die Kanäle `state`, `event` und `attributes`. `location` (`/downlink/vehicle/{id}/realtimeDate/location`) wurde durch Einsicht in den öffentlichen Quellcode eines Drittanbieter-Forks gefunden, nicht aus offizieller Dokumentation — siehe den Abschnitt „Bekannte Risiken" in der [README](README.de.md) dazu, was das für die langfristige Zuverlässigkeit bedeutet. Der Payload ist ein JSON-**Array** (kein Objekt) aus Einträgen mit einem `type`-Feld:

| Typ | Bedeutung | Felder |
|---|---|---|
| 1 | Pose | `postureX`/`postureY` (Meter, lokales kartesisches Koordinatensystem relativ zur Ladestation — **kein GPS**), `postureTheta` (Radiant), `vehicleState` |
| 2 | Fortschritt | `currentMowBoundary` (aktuelle physische Zone), `currentMowProgress` (0–10000, Routen-Fortschritt — keine Flächenabdeckung) |
| 3 | Zielzone | `partitionIds` (bei Mähstart gesetzt, fehlt bei „alles mähen") |
| 4 | Verzögerung | `taskDelay` (Regen-/Zeitplan-Verzögerung) |

Die Dekodierung liegt in `custom_components/navimow_custom/location.py`.

**Zone-/Partition-IDs sind nicht fortlaufend und nicht identisch mit den "Zone 1"/"Zone 2"-Bezeichnungen der App** — live bestätigt an einem Zwei-Zonen-Garten: die Zonen zeigten die IDs `9` und `4`, nicht `1`/`2`. Es gibt keinen bekannten Weg, die Zuordnung ID → App-Bezeichnung herzuleiten, außer jede Zone einmal zu starten und zu beobachten, welche ID erscheint.

## Warum Entity-Updates und der Poll-Zeitplan getrennt gehalten werden

Home Assistants `DataUpdateCoordinator.async_set_updated_data()` ist praktisch für Push-Updates, setzt aber bei jedem Aufruf auch den Timer für den nächsten geplanten Poll zurück. Während aktivem Mähen treffen `location`-Nachrichten (meist Pose-Updates) etwa alle 2 Sekunden ein — ein Aufruf von `async_set_updated_data()` aus dem Nachrichten-Handler würde den 120-Sekunden-REST-Poll-Countdown zurücksetzen, bevor er je ablaufen könnte, und den REST-Poll (und damit den Watchdog) stillschweigend verhungern lassen, solange sich der Mäher bewegte. Das wurde live (2026-07-09) über `custom_components.navimow_custom: debug`-Logging gefunden, das Home Assistants eigene Debug-Zeile „Manually updated navimow_custom data" im 2-Sekunden-Takt zeigte, statt der erwarteten ~120s-Poll-Kadenz.

Der Fix: MQTT-Push-Handler aktualisieren jetzt `self.data` direkt und rufen `async_update_listeners()` statt `async_set_updated_data()` auf — Entities aktualisieren sich weiterhin sofort bei Push-Daten, ohne je den Poll-Zeitplan zu berühren.
