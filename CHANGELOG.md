# Changelog

Alle nennenswerten Änderungen an dieser Integration werden hier dokumentiert.
Format lehnt sich an [Keep a Changelog](https://keepachangelog.com/) an.

## [1.3.0] – Pfade korrigiert anhand echtem Hardware-Test (KH 120 II)

**Hintergrund:** Nach der Ersteinrichtung zeigten fast alle Entities
`unknown`, obwohl das Schreiben einzelner Werte (z. B. Logo-Helligkeit)
funktionierte. Ein realer `khtool`-Test auf einer KH 120 II (Firmware
1_7_3) hat die Ursache bestätigt: Referenziert eine SSC-Anfrage auch nur
einen nicht-existierenden Pfad, lehnt das Gerät die **gesamte** Nachricht ab
(`{"osc":{"error":[400,{"desc":"message not understood"}]}}`) – nicht nur
den fehlerhaften Teil.

### Geändert
- Coordinator fragt Werte jetzt **containerweise** ab (`device`, `ui`,
  `audio`, `m` als vier getrennte SSC-Nachrichten) statt in einer
  Sammelnachricht. Das Gerät expandiert einen Container selbst in alle
  vorhandenen Blätter – ein einzelner falscher/veralteter Pfad kann dadurch
  nie mehr die komplette Abfrage zum Scheitern bringen.
- Korrigierte SSC-Pfade (verifiziert gegen echten Hardware-Dump):
  - Eingangsverstärkung: `ui/input_gain` (statt fälschlich `audio/in/gain`)
  - Phasenumkehr: `audio/out/phaseinversion` (statt zwei getrennter,
    nicht existierender Pfade `audio/in/phase_invert` und
    `audio/out/phase_correction`)
  - Live-Pegelmessung: `m/in/level` (statt `m/audio`) – liefert eine
    **Liste** von Pegelwerten (einer pro Kanal), nicht mehr einen Einzelwert
- `input_level_meter`-Sensor zeigt bei Listenwerten den lautesten Kanal an

### Entfernt
- `solo`-Switch (`audio/out/solo`) – taucht im vollständigen
  Geräte-Dump der KH 120 II nicht auf, vom Modell/dieser Firmware offenbar
  nicht unterstützt

### Hinzugefügt
- Neue Exception `SSCDeviceError`: erkennt vom Gerät explizit abgelehnte
  Anfragen (OSC-Fehlerantworten) und wandelt sie in klare
  `HomeAssistantError`-Meldungen um, statt sie unbemerkt zu verschlucken
  (betrifft `number`, `switch`, `button`)
- Dokumentiert: `dimm` (`audio/out/dimm`) existiert auf der getesteten
  KH 120 II nachweislich nicht (isolierter Test, gleicher Fehler) – Entity
  bleibt bestehen (evtl. bei anderen Modellen wie KH 750 DSP vorhanden),
  zeigt bei fehlender Unterstützung `unknown` und wirft beim Setzen jetzt
  eine klare Fehlermeldung

## [1.2.0] – Aktive Netzwerksuche

### Hinzugefügt
- Einstiegsmenü im Config Flow: "Automatisch im Netzwerk suchen" oder
  "Manuell eingeben"
- Aktiver mDNS/Zeroconf-Scan (`_ssc._tcp.local.`) über Home Assistants
  bestehende Zeroconf-Instanz, Ergebnis als Auswahlliste
- Bei automatisch gefundenen Geräten wird die IPv6-Scope-ID automatisch aus
  der mDNS-Antwort übernommen – keine manuelle Interface-Auswahl nötig

## [1.1.0] – Interface-Auswahl als Dropdown

### Geändert
- Das Netzwerk-Interface-Feld im manuellen Setup ist jetzt ein Dropdown,
  befüllt über Home Assistants `network`-Komponente (inkl. IPv4/IPv6-Adressen
  je Interface als Label), mit Freitext-Fallback für nicht gelistete
  Interfaces

## [1.0.1] – Formular-Werte bleiben bei Fehlern erhalten

### Behoben
- Der Config Flow zeigte bei einem Fehler (z. B. falsche IP) ein
  vollständig leeres Formular – bereits eingegebene Werte gingen verloren.
  Jetzt werden zuletzt eingegebene Werte über
  `add_suggested_values_to_schema()` als editierbare Vorschläge
  übernommen.

## [1.0.0] – Erste Version

### Hinzugefügt
- Eigenständiger asyncio-SSC-Client (TCP Port 45, JSON-Protokoll) ohne
  Abhängigkeit auf `pyssc`/khtool
- Config Flow (manuelle Eingabe: Name, IP-Adresse, Interface, Port)
- `DataUpdateCoordinator` mit 30-Sekunden-Poll-Intervall
- Entities: Ausgangspegel, Dimm, Verzögerung, Logo-Helligkeit (`number`);
  Stummschaltung, Solo, Phasenumkehr Ein-/Ausgang (`switch`);
  Eingangsverstärkung, Live-Eingangspegel (`sensor`); Einstellungen
  speichern (`button`)
- Modellerkennung: Logo-Helligkeit/Einstellungen-speichern nur bei
  KH 80/150/120 II, nicht bei KH 750 DSP
