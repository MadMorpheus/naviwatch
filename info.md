# NaviWatch — inoffizielle Navimow-Integration für Home Assistant

Eigenständige, inoffizielle Home-Assistant-Integration für Segway Navimow-Mähroboter — unabhängig entwickelt anhand des live beobachteten Segway-API-Verhaltens, kein Code aus dem offiziellen `navimow-sdk` übernommen.

## Warum diese Integration?

Bestehende Community-Integrationen für den i220 frieren nach ca. einer Stunde reproduzierbar ein und erholen sich nicht von selbst — nur ein manueller Reload hilft. Diese Integration wurde gezielt gebaut, um genau dieses Problem zu lösen:

- **Watchdog gegen Freeze**: vergleicht bei jedem REST-Poll den Status mit dem zuletzt per MQTT bekannten Zustand; bei Diskrepanz wird ein MQTT-Reconnect erzwungen (mit Debounce, damit derselbe anhaltende Mismatch nicht wiederholt unnötig reconnectet)
- Live über mehrere Stunden getestet, inklusive vollständigem Mähzyklus, automatisiertem Stopp und manuellem Docken — kein Freeze, kein manueller Eingriff nötig

## Features

- `lawn_mower`-Entity: Start, Pause, Dock
- Akku-Sensor
- MQTT-Verbindungsstatus als Diagnose-Sensor
- Hybrid aus REST-Poll (Ground Truth) und MQTT-Push (schnelle Updates innerhalb von Sekunden)
- Eigenes Icon/Logo, Deutsch/Englisch übersetzt

## Was diese Integration (bisher) NICHT kann

- **Keine Positions-/Kartendaten (Zonen)** — nach ausführlichem Live-Test über REST und alle bekannten MQTT-Kanäle beim i220 nicht erreichbar
- **Kein Mähfortschritt/Restzeit** — kein entsprechendes Feld in irgendeiner beobachteten API-Antwort

## Voraussetzungen

- Home Assistant (getestet mit Core 2026.5.4)
- Segway-Account, der sich in der offiziellen Navimow-App anmelden kann

## Installation

Noch nicht über HACS verfügbar — manuelle Installation:

1. `custom_components/navimow_custom/` nach `<config>/custom_components/navimow_custom/` kopieren
2. Home Assistant neu starten
3. Einstellungen → Geräte & Dienste → Integration hinzufügen → „NaviWatch" suchen

Nutzt intern weiterhin die Domain `navimow_custom` (aus der Testphase) und kann daher parallel zu anderen Navimow-Integrationen installiert werden, ohne Kollision — Parallelbetrieb ist aber optional, nicht zwingend.

---

*Inoffizielle Integration, nicht von Segway/Navimow autorisiert oder unterstützt. Unabhängig entwickelt anhand von Live-Tests gegen die reale API.*
