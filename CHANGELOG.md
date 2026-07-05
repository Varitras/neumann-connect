# Changelog

Alle nennenswerten Änderungen an dieser Integration werden hier dokumentiert.
Format lehnt sich an [Keep a Changelog](https://keepachangelog.com/) an.

## [1.5.0] – Subwoofer-Support (KH 750) und Code-Härtung

**Hintergrund:** Ein echter `khtool -q`-Dump einer KH 750 (Firmware 2_1_2)
hat gezeigt, dass die KH 750 deutlich mehr subwooferspezifische SSC-Werte
hat als bisher angenommen - insbesondere zwei zusätzliche Bass-Management-
Ausgänge (`out1`/`out2`) für angeschlossene Zusatzlautsprecher.

### Hinzugefügt (nur bei erkanntem Subwoofer, Modell "KH 750")
- Zwei zusätzliche Ausgangskanäle `out1`/`out2`: Pegel, Verzögerung, Mute
  (`number`/`switch`), sowie Bezeichnung und zugewiesener Lautsprechertyp
  (`sensor`, Diagnose)
- Subwoofer-Kalibrierung: Eingangsverstärkung, Low-Cut, Phase (`number`,
  Wertebereiche unverifiziert), Phaseninversion (`switch`)
- Subwoofer-Ausgangspegel als feste Auswahl 94/100/108/114 dB SPL (`select`,
  neue Plattform - passender als `number`, da feste Stufen statt
  kontinuierlichem Bereich, analog zu dokumentierten SPL-Stufen anderer
  KH-Modelle)
- Gerätetemperatur (`sensor`, `device_class: temperature`) - Einheit als
  Kelvin angenommen (unverifiziert)
- Ausgangspegel-Metering und Ausgang-Clip-Anzeige (`sensor`/`binary_sensor`,
  Pendant zu den bestehenden Eingangs-Entities)
- Bass-Management-Modus, Kanal-B-Eingangsmodus (`sensor`, Diagnose)

### Geändert (Code-Härtung, alle Modelle)
- Gemeinsame Hilfsfunktionen (`_util.py`) statt doppelter Implementierung
  von `build_nested`/`deep_merge` in `ssc_client.py` und `coordinator.py`
- `ssc_client.py`: `asyncio.LimitOverrunError` wird jetzt abgefangen
  (Schutz gegen unerwartet große/nie terminierte Geräteantworten);
  `assert` durch explizite Prüfung mit klarer Fehlermeldung ersetzt
- `coordinator.py`: Ein unerwarteter Fehler bei einem einzelnen Poll-Pfad
  reißt nicht mehr den gesamten Poll-Zyklus mit, sondern wird geloggt und
  übersprungen; neues Gesamt-Zeitlimit für einen kompletten Poll-Zyklus
  (`POLL_CYCLE_TIMEOUT_SECONDS`)
- `config_flow.py`: Leerer Name wird jetzt auch beim manuellen Setup
  abgelehnt (vorher inkonsistent nur beim Scan-Schritt); ein unerwarteter
  Fehler beim mDNS-Scan führt zu einer klaren Fehlermeldung statt eines
  Absturzes
- `__init__.py`: `DEFAULT_PORT`-Konstante statt hartcodierter Zahl
- Firmware-Version wird beim Einrichten zusätzlich ausgelesen und als
  `sw_version` im Geräte-Info-Bereich angezeigt

## [1.4.1] – Eigenes Icon/Logo

### Hinzugefügt
- `brand/icon.png`, `brand/icon@2x.png`, `brand/logo.png`, `brand/logo@2x.png`
  - eigenständiges, selbst entworfenes Design (keine Kopie des offiziellen
  Neumann-Firmenlogos): dunkles Anthrazit, stilisiertes
  Lautsprecher-Chassis-Symbol, Schriftzug "NEUMANN CONNECT". Nutzt das seit
  Home Assistant 2026.3 verfügbare Feature, bei dem Custom Integrations
  ihre Marken-Bilder direkt im eigenen `brand/`-Ordner mitliefern können,
  ohne Eintrag im offiziellen `home-assistant/brands`-Repository.
  **Voraussetzung: Home Assistant 2026.3 oder neuer.**

## [1.4.0] – Neue Funktionen: Clip-Anzeige, Auto-Standby, Identify, Klangregler, Info-Sensoren

### Hinzugefügt
- **Clip-Anzeige** (`binary_sensor.input_clip`, `m/in/clip`) - zeigt an,
  wenn mindestens ein Eingangskanal übersteuert
- **Auto-Standby** - Ein/Aus-Switch (`device/standby/enabled`), Zeit- und
  Schwellwert-Number-Entities (`auto_standby_time`, `level`) sowie ein
  Countdown-Sensor (`countdown`); alle standardmäßig deaktiviert, da
  Wertebereiche nicht offiziell dokumentiert und nicht gegen echte Hardware
  verifiziert sind
- **"Gerät identifizieren"-Button** (`device/identification/visual`) -
  lässt das Logo/die LEDs kurz blinken, um den physischen Lautsprecher zu
  finden
- **Klangregler** Bass/Mitten/Höhen (`ui/bass_gain`, `mid_gain`,
  `treble_gain`) als Number-Entities, standardmäßig deaktiviert
  (Wertebereich unverifiziert). Werden vom Gerät als JSON-STRING geliefert
  (nicht als Zahl) - beim Schreiben entsprechend berücksichtigt
  (`value_is_string` in der Entity-Beschreibung)
- **Info-/Diagnose-Sensoren** (entity_category: diagnostic): Gerätename,
  Hardware-Version, aktueller Eingang, Eingangs-Interface-Typ,
  Steuerungsmodus
- **Warnungs-Sensor** (`binary_sensor.warning`, `warnings`) - "Problem",
  sobald das Gerät etwas anderes als `NO_WARNING` meldet

### Bewusst NICHT implementiert
- **Werksreset** (`device/restore`): Keine verifizierte Quelle für den
  korrekten Wert bei KH-Monitoren gefunden - der bekannte Wert
  (`FACTORY_DEFAULTS`/`AUDIO_DEFAULTS`) stammt aus der Doku eines anderen
  Sennheiser-Produkts (TeamConnect Ceiling 2). Neumanns offizieller Weg für
  einen Werksreset läuft ohnehin über eine physische Schalterfolge am Gerät,
  nicht über das Netzwerk - siehe README, Abschnitt "Bekannte Grenzen".

## [1.3.2] – Entity-Standardwerte angepasst

### Geändert
- "Dimm" (`number.output_dimm`) ist jetzt standardmäßig **deaktiviert** -
  existiert auf der KH 120 II nachweislich nicht (siehe 1.3.0/1.3.1),
  bleibt aber verfügbar für Modelle wie die KH 750 DSP, falls dort
  unterstützt
- "Eingangspegel (live)" (`sensor.input_level_meter`) ist jetzt
  standardmäßig **aktiviert** (vorher deaktiviert)

## [1.3.1] – Container-Abfragen funktionieren doch nicht

**Hintergrund:** Der 1.3.0-Fix (containerweises Polling, z. B. `{"device":null}`)
ging von der Annahme aus, dass eine Container-Abfrage automatisch alle
vorhandenen Blätter zurückgibt. Ein weiterer Hardware-Test hat gezeigt: Das
stimmt nicht - die Firmware lehnt auch Container-Abfragen ab
(`{"osc":{"error":[{"device":[404,{"desc":"address not found"}]}]}}`).
Setup schlug dadurch komplett fehl ("Failed setup, will retry").

### Geändert
- Coordinator fragt jetzt **jeden Wert einzeln** ab (ein Blattpfad pro
  SSC-Nachricht) - der einzige bisher zuverlässig bestätigte Ansatz,
  passend zu khtools eigenem Vorgehen (modellspezifische Liste bekannter
  Einzelpfade, siehe `khtool_commands.json`)
- Geräte-Identität (Hersteller/Modell/Seriennummer) wird nicht mehr bei
  jedem Poll-Zyklus wiederholt abgefragt - sie ändert sich zur Laufzeit
  nicht und ist bereits einmalig beim Einrichten in den Config-Entry-Daten
  gespeichert
- Differenzierte Fehlerbehandlung: Ein genereller Verbindungsfehler lässt
  den ganzen Poll-Zyklus fehlschlagen; lehnt das Gerät dagegen nur EINEN
  einzelnen, nicht unterstützten Pfad ab (z. B. `dimm` auf der KH 120 II),
  wird nur dieser übersprungen - die übrigen Werte werden trotzdem
  aktualisiert

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
