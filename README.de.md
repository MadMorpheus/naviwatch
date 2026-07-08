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

### Native Home Assistant Integration

* Native `lawn_mower`-Entity, volle Automations-Kompatibilität
* Eigenes Brand-Icon/Logo
* Übersetzt: Deutsch, Englisch

## Was diese Integration (bisher) NICHT kann

* **Keine Positions-/Kartendaten (Zonen)** — nach ausführlichem Live-Test über REST und alle bekannten MQTT-Kanäle nicht erreichbar
* **Kein Mähfortschritt/Restzeit** — kein entsprechendes Feld in irgendeiner beobachteten API-Antwort

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

Nach dem Einrichten (OAuth2-Login mit deinem Segway-Account) siehst du:

* Eine `lawn_mower`-Entity (Start/Pause/Dock)
* Einen Akku-`sensor`
* Einen `binary_sensor` für den MQTT-Verbindungsstatus

Das Poll-Intervall lässt sich über die Integrations-Optionen anpassen.

## Troubleshooting 🔧

* Zeigt der Watchdog wiederholt Reconnects in den Logs (`Navimow Watchdog: ...`)? Das ist normales Verhalten bei einem echten Zustandswechsel — bei anhaltend gleichem Mismatch greift ein 5-Minuten-Debounce, damit nicht unnötig wiederholt reconnectet wird.
* Stelle sicher, dass sich dein Account in der offiziellen Navimow-App anmelden lässt — die Integration nutzt denselben OAuth2-Flow.
* Bei Problemen: Home-Assistant-Logs auf Meldungen von `custom_components.navimow_custom` prüfen und ein Issue mit relevanten Log-Ausschnitten eröffnen: `https://github.com/MadMorpheus/naviwatch/issues`

## Lizenz

MIT — siehe [`LICENSE`](LICENSE).
