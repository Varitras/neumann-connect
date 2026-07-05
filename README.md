# Neumann Connect – Home Assistant Custom Component

Steuert Neumann KH DSP Lautsprecher (KH 80, KH 120 II, KH 150, KH 750 DSP)
über das Sennheiser Sound Control Protocol (SSC), TCP Port 45. Kein
Fremdpaket nötig – ein schlanker eigener asyncio-Client ist enthalten.

Änderungshistorie: siehe [CHANGELOG.md](./CHANGELOG.md).

Eigenes Icon/Logo unter `custom_components/neumann_kh/brand/` (eigenständiges
Design, keine Kopie des offiziellen Neumann-Firmenlogos). Benötigt **Home
Assistant 2026.3 oder neuer** (erst ab dieser Version lesen Custom
Integrations ihre Marken-Bilder direkt aus einem eigenen `brand/`-Ordner,
siehe [HA Developer Blog](https://developers.home-assistant.io/blog/2026/02/24/brands-proxy-api/)). Bei älteren Versionen wird stattdessen ein generisches Icon angezeigt.

Basiert auf den SSC-Adresspfaden, die im
[khtool-Projekt](https://github.com/schwinn/khtool) dokumentiert sind.

## Einrichtung

1. Ordner `custom_components/neumann_kh` in dein Home-Assistant-Konfigurationsverzeichnis kopieren
   (z. B. `/config/custom_components/neumann_kh`).
2. Home Assistant neu starten.
3. **Einstellungen → Geräte & Dienste → Integration hinzufügen → "Neumann KH (SSC)"**.
4. Du bekommst ein Menü mit zwei Wegen:
   - **"Automatisch im Netzwerk suchen"** – aktiver mDNS-Scan (siehe unten),
     Ergebnis als Auswahlliste. Empfohlener Standardweg.
   - **"Manuell eingeben"** – IP-Adresse, Interface-Dropdown, Port (Fallback,
     falls die automatische Suche ein Gerät nicht findet).
5. Für **jeden** Lautsprecher einen eigenen Eintrag anlegen (z. B. "KH 120 II Links",
   "KH 120 II Rechts", "KH 750 DSP Sub 1", "KH 750 DSP Sub 2").

## Automatische Suche (mDNS/Zeroconf)

Neumann-KH-Lautsprecher machen sich laut SSC-Spezifikation per mDNS/Bonjour
im Netzwerk bekannt (Dienst-Typ `_ssc._tcp.local.`) – genau wie z. B.
AirPlay-Geräte. Die Integration nutzt Home Assistants ohnehin laufende
Zeroconf-Instanz, um für einige Sekunden aktiv danach zu suchen, und zeigt
gefundene Geräte (Modell, IP-Adresse, Seriennummer) zur Auswahl an.

**Vorteil bei IPv6 Link-Local:** Die gefundene Adresse enthält die
Scope-ID bereits automatisch (z. B. `fe80::...%3`) – bei automatisch
gefundenen Geräten musst du das Netzwerk-Interface **nicht** manuell
angeben.

**Wird nichts gefunden:** Formular einfach ohne Auswahl erneut absenden,
um die Suche zu wiederholen – oder zurück ins Menü gehen und "Manuell
eingeben" wählen. mDNS funktioniert nur zuverlässig, wenn HA multicast-mäßig
im selben Netzwerksegment wie die Lautsprecher hängt (bei Docker z. B.
`network_mode: host` nötig) – dieselbe Voraussetzung, die für die
Link-Local-Verbindung ohnehin gilt.

## IPv6 Link-Local Adresse & Interface ermitteln (nur für "Manuell eingeben")

Die Lautsprecher sind per Default nur über ihre IPv6 Link-Local-Adresse
(`fe80::...`) erreichbar. Diese benötigt zwingend eine **Scope-ID**
(Netzwerk-Interface), sonst kann kein Betriebssystem die Route auflösen.

**Interface auswählen:** Im Config Flow ist das Interface-Feld ein
**Dropdown** mit allen Netzwerk-Interfaces, die Home Assistant auf dem Host
kennt (inkl. deren aktuell zugewiesener IPv4-/IPv6-Adressen als Hilfe zur
Erkennung). Taucht dein gewünschtes Interface dort nicht auf (z. B. bei
bestimmten Docker-Netzwerksetups), kannst du im selben Feld auch einen
eigenen Wert eintippen.

**Adresse herausfinden** (z. B. auf dem HA-Host oder einem Rechner im
selben Netzwerksegment):

```bash
# Mit khtool selbst (unabhängig von dieser Integration nutzbar):
python3 ./khtool.py -i eth0 --scan -q
```

Die Ausgabe zeigt pro Gerät eine Zeile wie:
```
IPv6 address: fe80::2a36:38ff:fe12:3456
```

**Interface-Namen auf dem HA-Host ermitteln** (nur falls du doch manuell
eintippen möchtest/musst – normalerweise reicht die Dropdown-Auswahl im
Config Flow):
```bash
ip -6 addr show scope link
```
(Interface z. B. `eth0`, `end0`, `enp1s0` – je nach System.)

Im Config Flow trägst du dann z. B. ein:
- **IP-Adresse:** `fe80::2a36:38ff:fe12:3456`
- **Interface:** aus dem Dropdown auswählen (oder manuell `eth0` eintippen)

> Läuft Home Assistant in Docker: Der Container braucht `network_mode: host`
> oder direkten Layer-2-Zugriff auf das Netzwerksegment der Lautsprecher,
> sonst ist die Link-Local-Adresse nicht erreichbar.

Falls du den Lautsprechern stattdessen eine feste **IPv4-Adresse** über die
Neumann Control App vergeben hast, lässt du das Interface-Feld einfach leer.

## Angelegte Entities pro Lautsprecher

Wertebereiche/Optionen unten stammen aus **khtools interner
`khtool_commands.json`-Metadaten-Datenbank** (strukturierte Angaben zu Typ,
Schreibbarkeit, Min/Max, exakten Optionen je Modell/Firmware) - deutlich
zuverlässiger als reines Schätzen. Wichtige Einschränkung: Diese Datei
beschreibt nicht immer 1:1 das tatsächliche Geräteverhalten (siehe
"Bekannte Grenzen" unten, Auto-Standby-Beispiel) - wo ein echter
Hardware-Test etwas anderes gezeigt hat, hat der Test Vorrang.

**Standard-Aktivierung (Nicht-Subwoofer-Modelle wie KH 120 II):** Alle
Entities sind standardmäßig aktiviert, **außer** "Dimm" (existiert dort
nicht) und "Steuerungsmodus" (Sicherheits-Ausnahme, siehe unten).

| Entity | Typ | Bereich | SSC-Pfad |
|---|---|---|---|
| Ausgangspegel | `number` | 0–120 dB | `audio/out/level` |
| Dimm (Default: deaktiviert, nicht bei KH 120 II vorhanden) | `number` | −120–0 dB | `audio/out/dimm` |
| Verzögerung | `number` | 0–5760 Samples @48kHz (KH 750: 0–1000) | `audio/out/delay` |
| Logo-Helligkeit* | `number` | 0–125 % | `ui/logo/brightness` |
| Auto-Standby-Zeit | `number` | 1–240 min | `device/standby/auto_standby_time` |
| Standby-Schwellwert | `number` | −80 bis −55 dBu | `device/standby/level` |
| Eingangsverstärkung (nur Nicht-Subwoofer) | `number` | −15–0 dB | `ui/input_gain` |
| Stummschaltung | `switch` | – | `audio/out/mute` |
| Gerät identifizieren (An/Aus) | `switch` | – | `device/identification/visual` |
| Phasenumkehr (nur Nicht-Subwoofer) | `switch` | – | `audio/out/phaseinversion` |
| Auto-Standby (nur Nicht-Subwoofer; auf KH 750 stattdessen `binary_sensor`, siehe unten) | `switch` | – | `device/standby/enabled` |
| Bass/Mitten/Höhen (nur Nicht-Subwoofer) | `select` | feste Stufen (z. B. Bass: -6/-4/-2/0 dB) | `ui/bass_gain`, `ui/mid_gain`, `ui/treble_gain` |
| Ausgangspegel SPL (nur Nicht-Subwoofer) | `select` | 94/100/108/114 dB SPL | `ui/output_level` |
| Eingangsauswahl (Default: deaktiviert, unverifiziert) | `select` | MONO/AES3 R/AES3 L/ANALOG | `ui/input_select` |
| Eingangs-Interface (Default: deaktiviert bei Subwoofer, sonst aktiviert) | `select` | ANALOG ONLY/DIGITAL ONLY/DIGITAL DISCARDS ANALOG | `audio/in/interface` |
| Steuerungsmodus (Default: **immer** deaktiviert, siehe Warnung unten) | `select` | NETWORK/LOCAL | `ui/control_mode` |
| Gerätename (Default: deaktiviert) | `text` | max. 52 Zeichen | `device/name` |
| Eingangspegel live | `sensor` | dB | `m/in/level` |
| Standby-Countdown (Default: deaktiviert) | `sensor` | min | `device/standby/countdown` |
| Hardware-Version, aktueller Eingang (Diagnose) | `sensor` | Text | `device/identity/hw_version`, `audio/in/current_input` |
| Eingang übersteuert (Clip) | `binary_sensor` | – | `m/in/clip` |
| Warnung (Diagnose) | `binary_sensor` | – | `warnings` |
| Einstellungen speichern* | `button` | – | `device/save_settings` |
| Werkseinstellungen wiederherstellen (Default: deaktiviert, Zwei-Schritt-Bestätigung) | `button` | – | `device/restore` |

\* **Nur** bei KH 80 / KH 150 / KH 120 II – laut khtool-Dokumentation nicht bei
KH 750 verfügbar. Die Integration erkennt das Modell automatisch beim
Einrichten und blendet diese Entities für die KH 750 aus.

### Zusätzliche Entities nur bei erkanntem Subwoofer (KH 750)

Die KH 750 hat zwei zusätzliche Bass-Management-Ausgänge (`out1`/`out2`) für
angeschlossene Zusatzlautsprecher, sowie mehrere subwooferspezifische
Kalibrierungswerte. Alle unten gelisteten Entities werden **nur** angelegt,
wenn beim Einrichten `KH 750` als Modell erkannt wurde. Alle sind
standardmäßig **deaktiviert** (unverifizierte Wertebereiche bzw.
Routing-Risiko, siehe "Bekannte Grenzen"), außer den beiden
Subwoofer-Kalibrierungswerten (Eingangsverstärkung, Low-Cut) sowie
Auto-Standby-Zeit/-Schwellwert (gemeinsam mit Nicht-Subwoofer-Modellen).

| Entity | Typ | Bereich | SSC-Pfad |
|---|---|---|---|
| Subwoofer-Eingangsverstärkung | `number` | −12 bis +2 dB | `ui/subwoofer_input_gain` |
| Subwoofer Low-Cut | `number` | −12–0 dB | `ui/subwoofer_low_cut` |
| Ausgang 1/2 Pegel (Default: deaktiviert) | `number` | 0–120 dB | `audio/out1/level`, `audio/out2/level` |
| Ausgang 1/2 Verzögerung (Default: deaktiviert) | `number` | 0–1000 Samples | `audio/out1/delay`, `audio/out2/delay` |
| Subwoofer-Ausgangspegel | `select` | 94/100/108/114 dB SPL | `ui/subwoofer_output_level` |
| Subwoofer-Phase | `select` | 0° / −45° / −90° / −135° | `ui/subwoofer_phase` |
| Subwoofer-Phaseninversion | `select` | 0° / −180° | `ui/subwoofer_phase_inversion` |
| Bass-Management (Default: deaktiviert, Routing-Risiko) | `select` | DISABLED/ACTIVE | `ui/bass_management` |
| Kanal-B-Eingangsmodus (Default: deaktiviert, Routing-Risiko) | `select` | 4 feste Modi | `ui/channel_b_input_mode` |
| Gerätetemperatur (Default: deaktiviert, Einheit unverifiziert) | `sensor` | °C (angenommen aus Kelvin) | `device/temperature` |
| Ausgangspegel live (Default: deaktiviert) | `sensor` | dB | `m/out/level` |
| Ausgangsbezeichnung (Hauptausgang, Diagnose) | `sensor` | Text | `audio/out/label` |
| Ausgang 1/2 Bezeichnung, Ausgang 1/2 Lautsprecher (Default: deaktiviert, Diagnose, nur lesend) | `sensor` | Text ("Nicht zugewiesen" statt "UNKNOWN") | `audio/out1/label`, `audio/out1/loudspeaker`, `audio/out2/label`, `audio/out2/loudspeaker` |
| Ausgang übersteuert (Clip, Default: deaktiviert) | `binary_sensor` | – | `m/out/clip` |
| Digitaler Bypass (Diagnose) | `binary_sensor` | – | `audio/digital_bypass` |
| Auto-Standby-Status (nur lesend – auf der KH 750 per Hardware-Test nicht schreibbar, siehe "Bekannte Grenzen") | `binary_sensor` | – | `device/standby/enabled` |

Standardmäßig deaktivierte Entities kannst du in **Einstellungen → Geräte &
Dienste → [Gerät] → Entities** manuell aktivieren.

## Polling

Alle Werte eines Lautsprechers werden alle 30 Sekunden abgeholt - und zwar
**jeder Wert einzeln** (ein Blattpfad pro SSC-Nachricht), nicht als
Sammelnachricht und nicht als Container-Abfrage. Grund (per zwei
Hardware-Tests bestätigt): Die Firmware lehnt sowohl eine Sammelnachricht
mit mehreren Blättern (sobald eines davon unbekannt ist) als auch eine
Container-Abfrage wie `{"device":null}` komplett ab. Nur einzelne, konkrete,
existierende Blattpfade funktionieren zuverlässig. Lehnt das Gerät einen
einzelnen Wert ab (z. B. `dimm` auf der KH 120 II), wird nur dieser
übersprungen - die übrigen Werte werden trotzdem aktualisiert.

**Standby-Verhalten (wichtig, kein Bug):** Geht ein Lautsprecher (insb. die
KH 750) in den Standby, schaltet er offenbar auch seinen Netzwerk-Stack ab
und antwortet nicht mehr auf SSC-Anfragen. Alle Entities werden dann
korrekterweise **"nicht verfügbar"** - das ist das von Home Assistant
empfohlene Verhalten (`CoordinatorEntity` markiert Entities automatisch als
unavailable, sobald ein Poll-Zyklus fehlschlägt), kein Fehler der
Integration. Sobald das Gerät aus dem Standby aufwacht, erkennt Home
Assistant das automatisch wieder - die Wartezeit dafür ist durch HAs
eingebauten Wiederholungsmechanismus vorgegeben: 5s → 10s → 20s → 40s → 80s
zwischen den ersten Versuchen, danach alle 80 Sekunden (bzw. bei sehr langem
Standby und HA ≥ 2026.6 bis zu alle 10 Minuten). Das ist kein Verhalten
dieser Integration, sondern Home Assistants Kernmechanismus für
`ConfigEntryNotReady`.

## Bekannte Grenzen

- Der 7-/20-Band-Equalizer (`eq1`/`eq2`/`eq3`, alle Ausgänge) wird bewusst
  nicht abgebildet (komplexe Array-Struktur, hohes Risiko für
  Fehlbedienung) – bei Bedarf gerne als Erweiterung.
- **Auto-Standby ist NUR auf der KH 750 nicht schreibbar** (auf der KH 120 II
  funktioniert es per Nutzer-Test bestätigt): Auf der KH 750 wurde
  `device/standby/enabled` per echtem Hardware-Test mit Fehler 405 ("method
  not allowed") abgelehnt, ein alternativer Pfad (`ui/auto_standby`) mit
  Fehler 400 ("message not understood"). Beide Tests liefen ausschließlich
  gegen die KH 750 - eine frühere Version dieser Integration hatte das
  fälschlich auf alle Modelle verallgemeinert. **Wichtige Lehre daraus:**
  khtools Metadaten sind eine gute Quelle für Wertebereiche/Optionen, aber
  keine Garantie, dass ein Pfad auf jedem Modell/jeder Firmware tatsächlich
  schreibbar ist - und ein Testergebnis auf einem Gerät lässt sich nicht
  automatisch auf ein anderes Modell übertragen. Deshalb: KH 120 II →
  `switch` (schreibbar), KH 750 → `binary_sensor` (nur lesend).
- **Eingangsumschaltung (KH 120 II) bleibt unverifiziert:** Sowohl
  `ui/input_select` als auch `audio/in/interface` wurden mit falschen
  Testwerten real abgelehnt; die laut Metadaten korrekten Werte
  (MONO/AES3 R/AES3 L/ANALOG bzw. ANALOG ONLY/DIGITAL ONLY/DIGITAL
  DISCARDS ANALOG) wurden noch nicht gegen echte Hardware getestet.
  Ein [offenes GitHub-Issue](https://github.com/schwinn/khtool/issues/5)
  bestätigt unabhängig, dass andere Nutzer ebenfalls keinen
  funktionierenden Weg gefunden haben.
- **Steuerungsmodus (`ui/control_mode`) bleibt IMMER standardmäßig
  deaktiviert**, auch wenn sonst "alle Entities außer Dimm" aktiviert
  sind: Ein Wechsel zu `LOCAL` könnte die Netzwerksteuerung – und damit
  diese Integration – komplett vom Gerät trennen, bis manuell am Gerät
  zurückgestellt wird. Das ist eine bewusste Sicherheits-Ausnahme.
- **Werksreset (`device/restore`):** Der korrekte Wert
  (`"FACTORY_DEFAULTS"`) ist jetzt durch khtools Metadaten-Datenbank
  bestätigt (nicht mehr geraten wie in einer früheren Version dieser
  Integration). Trotzdem bewusst mit einer **Zwei-Schritt-Sicherheits-
  abfrage** umgesetzt: Der erste Tastendruck "bewaffnet" den Button nur
  (mit einer Warnung als Benachrichtigung), der eigentliche Reset erfolgt
  erst bei einem zweiten Druck innerhalb von 30 Sekunden. Alternativ (ohne
  Netzwerk) läuft der Werksreset über eine physische Schalterfolge am
  Gerät selbst:
  - **KH 80 DSP:** Beim Booten (Logo noch rot) den SETTINGS-Schalter
    mehrfach hoch/runter bewegen, bis das Logo kurz pink flackert.
  - **KH 750:** Beim Booten (Power-LED durchgehend rot) den
    AUTO STANDBY/STANDBY-Schalter mehrfach hoch/runter bewegen.
  - **KH 120 II / KH 150:** Beim Booten (Logo blinkt) den CONTROL-Schalter
    mehrfach hoch/runter bewegen, bis das Logo kurz schnell rot/pink blinkt.
  
  (Quelle: [Neumann KH Monitor Troubleshooting](https://help.neumann.com/hc/en-us/articles/39978248897049-KH-Monitor-Troubleshooting))
- **Bass-Management/Kanal-B-Eingangsmodus (KH 750) bleiben standardmäßig
  deaktiviert:** Ein falscher Wert könnte die Ausgangsroutung des gesamten
  Subwoofer-Systems durcheinanderbringen.
- `dimm` (`audio/out/dimm`) existiert per Hardware-Test auf einer KH 120 II
  (Firmware 1_7_3) NICHT - die Entity bleibt bestehen (evtl. bei anderen
  Modellen vorhanden), zeigt aber "unknown" und wirft beim Versuch, den
  Wert zu ändern, eine klare Fehlermeldung.
- `solo` (`audio/out/solo`) wurde entfernt - taucht im vollständigen
  Geräte-Dump der KH 120 II nicht auf.
- **"Identifizieren" ist ein Schalter, kein Auto-Stopp-Button:** Ein echter
  Hardware-Test hat gezeigt, dass das Blinken zwar von selbst aufhört,
  aber erst nach mehreren Minuten (nicht ~10 Sekunden, wie die allgemeine
  SSC-Doku für andere Sennheiser-Geräte vermuten ließ).
- **Gerätetemperatur (KH 750):** Einheit laut khtool-Metadaten bestätigt
  Kelvin (307 → ≈ 34,85 °C) - Rechnung ist also nicht mehr nur eine
  Annahme, sondern dokumentiert bestätigt.

## Code-Härtung

Folgende Robustheits-Verbesserungen wurden ergänzt (Details siehe
CHANGELOG.md):
- Gemeinsame Hilfsfunktionen (`_util.py`) statt doppelter Implementierung in
  `ssc_client.py` und `coordinator.py`
- Schutz gegen unerwartet große/nie terminierte Geräteantworten
  (`asyncio.LimitOverrunError`)
- Ein unerwarteter Fehler bei einem einzelnen Poll-Pfad reißt nicht mehr den
  gesamten Poll-Zyklus mit - nur der betroffene Wert wird übersprungen
- Gesamt-Zeitlimit für einen kompletten Poll-Zyklus (Schutz gegen ein
  "hängendes" Gerät)
- Leerer Name wird jetzt auch beim manuellen Setup abgelehnt (vorher nur
  beim Scan-Schritt)
- Ein unerwarteter Fehler beim mDNS-Scan führt zu einer klaren
  Fehlermeldung statt eines Absturzes des Einrichtungs-Dialogs
- Firmware-Version wird beim Einrichten zusätzlich ausgelesen und als
  `sw_version` im Geräte-Info-Bereich angezeigt

