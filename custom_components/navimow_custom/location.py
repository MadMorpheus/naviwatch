"""Decoding for the undocumented MQTT '.../realtimeDate/location' channel.

Nicht Teil des offiziellen navimow-sdk (das abonniert nur state/event/attributes) und nicht
selbst live verifiziert - Herkunft: oeffentlich einsehbarer Code von pgoutsos/NavimowHA (Fork),
der dort erfolgreich Position/Zonen-Sensoren daraus baut. Eigenstaendig reimplementiert (siehe
dokumentation/sdk-notizen.md fuer die Einordnung), nicht aus deren Code uebernommen - nur die
Feldnamen/Nachrichtentypen sind Protokoll-Fakten, keine schuetzbare Ausdrucksform.

Payload ist ein JSON-**Array** (nicht Objekt) aus Eintraegen mit "type":
  1 = Pose: postureX/postureY (Meter, lokales kartesisches Koordinatensystem relativ zur
      Ladestation, KEIN GPS), postureTheta (Radiant), vehicleState
  2 = Fortschritt: currentMowBoundary (aktuelle physische Zone, aktualisiert erst beim
      Ueberqueren einer Zonengrenze), currentMowProgress (Routen-Fortschritt 0-10000,
      erreicht 10000 bei Abschluss - Planroute, nicht Flaechenabdeckung)
  3 = Zielzone: partitionIds (Ziel-Partition bei Mähstart gesetzt, fehlt bei "alles maehen")
  4 = Verzoegerung: taskDelay (Regen/Zeitplan)
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


def location_topic(device_id: str) -> str:
    return f"/downlink/vehicle/{device_id}/realtimeDate/location"


@dataclass
class LocationUpdate:
    """Nur die Felder, die sich durch eine einzelne Nachricht tatsaechlich geaendert haben."""

    pos_x: float | None = None
    pos_y: float | None = None
    pos_theta: float | None = None
    zone: int | None = None
    target_zone: int | None = None
    mow_progress_pct: int | None = None
    task_delay: bool | None = None


def parse_location_payload(data: Any) -> LocationUpdate | None:
    """Eine Location-Nachricht (JSON-Array) in ein LocationUpdate uebersetzen.

    Gibt None zurueck, wenn nichts Verwertbares enthalten war (z.B. leeres Array oder
    unbekannter Typ) - der Aufrufer soll dann NICHTS im gecachten Zustand ueberschreiben.
    """
    if not isinstance(data, list):
        return None

    update = LocationUpdate()
    changed = False
    for item in data:
        if not isinstance(item, dict):
            continue
        item_type = item.get("type")

        if item_type == 1:
            try:
                update.pos_x = float(item["postureX"])
                update.pos_y = float(item["postureY"])
                update.pos_theta = float(item["postureTheta"])
                changed = True
            except (TypeError, ValueError, KeyError):
                pass

        elif item_type == 2:
            if "currentMowBoundary" in item:
                update.zone = item.get("currentMowBoundary")
                changed = True
            if "currentMowProgress" in item:
                raw_progress = item.get("currentMowProgress")
                try:
                    update.mow_progress_pct = round(int(raw_progress) / 100)
                    changed = True
                except (TypeError, ValueError):
                    pass

        elif item_type == 3:
            partition_ids = item.get("partitionIds")
            if isinstance(partition_ids, list) and partition_ids:
                update.target_zone = partition_ids[0]
                changed = True

        elif item_type == 4:
            if "taskDelay" in item:
                update.task_delay = bool(item.get("taskDelay"))
                changed = True

    return update if changed else None
