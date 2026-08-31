# Changelog

Alle relevanten Änderungen an NaviWatch werden in dieser Datei dokumentiert.

Das Format orientiert sich an [Keep a Changelog](https://keepachangelog.com/de/1.1.0/).

## [0.3.2] - 2026-08-31

### Behoben

- **`dock_distance` zeigte auch angedockt noch ~0,75 m an.** Die mähereigene Positionsschätzung (SLAM/Odometrie) legt ihren Koordinatenursprung nicht exakt auf die physische Ladestation, wodurch diese Restdrift bei einer Messung gegen ein festes `(0,0)` direkt in den Sensor durchschlug. Die Ladestation bewegt sich nicht — jeder beobachtete `docked`-Zustand mit bekannter Position wird jetzt als neuer Null-Punkt übernommen (`dock_offset_x`/`dock_offset_y`), und `dock_distance` misst gegen diesen kalibrierten Offset statt gegen `(0,0)`. Live verifiziert am 31.08.2026: der Sensor sprang genau beim Wechsel auf angedockt von den alten ~0,75 m auf 0,0 m und verfolgte den anschließenden Mähvorgang danach korrekt.
- **Ein rate-limitierter Abruf der MQTT-Zugangsdaten beim Setup legte die Integration still, bis sie manuell neu geladen wurde.** `async_setup()` sicherte `async_get_devices()` mit `ConfigEntryNotReady` ab, der direkt darunter stehende Aufruf `_async_connect_mqtt()` jedoch nicht — der `NavimowApiError` aus `async_get_mqtt_user_info()` verließ `async_setup_entry()` also als gewöhnliche Exception. Home Assistant wertet alles außer `ConfigEntryNotReady` als endgültigen Setup-Fehler und plant keinen Retry ein. Bei der stündlichen OAuth-Rotation lädt der Entry neu und holt sofort neue MQTT-Zugangsdaten, was Segway rate-limitet (`Request too frequent. Please retry after 1 minute.`) — beobachtet auf einem US-Account am 17.08.2026 um 18:17, danach blieb die Integration 8,5 Stunden tot, obwohl der Fehler laut eigener Beschreibung vorübergehend ist. Jetzt wird `ConfigEntryNotReady` geworfen, Home Assistant wartet ab und versucht es erneut; live verifiziert am 18.08.2026 um 13:37, wo sich dasselbe Rate-Limit nach 6 Sekunden von selbst auflöste.
- **Der Refresh der MQTT-Zugangsdaten konnte das Rate-Limit, auf das er stieß, selbst aufrechterhalten.** `_handle_mqtt_connection_changed()` startet `_async_refresh_mqtt_credentials()` bei jedem Disconnect über `async_create_task()`. Schlug dieser Refresh wegen des Rate-Limits fehl, wurde nur eine Warnung geloggt und zurückgekehrt — der Client behielt seine alten Zugangsdaten, verband sich neu, scheiterte, trennte und stieß den nächsten Refresh an. Beobachtet am 18.08.2026 zwischen 12:34 und 13:33: 36 Versuche im Abstand von rund 1,6 Sekunden. Eine Single-Flight-Sperre bündelt aufgelaufene Disconnect-Tasks jetzt zu einem einzigen laufenden Refresh, und ein Cooldown von 65 Sekunden — knapp über der Minute, um die der Server selbst bittet, damit Jitter die Wiederholung nicht wieder in dasselbe Fenster fallen lässt — begrenzt den schlimmsten Fall auf einen Aufruf pro Cooldown statt etwa 37. `update_credentials()` bleibt außerhalb der Sperre, damit MQTT-Arbeit sie nie hält.
- **Beim Ersetzen des MQTT-Clients lief der alte im Hintergrund weiter.** `update_credentials()` baut den Client neu auf, wenn er zwar existiert, aber nicht verbunden ist; `_connect_locked()` schrieb den neuen Client dabei direkt über `self._client`, ohne den alten zu stoppen. paho's `loop_start()`-Thread läuft in `loop_forever()` und verbindet nach jedem unerwarteten Disconnect selbsttätig neu — nur ein explizites `disconnect()` beendet ihn. Der überschriebene Client lief also mit weiterhin gebundenen Callbacks weiter, jeder seiner Disconnects stieß einen weiteren Zugangsdaten-Refresh an, und `async_shutdown()` erreichte nur noch den jüngsten Client; alle übrigen verschwanden erst mit einem Neustart von Home Assistant. Da alle Clients dieselbe Client-ID verwenden, warf der Broker bei jedem Connect zusätzlich die gleichnamige Session hinaus — Zombie und aktiver Client warfen sich also endlos gegenseitig hinaus, gemeldet mit 21–63 Refreshes pro Sekunde und rund 14,8 Millionen Warnungen in einer Woche. `_connect_locked()` stoppt den vorherigen Client jetzt auf jedem Pfad, und vier weitere Wege zum selben Ergebnis sind mit geschlossen: `disconnect()` nimmt `_connect_lock` wie jeder andere Einstiegspunkt und kann daher nicht mehr Vollzug melden, während ein Neuaufbau im Executor wartet; ein Einweg-Flag hindert den Refresh-Task — der das Entladen des Entry überlebt — daran, nach dem Shutdown noch einen Client zu bauen; die Callbacks prüfen, ob sie zum aktuellen Client gehören, damit ein sterbender keine späte Verbindung mehr meldet; und ein fehlgeschlagener Neuaufbau wird beim nächsten Poll wiederholt statt bis zur stündlichen Token-Rotation zu warten. `_disconnect_client()` ruft außerdem `disconnect()` vor statt nach `loop_stop()` auf, damit der Socket tatsächlich geschlossen wird und nicht bis zum Keepalive-Timeout offen bleibt. Das Stoppen eines Clients ist zudem zeitlich begrenzt, denn es geschieht jetzt unter der Sperre, hinter der jeder Verbindungsweg steht — ein festhängender paho-Thread würde sonst Unload, Reload und jeden künftigen Reconnect blockieren; und ein Neuaufbau, der zwischen dem Zuweisen und dem Starten des neuen Clients scheitert, räumt diesen ab, bevor er die Ausnahme weiterreicht, was zugleich ein Leck auf dem Setup-Pfad beseitigt.
- **Ein fehlgeschlagener Verbindungs*versuch* löste nie einen Zugangsdaten-Refresh aus.** Der Coordinator frischt die Zugangsdaten aus `on_connection_changed(False)` auf, was der Client bisher nur aus `on_disconnect` meldete. Einen gescheiterten Versuch meldet paho aber nicht darüber — `loop_forever()` fängt den Fehler ab und ruft stattdessen `_handle_on_connect_fail()`. Genau diesen Weg nimmt ein rotierter Token, denn er steht im WSS-`Authorization`-Header und wird schon beim HTTP-Upgrade abgelehnt, also vor jedem CONNACK. Der Refresh, der das behoben hätte, wurde nie eingeplant; die Erholung hing an einem zufälligen anderen Disconnect oder am stündlichen REST-Poll. `on_connect_fail` ist jetzt gebunden, und da "nicht verbunden" dadurch während paho's Backoff wiederholt eintrifft, werden Entities nur noch bei einem echten Wechsel aktualisiert, während der Refresh bei jedem Versuch läuft. Ein abgelehntes CONNACK wird außerdem nicht mehr bei jedem Wiederholungsversuch auf `WARNING` geloggt — paho versucht es unbegrenzt weiter, ein dauerhaft ablehnender Broker erzeugte diese Zeile also endlos; nur der erste Fehlschlag einer Serie ist jetzt eine Warnung.

## [0.3.0] - 2026-07-27

### Hinzugefügt

- **Unterstützung für mehrere Mäher.** Ein Account kann jetzt beliebig viele Mäher haben; der Coordinator pollt alle in einem REST-Call, teilt sich einen MQTT-Client für alle, und routet eingehende Nachrichten anhand der im jeweiligen MQTT-Topic enthaltenen `device_id`. `coordinator.data` ist jetzt `dict[device_id, NavimowData]` statt eines einzelnen Objekts, und jede Entity nimmt jetzt eine `device_id` entgegen, um ihren eigenen Ausschnitt nachzuschlagen. Bisher wurde immer nur `devices[0]` aus dem Account verwendet, was bei instabiler Geräte-Reihenfolge im Account bei jedem Neustart ein anderes Gerät auswählen und verwaiste "Geister"-Geräte in der Entity-Registry hinterlassen konnte.
- Das Grundgerüst des Multi-Geräte-Umbaus (der `dict[device_id, ...]`-Coordinator, der gemeinsame MQTT-Client, Entities pro Gerät) stammt von [github.com/klarah32](https://github.com/klarah32) — vielen Dank dafür! Eine Anpassung wurde vor der Übernahme vorgenommen: Das in 0.2.2 hinzugefügte, zeitlich begrenzte Command-Verification-Feature (`COMMAND_VERIFICATION_SPECS`/`last_command_result`) war dabei verlorengegangen. Es wurde hier wiederhergestellt, jetzt pro `device_id` statt global, und am 2026-07-27 live gegen einen echten Mäher erneut verifiziert (`pause`/`start_mowing` beide `verified` bestätigt).

### Bekannte Einschränkung

- Es wird weiterhin nur ein Home-Assistant-Config-Entry (ein Segway/Navimow-Account) unterstützt. Mehrere Mäher im selben Account werden automatisch erkannt; ein zweiter, separater Account nicht — `config_flow.py` bindet seine `unique_id` weiterhin an die Integrations-Domain statt an einen Account.

## [0.2.2] - 2026-07-27

### Hinzugefügt

- **Zeitlich begrenzte Kommando-Verifikation** nach `start_mowing`/`pause`/`dock`. Bisher kehrte der Service-Call nach einem einzigen Poll zurück, unabhängig vom Ergebnis — ein von der Cloud angenommenes, aber vom Mäher nie tatsächlich ausgeführtes Kommando (Hindernis, Funkloch) wäre unbemerkt geblieben. Jetzt pollt der Coordinator (bis zu einem kommandospezifischen Zeitbudget), bis der Zielzustand tatsächlich erreicht ist, und stellt das Ergebnis als `last_command_result` (`verified` oder `timeout`, plus letzter bekannter Zustand) als Attribut am Mäher-Entity bereit. `dock` verifiziert im Hintergrund (Budget bis zu 15 Minuten für die Rückfahrt), damit der Service-Call selbst nicht blockiert. Live gegen den echten Mäher verifiziert am 2026-07-13, inklusive einer echten ~1:38-minütigen Rückfahrt — dieses Release holt das nur versionsmäßig nach, gelaufen ist es seitdem bereits unversioniert.

## [0.2.1] - 2026-07-24

### Behoben

- **Ausgelaufene MQTT-Verbindungen nach fehlgeschlagenem erstem Refresh konnten sich zu einem Reconnect-Sturm aufschaukeln.** Schlug der allererste Daten-Refresh beim Setup fehl (`async_config_entry_first_refresh()` wirft dann `ConfigEntryNotReady`), wurde der kurz zuvor erstellte MQTT-Client nie getrennt — der Coordinator war zu diesem Zeitpunkt noch nirgends gespeichert und damit für die Aufräum-Logik unerreichbar. Home Assistants automatischer Setup-Retry erstellte daraufhin bei jedem weiteren Versuch einen neuen Coordinator samt neuer, aktiver MQTT-Verbindung, während die verwaisten alten Verbindungen im Hintergrund endlos weiter zu reconnecten versuchten. Bei genug Retries kämpften mehrere Verbindungen gleichzeitig um dieselbe Broker-Session, erkennbar an schnellem, durchgehendem Verbindungsauf-/-abbau (`rc=7`) über mehrere Client-IDs hinweg. `async_setup_entry()` fährt den Coordinator (inkl. Trennen des MQTT-Clients) jetzt explizit herunter, wenn der erste Refresh fehlschlägt, bevor der Fehler weitergereicht wird. Bereits betroffene Instanzen benötigen einen vollständigen Neustart von Home Assistant, um die verwaisten Verbindungen loszuwerden — ein reines Neuladen der Integration reicht nicht.

### Hinzugefügt

- `mqtt_client.py` registriert jetzt einen `on_subscribe`-Callback und loggt pro Topic, ob der Broker ein Abonnement bestätigt (`DEBUG`) oder abgelehnt hat (`WARNING`, z. B. bei einer ACL-Verweigerung) — auch für den undokumentierten `location`-Kanal. Bisher war aus dem Log nicht erkennbar, ob ein Subscribe für einen bestimmten Kanal tatsächlich erfolgreich war; eine Ablehnung und ein Kanal, der einfach nie Nachrichten sendet, sahen im Log identisch aus.

## [0.2.0] - 2026-07-09

### Hinzugefügt

- Sensoren für Zone, Mähfortschritt, Position (lokale X/Y-Koordinaten in Metern relativ zur Ladestation), Blickrichtung, Zielzone und Verzögerung, basierend auf dem undokumentierten MQTT-Kanal `.../realtimeDate/location`.

## [0.1.1]

### Behoben

- Ein blockierender Aufruf im MQTT-Client (`client.tls_set()`, später auch `disconnect()`) lief direkt im Event-Loop von Home Assistant statt in einem Executor-Thread, was HAs eingebauter Blocking-Call-Detektor nach einem Neustart gemeldet hat. Beide laufen jetzt in einem Executor-Thread.

## [0.1.0]

### Hinzugefügt

- Erstveröffentlichung: eigene Home-Assistant-Integration für den Segway Navimow i220 LiDAR Pro, kombiniert REST-Polling mit MQTT-Push-Updates und einem Watchdog, der einen Reconnect erzwingt, wenn MQTT einen Zustandswechsel stillschweigend verpasst.
