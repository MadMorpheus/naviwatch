# Changelog

Alle relevanten Änderungen an NaviWatch werden in dieser Datei dokumentiert.

Das Format orientiert sich an [Keep a Changelog](https://keepachangelog.com/de/1.1.0/).

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
