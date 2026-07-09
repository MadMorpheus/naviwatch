# NaviWatch

🇬🇧 [English](README.md) | 🇩🇪 Deutsch

Inoffizielle Home Assistant-Integration für Segway Navimow-Mähroboter.

[![Open your Home Assistant instance and open a repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=MadMorpheus&repository=naviwatch&category=Integration)

Eigenständig entwickelt anhand des live beobachteten Segway-API-Verhaltens — kein Code aus dem offiziellen `navimow-sdk` übernommen, keine Abhängigkeit zu anderen Navimow-Integrationen.

## Warum diese Integration? 🐛→✅

Bestehende Community-Integrationen frieren nach ca. einer Stunde reproduzierbar ein und erholen sich nicht von selbst — nur ein manueller Reload hilft. NaviWatch löst genau dieses Problem mit einem eingebauten Watchdog:

* Vergleicht bei jedem REST-Poll den Status mit dem zuletzt per MQTT bekannten Zustand
* Bei Diskrepanz wird ein MQTT-Reconnect erzwungen
* Debounce verhindert, dass derselbe anhaltende Mismatch wiederholt unnötig reconnectet
* Live über mehrere Stunden getestet, inklusive vollständigem Mähzyklus, automatisiertem Stopp und manuellem Docken — kein Freeze, kein manueller Eingriff nötig

## Features ✨

### Mower Control

* Start mowing
* Pause mowing
* Send mower to dock

### Device Monitoring

* Echtzeit-Mähstatus (`lawn_mower`-Entity)
* Akku-Sensor
* MQTT-Verbindungsstatus als Diagnose-Sensor

### Real-Time Communication

* Hybrid aus REST-Poll (Ground Truth) und MQTT-Push
* MQTT-Updates reagieren innerhalb von Sekunden auf echte Zustandswechsel

### Zone, Fortschritt & Position 🗺️

* Aktuelle Mäh-Zone, Routen-Fortschritt (0–100 %, live bestätigt exakt übereinstimmend mit der offiziellen App), Position (lokale X/Y-Koordinaten in Metern), Blickrichtung und Abstand zur Ladestation
* Stammt aus einem undokumentierten MQTT-Kanal, gefunden durch Einsicht in den Quellcode eines Drittanbieter-Forks — siehe [Bekannte Risiken](#bekannte-risiken--das-könnte-kaputtgehen-und-liegt-nicht-in-meiner-hand-)

### Native Home Assistant Integration

* Native `lawn_mower`-Entity, volle Automations-Kompatibilität
* Eigenes Brand-Icon/Logo
* Übersetzt: Deutsch, Englisch

## Prerequisites 📋

* Home Assistant, getestet mit Core **2026.5.4** (empfohlen ≥ 2026.3 für lokale Brand-Icons)
* Segway-Account, der sich in der offiziellen Navimow-App anmelden kann

## Installation 🛠️

Diese Integration ist nicht im HACS-Standardstore — sie muss als Custom Repository hinzugefügt werden:

1. HACS → Integrations → Menü oben rechts → **Custom repositories**
2. Repository: `https://github.com/MadMorpheus/naviwatch`
3. Category: **Integration**
4. Nach `NaviWatch` suchen und installieren
5. Home Assistant neu starten
6. Einstellungen → Geräte & Dienste → Integration hinzufügen → `NaviWatch` suchen

**Manuelle Installation** (alternativ, ohne HACS):

1. `custom_components/navimow_custom/` aus diesem Repo nach `<config>/custom_components/navimow_custom/` kopieren
2. Home Assistant neu starten
3. Einstellungen → Geräte & Dienste → Integration hinzufügen → `NaviWatch` suchen

Nutzt intern die Domain `navimow_custom` und kann daher parallel zu anderen Navimow-Integrationen installiert werden, ohne Kollision — Parallelbetrieb ist optional, nicht zwingend.

## Schon eine andere Navimow-Integration installiert? 🔀

NaviWatch nutzt eine eigene Domain (`navimow_custom`) und **kann parallel** zur offiziellen `segwaynavimow/NavimowHA`-Integration (oder Forks davon) laufen, ohne Konflikt — nichts muss vorher entfernt werden.

* **Beide behalten**: sinnvoll während der Testphase — du bekommst einen zweiten Satz Entitäten (Home Assistant hängt bei Namenskollision automatisch `_2` an), sodass du das Verhalten vergleichen kannst, bevor du dich festlegst.
* **Ganz umsteigen**: sobald du NaviWatch vertraust, entferne die andere Integration über Einstellungen → Geräte & Dienste → dort auswählen → Drei-Punkte-Menü → **Löschen**. Danach Automationen/Dashboards, die auf die alten Entity-IDs verweisen, auf die NaviWatch-Entitäten umstellen (Einstellungen → Geräte & Dienste → NaviWatch → Geräteseite zeigt die aktuellen Entity-IDs).
* Es gibt keine automatische Migration von Einstellungen oder Verlaufsdaten zwischen den beiden Integrationen — jede behält ihre eigenen Entitäten und ihren eigenen Verlauf.

## Usage 🎮

Nach dem Einrichten (OAuth2-Login mit deinem Segway-Account) bekommst du ein Gerät mit folgenden Entitäten:

| Entität | Wofür |
|---|---|
| `lawn_mower` | Die Haupt-Entity. State ist einer von `mowing`, `paused`, `returning`, `docked`, `error`. Unterstützt Start/Pause/Dock. Diagnose-Attribute (`raw_state`, `mqtt_connected`, `last_rest_update`, `last_mqtt_update`) zeigen, ob der Watchdog aktiv ist. |
| Akku-`sensor` | Batteriestand in Prozent. |
| MQTT-Verbindung `binary_sensor` (Diagnose) | Ob der schnelle MQTT-Push-Pfad gerade verbunden ist. Kein Hinweis auf generelle Erreichbarkeit — der REST-Poll hält die Haupt-Entity unabhängig davon aktuell. |
| Zone-`sensor` | Aktuelle physische Mäh-Zone/Partition-ID. Das ist eine **interne, von Segways Backend vergebene ID**, nicht identisch mit den "Zone 1"/"Zone 2"-Bezeichnungen in der App (live bestätigt: zwei echte Zonen zeigten die IDs `9` und `4`). **Diese IDs sind nicht fortlaufend/vorhersagbar** — bevor du Automationen für eine bestimmte Zone baust, starte jede Zone einmal über die App und notiere die erscheinende ID (Entwicklerwerkzeuge → Zustände, oder der State der Entity im Dashboard). Attribute: `target_zone` (bei Mähstart gewählte Zone), `task_delay` (Regen-/Zeitplan-Verzögerung). |
| Mähfortschritt-`sensor` | Routen-Fortschritt der aktuellen Aufgabe, 0–100 % (keine Flächenabdeckung). Live bestätigt: stimmt exakt mit dem in der offiziellen App angezeigten Prozentwert überein. |
| Position X / Position Y `sensor` | Lokale kartesische Koordinaten in Metern, relativ zur Ladestation — **kein GPS**. Nützlich für eigene Automationen, z. B. selbst definierte Teilbereiche oder Erkennung, ob sich der Mäher länger nicht bewegt hat. |
| Abstand zur Ladestation `sensor` | Abgeleitete (`sqrt(x² + y²)`) Luftlinien-Entfernung von der Ladestation in Metern. Dient nebenbei als Stillstands-/Freeze-Signal — ein unveränderter Wert trotz `state=mowing` ist verdächtig. |
| Blickrichtung `sensor` | Aktuelle Ausrichtung des Mähers in Grad (0–360°). Bezieht sich auf dasselbe lokale Koordinatensystem wie Position X/Y — kein Kompass. |

**Zone, Mähfortschritt, Position, Abstand und Blickrichtung stammen alle aus einem undokumentierten MQTT-Kanal**, gefunden durch Einsicht in den Quellcode eines Drittanbieter-Forks, nicht aus der offiziellen API — siehe [Bekannte Risiken](#bekannte-risiken--das-könnte-kaputtgehen-und-liegt-nicht-in-meiner-hand-) dazu, was das für die langfristige Zuverlässigkeit bedeutet.

Das Poll-Intervall lässt sich über die Integrations-Optionen anpassen.

Interessiert, wann/wie oft genau welche Entität aktualisiert wird? Siehe [ARCHITECTURE.md](ARCHITECTURE.md) (Englisch).

## Troubleshooting 🔧

* Zeigt der Watchdog wiederholt Reconnects in den Logs (`Navimow Watchdog: ...`)? Das ist normales Verhalten bei einem echten Zustandswechsel — bei anhaltend gleichem Mismatch greift ein 5-Minuten-Debounce, damit nicht unnötig wiederholt reconnectet wird.
* Stelle sicher, dass sich dein Account in der offiziellen Navimow-App anmelden lässt — die Integration nutzt denselben OAuth2-Flow.
* Bei Problemen: Home-Assistant-Logs auf Meldungen von `custom_components.navimow_custom` prüfen und ein Issue mit relevanten Log-Ausschnitten eröffnen: `https://github.com/MadMorpheus/naviwatch/issues`

## Bekannte Risiken — das könnte kaputtgehen, und liegt nicht in meiner Hand ⚠️

Das ist ein unabhängiges, inoffizielles Hobbyprojekt ohne Partnerschaft oder Support-Vereinbarung mit Segway. Ungefähr absteigend nach Wahrscheinlichkeit:

1. **Segway ändert etwas am Backend.** Keine Garantie auf API-Stabilität. Am fragilsten ist der **undokumentierte** MQTT-Kanal `location` (Zonen-/Fortschrittsdaten) — reverse-engineered aus einem Fremd-Fork, kein Teil einer offiziellen API, könnte sich jederzeit ohne Vorwarnung ändern oder verschwinden. Die Kernfunktionen (Status, Akku, Start/Pause/Dock) nutzen dieselben Endpunkte wie die offizielle App — etwas stabiler, aber ebenfalls ohne Garantie.
2. **Segway rotiert oder sperrt den geteilten OAuth-Client** (`client_id`/`client_secret`, ein "public client", den jede Community-Integration dieser Art nutzt). Falls das je eingeschränkt wird, bräuchten alle inoffiziellen Integrationen — auch diese — neue Zugangsdaten.
3. **Home-Assistant-Core-Änderungen.** Das OAuth2-Framework oder die `DataUpdateCoordinator`-API könnten sich in einer künftigen Major-Version ändern. HAs Blocking-Call-Detektor wird zudem tendenziell strenger und könnte künftig bisher unbemerkte Probleme aufdecken.
4. **Änderungen an der `paho-mqtt`-Bibliothek.** Diese Integration nutzt bewusst die ältere `CallbackAPIVersion.VERSION1`-API, die eine künftige Major-Version entfernen könnte.
5. **Mäher-Firmware-Updates.** Neue oder geänderte `vehicleState`-Werte (es gibt schon einen bekannten Firmware-Tippfehler, `isIdel`) könnten außerhalb der aktuellen Zuordnung liegen.

**Kurz gesagt:** Das ist ein Soloprojekt ohne Herstellerbeziehung und ohne aktives Monitoring seitens Segway. Falls sich stromaufwärts etwas ändert, fällt die Integration vermutlich still aus (Fehler im Log), bis es jemand bemerkt und den Code anpasst — es gibt keine Garantie auf einen Fix, erst recht nicht in einem bestimmten Zeitrahmen.

## Lizenz

MIT — siehe [`LICENSE`](LICENSE).
