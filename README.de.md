# Neumann Connect – Home Assistant Custom Component

**Deutsch** | [English](./README.md)

Steuert Neumann-KH-DSP-Lautsprecher (KH 80, KH 120 II, KH 150, KH 750 DSP)
über das Sennheiser Sound Control Protocol (SSC), TCP-Port 45. Es muss kein
zusätzliches pip-Paket installiert werden – für das SSC-Protokoll selbst
ist ein schlanker eigener asyncio-Client enthalten, die Geräte-Suche nutzt
Home Assistants eingebaute Zeroconf-Komponente.

Änderungshistorie: siehe [CHANGELOG.de.md](./CHANGELOG.de.md).

**Benötigt Home Assistant 2025.2 oder neuer.**

Eigenes Icon/Logo unter `custom_components/neumann_kh/brand/` (eigenständiges
Design, keine Kopie des offiziellen Neumann-Firmenlogos). Das Icon selbst
braucht **2026.3 oder neuer** – erst ab dieser Version lesen Custom
Integrations ihre Marken-Bilder direkt aus einem eigenen `brand/`-Ordner
(siehe [HA Developer Blog](https://developers.home-assistant.io/blog/2026/02/24/brands-proxy-api/)).
Alles andere läuft ab 2025.2; ältere Versionen zeigen lediglich ein
generisches Icon.

Basiert auf den SSC-Adresspfaden, die im
[khtool-Projekt](https://github.com/schwinn/khtool) dokumentiert sind.

## Disclaimer

**Das ist ein privates Hobby-/Testprojekt, entwickelt für mein eigenes
Setup und „as-is“ geteilt.** Es ist keine offizielle Integration, es gibt
keine Garantie und weder zugesicherten Support noch zugesicherte Wartung. Nutzung auf
eigenes Risiko – besonders bei schreibbaren Einstellungen, die direkt die
echte Lautsprecher-Hardware verändern (EQ, Pegel, Delay, Werksreset).
Änderungen immer zusätzlich in Neumanns eigener MA1/Neumann.Control-Software
oder direkt am Gerät überprüfen.

Entwickelt mit KI-Unterstützung (Claude); sämtliche Tests, Entscheidungen
und Validierungen habe ich selbst an meiner eigenen Installation
(KH 120 II, KH 750 DSP) durchgeführt.

## Unterstützte Modelle

**Getestet mit echter Hardware:** KH 120 II, KH 750 DSP.

**Vermutlich funktionsfähig, aber unverifiziert** (gleiche DSP-/SSC-Basis
laut Herstellerangaben, keine eigenen Tests): KH 80 DSP, KH 150 sowie
deren AES67-Varianten (KH 120 II AES67, KH 150 AES67). Wertebereiche
(Delay, Logo-Helligkeit etc.) sind von der KH 120 II übernommen und
könnten bei diesen Modellen leicht abweichen.

**Nicht unterstützbar** (keine DSP-/Netzwerkfunktion, rein analog): KH 310,
KH 420 und andere klassische analoge KH-Monitore. Diese lassen sich nicht
per SSC ansprechen – die automatische Suche listet sie nicht, und eine
manuelle Einrichtung kommt nicht zustande. Das ist kein Fehler dieser Integration.

**Komplett ungetestet, evtl. kompatibel:** Die neueren DSP-Subwoofer
KH 805 II, KH 810 II, KH 870 II (2024/2025 vorgestellt, laut Hersteller
„bauen auf dem KH 750 DSP auf“) sind bisher nicht in der Modell-Erkennung
hinterlegt – falls du eines dieser Geräte besitzt und testen möchtest,
gerne melden.

## Installation

### HACS (benutzerdefiniertes Repository)

Diese Integration steht nicht im HACS-Standardkatalog, das Repository wird
also einmalig von Hand hinzugefügt:

1. **HACS → ⋮ (oben rechts) → Benutzerdefinierte Repositories**
2. Repository `https://github.com/Varitras/neumann-connect`, Typ
   **Integration**, dann **Hinzufügen**
3. **Neumann Connect** in HACS suchen und herunterladen
4. Home Assistant neu starten

Vorabversionen (`1.18.1b5` und ähnliche) erscheinen erst, wenn für das
Repository in HACS Beta-Versionen aktiviert sind.

### Manuell

1. Ordner `custom_components/neumann_kh` in dein Home-Assistant-Konfigurationsverzeichnis kopieren
   (z. B. `/config/custom_components/neumann_kh`).
2. Home Assistant neu starten.

## Einrichtung

1. **Einstellungen → Geräte & Dienste → Integration hinzufügen → „Neumann KH (SSC)“**.
2. Du bekommst ein Menü mit zwei Wegen:
   - **„Automatisch im Netzwerk suchen“** – aktiver mDNS-Scan (siehe unten),
     Ergebnis als Auswahlliste. Empfohlener Standardweg.
   - **„Manuell eingeben (IP-Adresse)“** – Name, IP-Adresse, Interface-Dropdown, Port (Fallback,
     falls die automatische Suche ein Gerät nicht findet).
3. Für **jeden** Lautsprecher einen eigenen Eintrag anlegen (z. B. „KH 120 II Links“,
   „KH 120 II Rechts“, „KH 750 DSP Sub 1“, „KH 750 DSP Sub 2“).

### Verbindungsdaten nachträglich ändern

Landet ein Lautsprecher auf einer anderen Adresse, einem anderen Interface oder einem
anderen Port, führt der Weg über **Einstellungen → Geräte & Dienste → [Gerät]
→ ⋮ → Neu konfigurieren**. Der Eintrag wird an Ort und Stelle aktualisiert,
Entity-IDs, Verlauf und darauf verweisende Automationen bleiben also erhalten –
Löschen und neu anlegen ist nicht nötig.

Die neue Adresse wird geprüft, bevor irgendetwas gespeichert wird. Antwortet
dort ein Lautsprecher mit abweichender Seriennummer, wird die Änderung
abgelehnt: sonst hinge der Verlauf des einen Geräts still an einem anderen
physischen Gerät.

## Automatische Suche (mDNS/Zeroconf)

Neumann-KH-Lautsprecher machen sich laut SSC-Spezifikation per mDNS/Bonjour
im Netzwerk bekannt (Dienst-Typ `_ssc._tcp.local.`) – genau wie z. B.
AirPlay-Geräte. Die Integration nutzt Home Assistants ohnehin laufende
Zeroconf-Instanz, um für einige Sekunden aktiv danach zu suchen, und zeigt
gefundene Geräte (Modell, IP-Adresse, Seriennummer) zur Auswahl an.

Zusätzlich reicht Home Assistant die Ankündigungen der Lautsprecher selbst
weiter. Ein noch nicht eingerichteter Lautsprecher erscheint unter
**Einstellungen → Geräte & Dienste** als gefundenes Gerät und braucht nur
noch einen Namen. Bei einem bereits eingerichteten wird eine geänderte Adresse
übernommen, sobald der Lautsprecher seine Seriennummer bestätigt hat.

**Vorteil bei IPv6-Link-Local:** Die gefundene Adresse enthält die
Scope-ID bereits automatisch (z. B. `fe80::...%3`) – bei automatisch
gefundenen Geräten musst du das Netzwerk-Interface **nicht** manuell
angeben.

Die Suche bevorzugt bewusst die Link-Local-Adresse, auch wenn ein
Lautsprecher zusätzlich eine globale meldet. Eine globale IPv6-Adresse
enthält das Präfix, das der Provider zuteilt, und viele Anschlüsse bekommen
bei der täglichen Zwangstrennung ein neues – jede gespeicherte globale
Adresse zeigt danach ins Leere. Die Link-Local-Adresse leitet sich aus der
MAC ab und bleibt gültig, solange der Lautsprecher im selben Netzsegment
hängt.

**Wird nichts gefunden:** Formular einfach ohne Auswahl erneut absenden,
um die Suche zu wiederholen – oder zurück ins Menü gehen und „Manuell
eingeben (IP-Adresse)“ wählen. mDNS funktioniert nur zuverlässig, wenn HA multicast-mäßig
im selben Netzwerksegment wie die Lautsprecher hängt (bei Docker z. B.
`network_mode: host` nötig) – dieselbe Voraussetzung, die für die
Link-Local-Verbindung ohnehin gilt.

## IPv6-Link-Local-Adresse & Interface ermitteln (nur für „Manuell eingeben (IP-Adresse)“)

Die Lautsprecher sind per Default nur über ihre IPv6-Link-Local-Adresse
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
python3 ./khtool.py --scan        # findet die Lautsprecher, speichert khtool.json und endet
python3 ./khtool.py -i eth0 -q    # fragt sie ab; die Ausgabe nennt je Gerät die IPv6-Adresse
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

## Angelegte Entities pro Lautsprecher

**Schreibbar vs. nur lesbar (nach Entity-Typ):**

| Typ | Schreibbar? |
|---|---|
| `number` | Ja – Zahlenwert per Schieberegler/Eingabefeld |
| `select` | Ja – feste Auswahl |
| `switch` | Ja – An/Aus |
| `text` | Ja – Freitext |
| `button` | Löst eine einmalige Aktion aus (kein Wert, kein Lesen/Schreiben) |
| `sensor` | **Nein**, nur lesbar |
| `binary_sensor` | **Nein**, nur lesbar |

Werte, die laut khtool-Metadaten eigentlich schreibbar sein sollten, aber
**per echtem Test bestätigt nicht schreibbar sind** (siehe „Bekannte
Grenzen“), sind deshalb bewusst als `sensor`/`binary_sensor` statt als
`number`/`select`/`switch` umgesetzt – nicht weil HA das technisch
verlangt, sondern weil ein Schreibversuch dort ohnehin fehlschlägt.

**Standardmäßig aktiviert:** die meisten Entities. Die Ausnahmen sind in den
Tabellen unten mit „Default: deaktiviert“ gekennzeichnet – hier bewusst nicht
noch einmal aufgezählt, weil eine zweite Liste genau die ist, die mit der
ersten auseinanderläuft.

| Entity | Typ | Bereich | SSC-Pfad |
|---|---|---|---|
| Ausgangspegel | `number` | 0–120 dB | `audio/out/level` |
| Verzögerung | `number` | 0–5760 Samples @48kHz (KH 750 DSP: 0–1000) | `audio/out/delay` |
| Logo-Helligkeit* | `number` | 0–125 % | `ui/logo/brightness` |
| Auto-Standby-Zeit | `number` | 1–240 min | `device/standby/auto_standby_time` |
| Standby-Schwellwert | `number` | −80 bis −55 dBu | `device/standby/level` |
| Stummschaltung | `switch` | – | `audio/out/mute` |
| Identifizieren | `switch` | – | `device/identification/visual` |
| Phasenumkehr (nur Nicht-Subwoofer) | `switch` | – | `audio/out/phaseinversion` |
| Auto-Standby (nur Nicht-Subwoofer; auf KH 750 DSP stattdessen `binary_sensor`) | `switch` | – | `device/standby/enabled` |
| Eingangs-Interface (schreibbar, bestätigt auf KH 120 II und KH 750 DSP) | `select` | ANALOG ONLY/DIGITAL ONLY/DIGITAL DISCARDS ANALOG | `audio/in/interface` |
| Steuerungsmodus (Default: deaktiviert, siehe „Bekannte Grenzen“) | `select` | NETWORK/LOCAL | `ui/control_mode` |
| Gerätename (Default: deaktiviert) | `text` | max. 52 Zeichen | `device/name` |
| Eingangspegel (live) | `sensor` | dB | `m/in/level` |
| Standby-Countdown (Default: deaktiviert, Diagnose) | `sensor` | min | `device/standby/countdown` |
| Hardware-Version, aktueller Eingang (Diagnose) | `sensor` | Text | `device/identity/hw_version`, `audio/in/current_input` |
| Eingangsverstärkung, Eingangsauswahl, Bass, Mitten, Höhen, Ausgangspegel (SPL) (nur Nicht-Subwoofer; per Test nicht schreibbar, Diagnose) | `sensor` | dB bzw. Text | `ui/input_gain`, `ui/input_select`, `ui/bass_gain`, `ui/mid_gain`, `ui/treble_gain`, `ui/output_level` |
| Eingang übersteuert (Clip) | `binary_sensor` | – | `m/in/clip` |
| Warnung (Diagnose) | `binary_sensor` | – | `warnings` |
| Werkseinstellungen wiederherstellen (Default: deaktiviert, Zwei-Schritt-Bestätigung) | `button` | – | `device/restore` |
| Backup erstellen (alle bekannten Werte außer Live-Messwerten) | `button` | – | – |
| Backup zurückspielen (schreibt das gespeicherte Backup zurück, standardmäßig deaktiviert) | `button` | – | – |
| Geräte-Discovery ausführen (Diagnose) | `button` | – | – |

\* **Nur** bei KH 80 / KH 150 / KH 120 II – laut khtool-Dokumentation nicht bei
KH 750 DSP verfügbar. Die Integration erkennt das Modell automatisch beim
Einrichten und blendet diese Entities für die KH 750 DSP aus.

### Zusätzliche Entities nur bei erkanntem Subwoofer (KH 750 DSP)

Die KH 750 DSP hat zwei zusätzliche Bass-Management-Ausgänge (`out1`/`out2`) für
angeschlossene Zusatzlautsprecher. Alle unten gelisteten Entities werden
**nur** angelegt, wenn beim Einrichten `KH 750` als Modell erkannt wurde
(das Gerät meldet sich über SSC selbst nur als `KH 750`, ohne „DSP“ –
die Integration akzeptiert beide Schreibweisen).

| Entity | Typ | Bereich | SSC-Pfad |
|---|---|---|---|
| Ausgang 1/2 Pegel (Default: deaktiviert) | `number` | 0–120 dB | `audio/out1/level`, `audio/out2/level` |
| Ausgang 1/2 Verzögerung (Default: deaktiviert) | `number` | 0–1000 Samples | `audio/out1/delay`, `audio/out2/delay` |
| Ausgang 1/2 Stummschaltung (Default: deaktiviert) | `switch` | – | `audio/out1/mute`, `audio/out2/mute` |
| Gerätetemperatur (Default: aktiviert, Diagnose; das Gerät meldet Kelvin) | `sensor` | °C | `device/temperature` |
| Ausgangspegel (live) (Default: deaktiviert) | `sensor` | dB | `m/out/level` |
| Ausgangsbezeichnung (Hauptausgang, Diagnose) | `sensor` | Text | `audio/out/label` |
| Ausgang 1/2 Bezeichnung, Ausgang 1/2 Lautsprecher (Default: deaktiviert, Diagnose, nur lesend) | `sensor` | Text (Lautsprecher: „Nicht zugewiesen“ statt „UNKNOWN“) | `audio/out1/label`, `audio/out1/loudspeaker`, `audio/out2/label`, `audio/out2/loudspeaker` |
| Subwoofer-Eingangsverstärkung, Low-Cut, Ausgangspegel, Phase, Phasenumkehr, Bass-Management, Kanal-B-Eingangsmodus (per Test nicht schreibbar, Diagnose) | `sensor` | dB bzw. Text | `ui/subwoofer_input_gain`, `ui/subwoofer_low_cut`, `ui/subwoofer_output_level`, `ui/subwoofer_phase`, `ui/subwoofer_phase_inversion`, `ui/bass_management`, `ui/channel_b_input_mode` |
| Ausgang übersteuert (Clip, Default: deaktiviert) | `binary_sensor` | – | `m/out/clip` |
| Digitaler Bypass (Diagnose) | `binary_sensor` | – | `audio/digital_bypass` |
| Auto-Standby (nur lesend – auf der KH 750 DSP per Hardware-Test nicht schreibbar, siehe „Bekannte Grenzen“) | `binary_sensor` | – | `device/standby/enabled` |

Standardmäßig deaktivierte Entities kannst du in **Einstellungen → Geräte &
Dienste → [Gerät] → Entities** manuell aktivieren.

## Polling

Ein Lautsprecher wird alle 30 Sekunden abgefragt. Dabei wird nicht jedes Mal
alles geholt: Selten wechselnde Werte (Identität, Rückseiten-Schalter,
Gerätename) werden nur in jedem zehnten Zyklus abgefragt, also alle 5 Minuten.
Abgefragt wird **jeder Wert einzeln** (ein Blattpfad pro SSC-Nachricht), nicht als
Sammelnachricht und nicht als Container-Abfrage. Grund (per zwei
Hardware-Tests bestätigt): Die Firmware lehnt sowohl eine Sammelnachricht
mit mehreren Blättern (sobald eines davon unbekannt ist) als auch eine
Container-Abfrage wie `{"device":null}` komplett ab. Nur einzelne, konkrete,
existierende Blattpfade funktionieren zuverlässig. Lehnt das Gerät einen
einzelnen Wert ab, wird nur dieser
übersprungen – die übrigen Werte werden trotzdem aktualisiert.

**Standby-Verhalten (wichtig, kein Bug):** Geht ein Lautsprecher in den
Standby, schaltet er auch seinen Netzwerk-Stack ab und antwortet nicht mehr auf
SSC-Anfragen (beobachtet bei KH 120 II und KH 750 DSP). Alle Entities werden dann
korrekterweise **„nicht verfügbar“** – das ist das von Home Assistant
empfohlene Verhalten (`CoordinatorEntity` markiert Entities automatisch als
unavailable, sobald ein Poll-Zyklus fehlschlägt), kein Fehler der
Integration. Sobald das Gerät aus dem Standby aufwacht, erkennt Home
Assistant das von selbst wieder. Im Log steht dazu je eine Info-Zeile beim
Wegfallen und beim Wiederkommen – keine Fehler. Wie schnell es zurückkommt,
hängt davon ab, welcher der beiden Mechanismen greift.

War der Lautsprecher schon beim Start von Home Assistant nicht erreichbar, kam
der Eintrag nie zustande und Home Assistant versucht es mit wachsendem Abstand
erneut: 5 s, 10 s, 20 s, 40 s, 80 s und danach alle 80 s. Seit Home Assistant
2026.6 verdoppelt sich der Abstand stattdessen weiter (160 s, 320 s) bis auf
10 Minuten. Aufgegeben wird nie.

Lief der Eintrag bereits, als der Lautsprecher einschlief, läuft der
Abfragezyklus einfach in seinem normalen 30-Sekunden-Takt weiter und greift den
Lautsprecher beim ersten erfolgreichen Zyklus wieder auf.

Die Wiederholabstände bestimmt Home Assistant selbst. Zusätzlich sucht die
Integration nach jedem fehlgeschlagenen Einrichten im Netzwerk anhand der
Seriennummer nach dem Lautsprecher und speichert seine neue Adresse, falls er
umgezogen ist.

## Bekannte Grenzen

- Auto-Standby ist nur auf der KH 750 DSP nicht schreibbar (auf der KH 120 II
  funktioniert es). Deshalb: KH 120 II → `switch`, KH 750 DSP → `binary_sensor`.
- `ui/input_select` bleibt nur lesend. Der schreibbare Pfad ist
  `audio/in/interface`, bestätigt auf KH 120 II und KH 750 DSP und dort
  standardmäßig aktiviert.
- Antwortet ein Lautsprecher auf eine einzelne Abfrage mit mehr als einer
  Zeile, kann in einem engen Fall eine Folgezeile der einen Antwort als die
  nächste ausgegeben werden. Das Protokoll führt keine Transaktionskennung,
  eine Folgezeile für den gerade abgefragten Pfad ist von einer frischen
  Antwort darauf also nicht zu unterscheiden. Bereits anliegende Zeilen werden
  vor der nächsten Anfrage verworfen; betroffen ist nur eine, die genau
  dazwischen eintrifft. Beide Testgeräte antworten mit exakt einer Zeile, das
  betrifft also andere Firmware, nicht die eingesetzte Hardware.
- Steuerungsmodus (`ui/control_mode`) ist standardmäßig deaktiviert und
  sollte es bleiben: Ein Wechsel zu `LOCAL` könnte die Netzwerksteuerung vom
  Gerät trennen.
- Werksreset (`device/restore`) hat eine Zwei-Schritt-Sicherheitsabfrage:
  Der erste Tastendruck schaltet nur scharf, ein zweiter Druck frühestens 2 s
  und spätestens 30 s danach löst aus. Alternativ über eine physische Schalterfolge am Gerät selbst:
  - **KH 80 DSP:** Beim Booten (Logo noch rot) den SETTINGS-Schalter
    mehrfach hoch und runter bewegen, bis das Logo weiß wird, und danach noch
    einige Sekunden weiter.
  - **KH 750 DSP:** Beim Booten (Power-LED durchgehend rot) den
    AUTO-STANDBY-Schalter mehrfach hoch und runter bewegen. Die Power-LED
    blinkt rot, während die Werkseinstellungen geladen werden, und wird dann
    grün.
  - **KH 120 II / KH 150:** Beim Booten (Logo blinkt) den CONTROL-Schalter
    mehrfach hoch und runter bewegen, bis das Logo einige Sekunden lang
    durchgehend weiß leuchtet. Danach blinkt es kurz schnell rot und wird
    wieder weiß.

  (Quelle: [Neumann KH Monitor Troubleshooting](https://help.neumann.com/hc/en-us/articles/39978248897049-KH-Monitor-Troubleshooting))
- Folgende KH-750-Werte sind per Test bestätigt nicht schreibbar und deshalb
  reine Lesewerte: Bass-Management, Kanal-B-Eingangsmodus,
  Subwoofer-Eingangsverstärkung/Low-Cut/Ausgangspegel/Phase/Phasenumkehr.
- Folgende KH-120-II-Werte sind ebenso per Test bestätigt nicht schreibbar:
  Eingangsverstärkung, Eingangsauswahl, Bass, Mitten, Höhen, Ausgangspegel (SPL).
- `audio/out/dimm` und `device/save_settings` werden von beiden Testmodellen
  mit 404 beantwortet, existieren dort also nicht. Die Dimm-Entity und der
  Button „Einstellungen speichern“ wurden entfernt, statt dauerhaft
  „unbekannt“ anzuzeigen bzw. bei jedem Druck zu scheitern.
- „Identifizieren“ ist ein Schalter, kein Auto-Stopp-Button: Das Blinken
  hört erst nach mehreren Minuten von selbst auf.
- Gerätetemperatur (KH 750 DSP): Einheit Kelvin, umgerechnet in °C.

## Namensgedächtnis, Backup & Geräte-Discovery

Drei getrennte, dauerhafte Speicher (unabhängig von Config Entries,
überleben also auch das Löschen und Neueinrichten eines Geräts, alle in
`storage.py`), je ein Eintrag pro Seriennummer:

- **`.storage/neumann_kh_names`**: zuletzt verwendeter Name. Beim erneuten
  Einrichten über die automatische Suche wird das Namensfeld damit
  vorausgefüllt.
- **`.storage/neumann_kh_backups`**: Ergebnis des `Backup erstellen`-Buttons –
  alle bekannten Werte außer Live-Messwerten, inklusive der selten
  abgefragten Einstellungen und des vollständigen EQ jedes Containers (Gain,
  Boost, Frequenz, Q und Filtertyp je Band). Zusätzlich als JSON-Datei unter
  `<config>/neumann_kh/` – erreichbar über Dateimanager oder Freigabe, aber
  nie über HTTP, anders als `/config/www/`.
- **`.storage/neumann_kh_discovery`**: Ergebnis des `Geräte-Discovery
  ausführen`-Buttons (Diagnose) – kombiniert unsere bekannten Pfade mit
  einem Best-effort-Versuch über `osc/schema` + `osc/limits` (optionale
  SSC-Methoden, nicht jede Firmware unterstützt sie – schlägt dieser Teil
  fehl, bleibt er einfach leer). Zusätzlich als JSON-Datei unter
  `<config>/neumann_kh/`; die Benachrichtigung nennt den Pfad. Die
  Seriennummer ist in diesem Export zensiert (nur die letzten 3 Zeichen
  bleiben sichtbar).

Backup und Discovery laufen ausschließlich manuell über die jeweiligen
Buttons – keine automatische Auslösung im Hintergrund.

Die Auswahlliste beim automatischen Scan enthält außerdem einen Eintrag
„🔄 Erneut suchen“, um die Netzwerksuche direkt aus der Liste neu zu starten.

## EQ (parametrischer Equalizer)

Eine vollständige 1:1-Abbildung aller EQ-Parameter (Typ/Frequenz/Gain/Boost/
Q/Enabled je Band) wäre bei der KH 750 DSP ca. 800 Entities – nicht mehr
überschaubar. Stattdessen bewusst auf Container-Ebene reduziert:

- **Ein Ein/Aus-Schalter pro EQ-Container** (`switch`, Kategorie
  „Konfiguration“, standardmäßig aktiviert): schaltet **alle Bänder dieses
  Containers gemeinsam** (schreibt denselben Wert in das komplette
  `enabled`-Array). Zeigt „an“, sobald mindestens ein Band aktiv ist.
- **Ein „{container}: auf neutral zurücksetzen“-Button pro EQ-Container** (`button`,
  Kategorie „Konfiguration“, standardmäßig aktiviert): setzt Gain **und**
  Boost aller Bänder dieses Containers auf 0 dB. Frequenz/Q/Typ/Enabled
  bleiben unverändert – eine echte Werks-Rücksetzung ist nicht möglich, da
  keine dokumentierten Standardfrequenzen pro Band vorliegen.

Alle Container-Namen beginnen bewusst mit „EQ“ (z. B. „EQ2 Hauptausgang“,
„EQ Crossover Ausgang 1“), damit sie im Abschnitt „Konfiguration“
alphabetisch zusammen gruppiert erscheinen.

**Abgedeckte Container:**

| Modell | Container | Bänder |
|---|---|---|
| KH 120 II (Nicht-Subwoofer) | `audio/out/eq2` | 10 |
| KH 120 II (Nicht-Subwoofer) | `audio/out/eq3` | 20 |
| KH 750 DSP (Hauptausgang) | `audio/out/eq2` | 10 |
| KH 750 DSP (out1/out2 je) | `eq1` (Crossover) | 2 |
| KH 750 DSP (out1/out2 je) | `eq2` | 10 |
| KH 750 DSP (out1/out2 je) | `eq3` | 10 |

Macht in Summe **4 Entities** (KH 120 II: 2 Container × Schalter+Button)
bzw. **14 Entities** (KH 750 DSP: 7 Container × Schalter+Button).

