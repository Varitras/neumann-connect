# Changelog

Alle nennenswerten Änderungen an dieser Integration werden hier dokumentiert.
Format lehnt sich an [Keep a Changelog](https://keepachangelog.com/) an.

## [1.8.1] – Bugfix: Geräte-Suche fand keine Lautsprecher mehr

**Hintergrund:** In 1.8.0 wurden die Parameter des mDNS-Callbacks
`_on_change()` in `discovery.py` rein kosmetisch zu `_zeroconf`/
`_service_type` umbenannt. Das war ein Fehler: python-zeroconf ruft diesen
Handler mit BENANNTEN Argumenten auf (`zeroconf=...`, `service_type=...`),
nicht rein positional - die Parameternamen müssen deshalb exakt passen. Nach
der Umbenennung scheiterte jeder Aufruf mit einem `TypeError`, wodurch die
Geräteliste beim Scannen leer blieb ("keine Lautsprecher gefunden").

### Behoben
- `discovery.py`: Parameternamen des `_on_change()`-Handlers zurück auf
  `zeroconf`, `service_type` (exakt wie von python-zeroconf erwartet).
  Codebasisweit geprüft: keine weiteren Stellen mit diesem Callback-Muster
  betroffen.

## [1.8.0] – Reaktivität & Robustheit

### Hinzugefügt
- **Priority-Pfad für Nutzeraktionen:** Ein "set" (z. B. Schalter, Auswahl,
  Regler) drängelt sich jetzt zwischen zwei Einzelabfragen eines laufenden
  Poll-Zyklus hinein, statt bis zu ~25s auf dessen Ende zu warten. Der Poll
  gibt den Verbindungs-Lock nach seiner aktuellen Einzelabfrage kurz frei,
  sobald eine Nutzeraktion darauf wartet (`SSCClient.priority_waiting`).
  Schalter reagieren dadurch spürbar direkter, ohne dass parallele Zugriffe
  auf denselben Socket entstehen (die Verbindung bleibt sauber serialisiert).

### Geändert (Robustheit)
- **Bestätigten Wert HA-idiomatisch einspielen:** `_apply_confirmed_value()`
  nutzt jetzt den offiziellen `async_set_updated_data()`-Weg des Coordinators
  (auf einer Kopie der Daten) statt `coordinator.data` direkt zu mutieren -
  vermeidet subtile Races mit dem Listener-Mechanismus und benachrichtigt
  alle gebundenen Entities konsistent.
- **Defensive Zahlkonvertierung:** `number`- und `sensor`-Entities fangen
  nicht-numerische Gerätewerte jetzt ab (zeigen "unbekannt" statt eine
  Exception im Statusabgleich auszulösen). Bei Live-Pegel-Listen werden nur
  tatsächlich numerische Einträge für die max()-Auswertung berücksichtigt.
- **Verbindung immer schließen:** `async_unload_entry` schließt die
  TCP-Verbindung jetzt auch dann, wenn das Entladen einer Plattform
  fehlschlägt - kein offener Socket bleibt zurück.
- **Korrekte Link-Local-Erkennung:** Die Scope-ID wird jetzt für den
  gesamten IPv6-Link-Local-Bereich fe80::/10 (fe80–febf) angehängt, nicht
  nur bei exakt "fe80"-Präfix (RFC 4291). Mit Grenzfall-Tests abgesichert.

### Aufgeräumt
- `discovery.py`: ungenutzte Callback-Parameter mit "_" markiert (kosmetisch).

## [1.7.0] – Bereits verbundene Lautsprecher in der Suche kennzeichnen

### Hinzugefügt
- Beim automatischen Netzwerk-Scan (Config Flow) werden bereits
  eingerichtete Lautsprecher jetzt in der Auswahlliste mit
  "✓ bereits verbunden" gekennzeichnet (Abgleich über die Seriennummer
  gegen bestehende Config Entries). Sie bleiben auswählbar, der
  eigentliche Schutz vor echten Duplikaten läuft weiterhin über die
  bestehende Prüfung bei der tatsächlichen Auswahl.

## [1.6.3] – Bugfix: binary_sensor-Setup schlug fehl (entity_category)

**Hintergrund:** Home Assistant meldete beim Laden der Integration
"Error adding entity ... for domain binary_sensor" mit
`ValueError: entity_category must be a valid EntityCategory instance, got diagnostic`.

### Behoben
- `binary_sensor.py`: Zwei Entities ("Warnung" und "Digitaler Bypass")
  übergaben `entity_category="diagnostic"` als reinen String statt des von
  Home Assistant erwarteten `EntityCategory.DIAGNOSTIC`-Enums - neuere
  HA-Versionen validieren das jetzt strikt und lehnen den String ab.
  `sensor.py` verwendete bereits korrekt das Enum, nur `binary_sensor.py`
  war betroffen. Codebasisweit geprüft: keine weiteren Stellen mit diesem
  Muster.

## [1.6.2] – Schalter/Auswahl springen nicht mehr kurz zurück (Race Condition behoben)

**Hintergrund:** Nach dem Betätigen eines Schalters/einer Auswahl (z. B.
Auto-Standby, Identifizieren) sprang die Anzeige kurz auf den alten Wert
zurück, bevor sie nach einigen Sekunden wieder korrekt wurde. Ursache: Nach
jedem "set" wurde ein kompletter Poll-Zyklus (20+ Einzelabfragen)
angestoßen. Wurde dabei ausgerechnet der gerade geänderte Wert abgefragt,
BEVOR das Gerät ihn intern vollständig übernommen hatte, kam kurzzeitig der
alte Wert zurück.

### Behoben
- `number`/`select`/`switch`/`text`: Nach einem "set" wird jetzt direkt der
  vom Gerät in DERSELBEN Antwort bereits bestätigte Wert übernommen, statt
  einen kompletten (langsameren) Poll-Zyklus anzustoßen. Das vermeidet die
  Race Condition komplett und ist zusätzlich spürbar schneller. Neue
  gemeinsame Methode `NeumannKHEntity._apply_confirmed_value()` in
  `entity.py`. Liefert das Gerät ausnahmsweise keinen eindeutigen Wert
  zurück, wird sicherheitshalber weiterhin ein normaler Refresh angestoßen.

## [1.6.1] – Auto-Standby-Korrektur: modellspezifisch, nicht universell

**Hintergrund:** In 1.6.0 wurde Auto-Standby fälschlich für ALLE Modelle zu
einem reinen Lesewert (`binary_sensor`) gemacht. Grund war eine
Übergeneralisierung: Die beiden Schreibfehler (405 "method not allowed" bei
`device/standby/enabled`, 400 "message not understood" bei `ui/auto_standby`)
wurden ausschließlich gegen die KH 750 getestet - nie gegen die KH 120 II.
Der Nutzer hat bestätigt, dass Auto-Standby auf seiner KH 120 II tatsächlich
funktioniert.

### Behoben
- Auto-Standby ist jetzt **modellabhängig**:
  - **Nicht-Subwoofer-Modelle (KH 120 II etc.):** wieder ein schreibbarer
    `switch` (`device/standby/enabled`)
  - **KH 750:** bleibt ein reiner `binary_sensor` (nur dort per Hardware-Test
    bestätigt nicht schreibbar)
- README und Code-Kommentare korrigiert: Die Lehre aus diesem Vorfall ist
  jetzt explizit dokumentiert - ein Testergebnis auf einem Modell lässt sich
  nicht automatisch auf ein anderes Modell übertragen.

## [1.6.0] – Korrekturen anhand khtools interner Metadaten-Datenbank

**Hintergrund:** Der Nutzer hat khtools interne `khtool_commands.json`
bereitgestellt - strukturierte Metadaten (Typ, schreibbar ja/nein, Min/Max,
exakte Optionen) für KH 120 II (Firmware 1_7_3) und KH 750 (Firmware
2_1_2). Das ist eine deutlich zuverlässigere Quelle als die bisherigen
Schätzwerte, ABER ein echter Hardware-Test (`ui/auto_standby`) hat gezeigt,
dass diese Datei nicht immer mit dem tatsächlichen Geräteverhalten
übereinstimmt - siehe README "Bekannte Grenzen".

### Korrigiert (Wertebereiche)
- Verzögerung: KH 120 II 0-**5760** Samples (statt 3360), KH 750 (Haupt/
  out1/out2) 0-**1000** Samples (statt 3360) - jetzt modellabhängig
- Standby-Zeit: 1-**240** min (statt 1-90)
- Standby-Schwellwert: **-80 bis -55 dBu** (statt -90-0 dB, andere Einheit!)
- Logo-Helligkeit: 0-**125** % (statt 0-100)
- Subwoofer-Eingangsverstärkung: **-12 bis +2** dB (statt ±12)
- Subwoofer-Low-Cut: **-12 bis 0** dB (statt ±12)

### Geändert (Number → Select, da feste Stufen statt kontinuierlichem Bereich)
- Bass/Mitten/Höhen (KH 120 II): jetzt `select` mit den tatsächlichen festen
  Stufen (Bass/Mitten: -6/-4/-2/0 dB, Höhen: -2/-1/0/1 dB) statt Schieberegler
- Subwoofer-Phase: jetzt `select` mit den tatsächlichen Werten
  0°/-45°/-90°/-135° (statt kontinuierlichem 0-180°-Bereich)
- Subwoofer-Phaseninversion: jetzt `select` mit den tatsächlichen Werten
  "0"/"-180" (statt `switch` mit angenommenem "0"/"1")

### Hinzugefügt
- **Eingangsverstärkung** (`ui/input_gain`, Nicht-Subwoofer) als
  schreibbares `number` (-15-0 dB) statt nur lesendem Sensor
- **Ausgangspegel SPL** (`ui/output_level`, Nicht-Subwoofer) als neues
  `select` (94/100/108/114 dB SPL) - Pendant zum Subwoofer-Ausgangspegel
- **Eingangsauswahl** (`select`, `ui/input_select`) und **Eingangs-
  Interface** (`select`, `audio/in/interface`) - Wertebereiche jetzt
  bekannt, Schreibbarkeit aber weiterhin unverifiziert (mit falschen
  Testwerten real abgelehnt)
- **Steuerungsmodus** (`select`, `ui/control_mode`, NETWORK/LOCAL) - immer
  standardmäßig deaktiviert (Sicherheits-Ausnahme: Risiko, sich vom Gerät
  auszusperren)
- **Gerätename** (`text`, `device/name`, max. 52 Zeichen) - neue Plattform
  `text.py`
- **"Werkseinstellungen wiederherstellen"-Button** (`device/restore`) mit
  bestätigtem Wert `"FACTORY_DEFAULTS"` - trotzdem mit
  Zwei-Schritt-Sicherheitsabfrage umgesetzt (erster Druck "bewaffnet" nur,
  zweiter Druck innerhalb 30s löst tatsächlich aus)
- **Digitaler Bypass** (`binary_sensor`, `audio/digital_bypass`, nur
  Subwoofer)
- **Ausgangsbezeichnung Hauptausgang** (`sensor`, `audio/out/label`, nur
  Subwoofer)
- "UNKNOWN" bei Ausgang-1/2-Lautsprecher wird jetzt als "Nicht zugewiesen"
  angezeigt

### Geändert (Verhalten)
- **"Identifizieren"** ist jetzt ein **Schalter** (An/Aus) statt eines
  Auto-Stopp-Buttons: Ein Hardware-Test zeigte, dass das Blinken erst nach
  mehreren Minuten von selbst aufhört, nicht nach ~10 Sekunden
- **"Auto-Standby"** ist nur noch ein reiner Lesewert (`binary_sensor`),
  kein Schalter mehr: Per zwei unabhängigen Hardware-Tests bestätigt nicht
  schreibbar (Fehler 405 bzw. 400 bei zwei verschiedenen Pfaden), obwohl
  khtools Metadaten `device/standby/enabled` als schreibbar listen
- **Alle KH-120-II-Entities sind jetzt standardmäßig aktiviert**, außer
  "Dimm" (existiert dort nicht) und "Steuerungsmodus" (bewusste
  Sicherheits-Ausnahme)

### Code-Härtung
- Gemeinsame Hilfsfunktionen (`_util.py`) statt doppelter Implementierung
  von `build_nested`/`deep_merge` in `ssc_client.py` und `coordinator.py`
- `ssc_client.py`: `asyncio.LimitOverrunError` wird abgefangen; `assert`
  durch explizite Prüfung ersetzt
- `coordinator.py`: unerwarteter Fehler bei einem Poll-Pfad reißt nicht
  mehr den gesamten Zyklus mit; neues Gesamt-Zeitlimit pro Poll-Zyklus
  (`POLL_CYCLE_TIMEOUT_SECONDS`)
- `config_flow.py`: leerer Name auch beim manuellen Setup abgelehnt;
  mDNS-Scan-Fehler führen zu klarer Meldung statt Absturz
- `__init__.py`: `DEFAULT_PORT`-Konstante statt hartcodierter Zahl
- Firmware-Version wird beim Einrichten zusätzlich gespeichert und als
  `sw_version` im Geräte-Info angezeigt

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
