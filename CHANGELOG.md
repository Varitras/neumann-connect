# Changelog

Alle nennenswerten Änderungen an dieser Integration werden hier dokumentiert.
Format lehnt sich an [Keep a Changelog](https://keepachangelog.com/) an.

## [1.15.1] – Bugfix

### Behoben
- Geänderte Werte sprangen in der Oberfläche kurz nach der Änderung auf den
  alten Stand zurück und blieben bis zu 5 Minuten falsch, obwohl der
  Lautsprecher den neuen Wert längst übernommen hatte. Betroffen waren die
  seltener abgefragten Einstellungen (u. a. Eingangsverstärkung,
  Ausgangspegel, Bass/Mitten/Höhen, Eingangswahl, Gerätename, beim
  Subwoofer zusätzlich Bass-Management, Kanal-B-Modus, Sub-Eingangspegel,
  Low Cut, Digital Bypass sowie die EQ-Ein/Aus-Schalter). Bestand seit der
  Poll-Aufteilung in 1.14.0

## [1.15.0] – Robustheit & Datenschutz

### Behoben / Abgehärtet
- Wird ein Poll-Zyklus durch das Zeitlimit abgebrochen, wird die
  Verbindung nun sauber verworfen. Verhindert, dass eine verspätet
  eintreffende Antwort einer späteren Abfrage zugeordnet wird und dort zu
  falschen Werten oder einem fälschlich übersprungenen Pfad führt
- Schreibaktionen (Pegel, Schalter, Auswahllisten, Gerätename, EQ,
  Werksreset u. a.) melden einen nicht erreichbaren Lautsprecher jetzt als
  klare Fehlermeldung, statt einen unbehandelten Fehler ins Protokoll zu
  schreiben
- Schlägt die erste Verbindung direkt nach dem Einrichten fehl (z. B. Gerät
  ausgeschaltet), wird die offene Netzwerkverbindung geschlossen, bevor
  Home Assistant den Einrichtungsversuch wiederholt
- Nach einem fehlgeschlagenen Abruf der selten abgefragten Werte werden
  diese beim nächsten erfolgreichen Zyklus sofort nachgeholt, statt bis zum
  regulären Intervall (5 min) auf zwischengespeicherte Werte zu warten

### Datenschutz
- Das Einstellungs-Backup enthält die Seriennummer nur noch zensiert – in
  der heruntergeladenen Datei und im Dateinamen (bislang nur bei der
  Geräte-Diagnose so). Die interne Zuordnung bleibt unverändert
- Dateinamen der Export-Dateien werden zusätzlich bereinigt, sodass sie den
  Export-Ordner unter keinen Umständen verlassen können

### Geändert
- Manuelle Einrichtung: Die IPv6-Adresse darf jetzt die Interface-Angabe
  direkt enthalten (z. B. `fe80::1%eth0`); ein separat gewähltes Interface
  hat weiterhin Vorrang. Zusätzlich wird der Port auf einen gültigen
  Bereich (1–65535) geprüft

## [1.14.0] – Effizienz & Robustheit

### Geändert
- Poll-Zyklus in schnelle und langsame Pfade aufgeteilt: veränderliche Werte
  werden weiterhin alle 30 s abgefragt, selten ändernde Werte (Geräte-
  Identität, statische Konfiguration, Ausgangs-Bezeichnungen, EQ-Status) nur
  noch alle 5 Minuten. Reduziert die Anzahl der Netzwerkabfragen pro Zyklus
  deutlich (KH 750 DSP: 47 → 23 pro schnellem Zyklus) und schafft mehr Abstand
  zum Zyklus-Zeitlimit. Zwischenzeitlich nicht neu abgefragte Werte bleiben
  über einen Cache erhalten (keine kurzzeitig "unbekannten" Entities)
- Eingangs-Interface (`audio/in/interface`) ist jetzt auch auf der KH 750 DSP
  standardmäßig aktiviert (bestätigt schreibbar auf KH 120 II und KH 750 DSP)

### Behoben / Abgehärtet
- Backup- und Discovery-Button sind gegen versehentliches Mehrfach-Auslösen
  abgesichert (ein bereits laufender Vorgang wird nicht erneut gestartet)
- Der Best-effort-Discovery-Durchlauf (`osc/schema`) hat jetzt ein
  Gesamt-Zeitlimit von 30 s und verwendet bei Überschreitung das bis dahin
  gesammelte Teilergebnis, statt unbegrenzt weiterzulaufen

## [1.13.1] – Doku-Korrektur

### Geändert
- README-Einleitung präzisiert: Die Geräte-Suche nutzt `zeroconf` über
  Home Assistants eingebaute Komponente (kein manuelles pip-Install
  nötig). Nur das SSC-Protokoll selbst kommt ohne jede
  Drittanbieter-Bibliothek aus (eigener asyncio-Client)

## [1.13.0] – Bugfix Verbindungsabbruch, erweiterte Modell-Erkennung, Aufräumen

### Behoben
- Ist der Lautsprecher nicht erreichbar, fing der generische
  Fehler-Handler pro Einzelpfad `SSCConnectionError`/`SSCTimeoutError` ab,
  statt sie an die äußere Behandlung weiterzureichen. Das führte zu
  Log-Flut und teils zum Überschreiten des Poll-Zyklus-Zeitlimits. Bricht
  jetzt sofort nach dem ersten fehlgeschlagenen Verbindungsversuch ab
- `storage.py` wieder zu einer Datei zusammengeführt - die drei
  `.storage/`-Ausgabedateien (`neumann_kh_names`, `neumann_kh_backups`,
  `neumann_kh_discovery`) bleiben davon unberührt

### Geändert
- `manifest.json`: `documentation`/`issue_tracker` zeigen jetzt auf das
  eigene Repository
- Modell-Erkennung erweitert: akzeptiert jetzt auch "KH 750 DSP" (nicht
  nur "KH 750"), sowie "KH 80 DSP", "KH 150 AES67", "KH 120 II AES67" für
  Logo-Helligkeit/Save-Settings (unverifiziert)
- README: neuer Abschnitt zu unterstützten/nicht unterstützten Modellen;
  IPv4-bezogene Anleitungstexte entfernt (Lautsprecher sind laut
  offizieller Doku IPv6-only)

## [1.12.0] – Bass Gain zu Diagnose, Speicher aufgeteilt

### Geändert
- `ui/bass_gain` (KH 120 II) von `select` (schreibbar) zu `sensor`
  (Diagnose, nur lesend) verschoben - nicht schreibbar, analog zu
  Mid Gain/Treble Gain
- `storage.py` in drei separate Module aufgeteilt: `name_storage.py`,
  `backup_storage.py`, `discovery_storage.py` - landen dadurch auch als
  drei separate Dateien unter `.storage/`

### Behoben
- `translations/en.json` war nach der Bass-Gain-Umstellung kurzzeitig
  nicht mit `strings.json` synchron

## [1.11.1] – EQ-Schalter auf Container-Ebene statt pro Band

### Geändert
- EQ-Ein/Aus-Schalter schalten jetzt alle Bänder eines Containers
  gemeinsam (ein SSC-Schreibvorgang für das komplette `enabled`-Array),
  statt einen Schalter pro einzelnem Band anzulegen - deutlich weniger
  Entities (4 statt 32 bei der KH 120 II, 14 statt 61 bei der KH 750 DSP)
- Alle EQ-Container-Namen beginnen jetzt einheitlich mit "EQ", damit sie
  in der "Konfiguration"-Sektion alphabetisch zusammen gruppiert
  erscheinen
- EQ-Schalter und Reset-Buttons sind jetzt standardmäßig aktiviert

## [1.11.0] – EQ-Unterstützung, Discovery-Anonymisierung

### Hinzugefügt
- EQ-Unterstützung: pro EQ-Container ein Ein/Aus-Schalter (SSC-Array-
  Teilschreiben) sowie ein "Auf neutral zurücksetzen"-Button (setzt Gain
  und Boost aller Bänder auf 0 dB). Abgedeckt: `eq2`/`eq3` am
  Hauptausgang, plus `eq1`/`eq2`/`eq3` an `out1`/`out2` bei der KH 750 DSP
- README: neue Übersichtstabelle, welche Entity-Typen schreibbar sind

### Geändert
- Seriennummer im Discovery-Export wird jetzt zensiert (nur die letzten
  3 Zeichen bleiben sichtbar)
- Backup und Discovery laufen ausschließlich manuell über die
  jeweiligen Buttons

## [1.10.0] – Namensgedächtnis, Backup & Geräte-Discovery

### Hinzugefügt
- Neuer dauerhafter Speicher (`storage.py`, ein Eintrag pro
  Seriennummer, unabhängig von Config Entries)
- Namensgedächtnis: zuletzt verwendeter Name pro Seriennummer wird beim
  erneuten Einrichten über die automatische Suche vorausgefüllt
  (zweistufiger Scan-Flow: erst Gerät wählen, dann Name bestätigen)
- "🔄 Erneut suchen" als Eintrag in der Scan-Auswahlliste
- "Backup erstellen"-Button: liest alle bekannten Werte (ohne
  Live-Messwerte) und speichert sie dauerhaft sowie als JSON-Datei
- "Geräte-Discovery ausführen"-Button (Diagnose): kombiniert bekannte
  Pfade mit einem Best-effort-Versuch über die optionalen SSC-Methoden
  `osc/schema` + `osc/limits`

## [1.9.0] – Nicht schreibbare Werte korrigiert, Bugfixes

### Geändert (KH 120 II, nicht schreibbar → jetzt Lesewert)
- Input Gain, Input Select, Mid Gain, Output Level (SPL), Treble Gain
- "Einstellungen speichern"-Button standardmäßig deaktiviert (nicht
  funktional)

### Geändert (KH 750 DSP, nicht schreibbar → jetzt Lesewert)
- Bass Management, Channel B Input Mode, Subwoofer Input Gain,
  Subwoofer Low-Cut, Subwoofer Output Level, Subwoofer Phase,
  Subwoofer Phase Inversion

### Behoben
- Ausgang-1/2-Stummschaltung (`out1_mute`/`out2_mute`, KH 750 DSP) fehlte
  komplett - wieder ergänzt
- `settle_time` in `ssc_client.py` nutzt jetzt die vorgesehene Konstante
  statt eines fest verdrahteten Werts
- Ungenutzte Konstante entfernt

### Aufgeräumt
- Code-Kommentare durchgängig gekürzt (kurz und fachlich)

## [1.8.1] – Bugfix: Geräte-Suche fand keine Lautsprecher mehr

### Behoben
- `discovery.py`: Parameternamen des mDNS-Callbacks `_on_change()`
  korrigiert (`zeroconf`, `service_type` - python-zeroconf ruft diesen
  Handler mit benannten Argumenten auf, nicht positional; eine
  Umbenennung führte zu `TypeError` und einer leeren Geräteliste)

## [1.8.0] – Reaktivität & Robustheit

### Hinzugefügt
- Priority-Pfad für Nutzeraktionen: Ein "set" (Schalter, Auswahl, Regler)
  drängelt sich jetzt zwischen zwei Einzelabfragen eines laufenden
  Poll-Zyklus, statt bis zu ~25s auf dessen Ende zu warten

### Geändert (Robustheit)
- Bestätigten Wert HA-idiomatisch einspielen: `_apply_confirmed_value()`
  nutzt `async_set_updated_data()` des Coordinators statt
  `coordinator.data` direkt zu mutieren
- Defensive Zahlkonvertierung: `number`-/`sensor`-Entities fangen
  nicht-numerische Gerätewerte ab (zeigen "unbekannt" statt eine
  Exception auszulösen)
- Verbindung wird beim Entladen immer geschlossen, auch wenn eine
  Plattform sich nicht sauber entladen lässt
- Korrekte Link-Local-Erkennung für den gesamten IPv6-Bereich fe80::/10
  (RFC 4291), nicht nur exaktes "fe80"-Präfix

## [1.7.0] – Bereits verbundene Lautsprecher in der Suche kennzeichnen

### Hinzugefügt
- Beim automatischen Netzwerk-Scan werden bereits eingerichtete
  Lautsprecher in der Auswahlliste mit "✓ bereits verbunden"
  gekennzeichnet

## [1.6.3] – Bugfix: binary_sensor-Setup schlug fehl

### Behoben
- `binary_sensor.py`: Zwei Entities übergaben `entity_category` als
  reinen String statt des von Home Assistant erwarteten
  `EntityCategory`-Enums - neuere HA-Versionen lehnen das ab

## [1.6.2] – Schalter/Auswahl springen nicht mehr kurz zurück

### Behoben
- Race Condition behoben: Nach einem "set" wird jetzt direkt der vom
  Gerät in derselben Antwort bereits bestätigte Wert übernommen, statt
  einen kompletten Poll-Zyklus anzustoßen. Neue gemeinsame Methode
  `NeumannKHEntity._apply_confirmed_value()`

## [1.6.1] – Auto-Standby-Korrektur: modellspezifisch, nicht universell

### Behoben
- Auto-Standby ist jetzt modellabhängig: Bei Nicht-Subwoofer-Modellen
  (KH 120 II etc.) ein schreibbarer `switch`, bei der KH 750 DSP bleibt
  es ein reiner `binary_sensor` (dort nicht schreibbar)

## [1.6.0] – Korrigierte Wertebereiche und neue Entities

### Korrigiert (Wertebereiche)
- Verzögerung: KH 120 II 0-5760 Samples, KH 750 DSP (Haupt/out1/out2)
  0-1000 Samples - jetzt modellabhängig
- Standby-Zeit: 1-240 min
- Standby-Schwellwert: -80 bis -55 dBu
- Logo-Helligkeit: 0-125 %
- Subwoofer-Eingangsverstärkung: -12 bis +2 dB
- Subwoofer-Low-Cut: -12 bis 0 dB

### Geändert (Number → Select, da feste Stufen statt kontinuierlichem Bereich)
- Bass/Mitten/Höhen (KH 120 II): jetzt `select` mit festen Stufen
- Subwoofer-Phase: jetzt `select` (0°/-45°/-90°/-135°)
- Subwoofer-Phaseninversion: jetzt `select` ("0"/"-180")

### Hinzugefügt
- Eingangsverstärkung (Nicht-Subwoofer) als schreibbares `number`
- Ausgangspegel SPL (Nicht-Subwoofer) als `select`
- Eingangsauswahl und Eingangs-Interface als `select`
- Steuerungsmodus (`select`, NETWORK/LOCAL) - standardmäßig deaktiviert
  (Sicherheits-Ausnahme)
- Gerätename (`text`, max. 52 Zeichen) - neue Plattform `text.py`
- "Werkseinstellungen wiederherstellen"-Button mit
  Zwei-Schritt-Sicherheitsabfrage
- Digitaler Bypass (`binary_sensor`, nur Subwoofer)
- Ausgangsbezeichnung Hauptausgang (`sensor`, nur Subwoofer)
- "UNKNOWN" bei Ausgang-1/2-Lautsprecher wird als "Nicht zugewiesen"
  angezeigt

### Geändert (Verhalten)
- "Identifizieren" ist jetzt ein Schalter (An/Aus) statt eines
  Auto-Stopp-Buttons
- "Auto-Standby" war in dieser Version kurzzeitig nur ein Lesewert
  (in 1.6.1 korrigiert, siehe oben)
- Alle KH-120-II-Entities sind jetzt standardmäßig aktiviert, außer
  "Dimm" und "Steuerungsmodus"

### Code-Härtung
- Gemeinsame Hilfsfunktionen (`_util.py`) statt doppelter
  Implementierung
- `ssc_client.py`: `asyncio.LimitOverrunError` wird abgefangen
- `coordinator.py`: Fehler bei einem Poll-Pfad reißt nicht mehr den
  gesamten Zyklus mit; Gesamt-Zeitlimit pro Poll-Zyklus ergänzt
- `config_flow.py`: leerer Name auch beim manuellen Setup abgelehnt
- Firmware-Version wird als `sw_version` im Geräte-Info angezeigt

## [1.5.0] – Subwoofer-Support (KH 750 DSP) und Code-Härtung

### Hinzugefügt (nur bei erkanntem Subwoofer)
- Zwei zusätzliche Ausgangskanäle `out1`/`out2`: Pegel, Verzögerung,
  Mute, sowie Bezeichnung und zugewiesener Lautsprechertyp (Diagnose)
- Subwoofer-Kalibrierung: Eingangsverstärkung, Low-Cut, Phase,
  Phaseninversion
- Subwoofer-Ausgangspegel als feste Auswahl 94/100/108/114 dB SPL
- Gerätetemperatur (`device_class: temperature`)
- Ausgangspegel-Metering und Ausgang-Clip-Anzeige
- Bass-Management-Modus, Kanal-B-Eingangsmodus (Diagnose)

### Geändert (Code-Härtung, alle Modelle)
- Gemeinsame Hilfsfunktionen (`_util.py`) statt doppelter Implementierung
- `ssc_client.py`: Schutz gegen unerwartet große/nie terminierte
  Geräteantworten
- `coordinator.py`: Fehler bei einem einzelnen Poll-Pfad reißt nicht
  mehr den gesamten Zyklus mit; Gesamt-Zeitlimit ergänzt
- `config_flow.py`: leerer Name auch beim manuellen Setup abgelehnt
- Firmware-Version wird als `sw_version` im Geräte-Info angezeigt

## [1.4.1] – Eigenes Icon/Logo

### Hinzugefügt
- Eigenständiges Marken-Design (`brand/`-Ordner): dunkles Anthrazit,
  stilisiertes Lautsprecher-Chassis-Symbol, Schriftzug
  "NEUMANN CONNECT". Voraussetzung: Home Assistant 2026.3 oder neuer

## [1.4.0] – Clip-Anzeige, Auto-Standby, Identify, Klangregler, Info-Sensoren

### Hinzugefügt
- Clip-Anzeige (`binary_sensor`) - zeigt an, wenn mindestens ein
  Eingangskanal übersteuert
- Auto-Standby - Ein/Aus-Schalter, Zeit- und Schwellwert-Regler sowie
  ein Countdown-Sensor
- "Gerät identifizieren"-Button - lässt das Logo/die LEDs kurz blinken
- Klangregler Bass/Mitten/Höhen als Number-Entities
- Info-/Diagnose-Sensoren: Gerätename, Hardware-Version, aktueller
  Eingang, Eingangs-Interface-Typ, Steuerungsmodus
- Warnungs-Sensor (`binary_sensor`)

## [1.3.2] – Entity-Standardwerte angepasst

### Geändert
- "Dimm" ist jetzt standardmäßig deaktiviert (existiert auf der
  KH 120 II nicht)
- "Eingangspegel (live)" ist jetzt standardmäßig aktiviert

## [1.3.1] – Fehlerbehandlung verbessert

### Geändert
- Coordinator fragt jetzt jeden Wert einzeln ab (ein Blattpfad pro
  SSC-Nachricht) statt containerweise
- Geräte-Identität wird nicht mehr bei jedem Poll-Zyklus wiederholt
  abgefragt
- Differenzierte Fehlerbehandlung: Ein genereller Verbindungsfehler
  lässt den ganzen Poll-Zyklus fehlschlagen; lehnt das Gerät nur einen
  einzelnen Pfad ab, wird nur dieser übersprungen

## [1.3.0] – SSC-Pfade korrigiert

### Geändert
- Coordinator fragt Werte containerweise ab (`device`, `ui`, `audio`,
  `m` als vier getrennte SSC-Nachrichten) statt in einer Sammelnachricht
- Korrigierte SSC-Pfade: Eingangsverstärkung (`ui/input_gain`),
  Phasenumkehr (`audio/out/phaseinversion`), Live-Pegelmessung
  (`m/in/level`, liefert eine Liste von Werten statt Einzelwert)
- `input_level_meter`-Sensor zeigt bei Listenwerten den lautesten Kanal an

### Entfernt
- `solo`-Switch (`audio/out/solo`) - vom Modell nicht unterstützt

### Hinzugefügt
- Neue Exception `SSCDeviceError`: erkennt vom Gerät abgelehnte
  Anfragen und wandelt sie in klare Fehlermeldungen um

## [1.2.0] – Aktive Netzwerksuche

### Hinzugefügt
- Einstiegsmenü im Config Flow: "Automatisch im Netzwerk suchen" oder
  "Manuell eingeben"
- Aktiver mDNS/Zeroconf-Scan über Home Assistants bestehende
  Zeroconf-Instanz, Ergebnis als Auswahlliste
- Bei automatisch gefundenen Geräten wird die IPv6-Scope-ID automatisch
  übernommen

## [1.1.0] – Interface-Auswahl als Dropdown

### Geändert
- Das Netzwerk-Interface-Feld im manuellen Setup ist jetzt ein Dropdown,
  mit Freitext-Fallback für nicht gelistete Interfaces

## [1.0.1] – Formular-Werte bleiben bei Fehlern erhalten

### Behoben
- Der Config Flow zeigte bei einem Fehler ein vollständig leeres
  Formular - bereits eingegebene Werte gingen verloren. Jetzt werden
  zuletzt eingegebene Werte als editierbare Vorschläge übernommen

## [1.0.0] – Erste Version

### Hinzugefügt
- Eigenständiger asyncio-SSC-Client (TCP Port 45, JSON-Protokoll)
- Config Flow (manuelle Eingabe: Name, IP-Adresse, Interface, Port)
- `DataUpdateCoordinator` mit 30-Sekunden-Poll-Intervall
- Entities: Ausgangspegel, Dimm, Verzögerung, Logo-Helligkeit (`number`);
  Stummschaltung, Phasenumkehr (`switch`); Eingangsverstärkung,
  Live-Eingangspegel (`sensor`); Einstellungen speichern (`button`)
- Modellerkennung: Logo-Helligkeit/Einstellungen-speichern nur bei
  KH 80/150/120 II, nicht bei KH 750 DSP
