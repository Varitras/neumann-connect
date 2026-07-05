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

Pfade unten sind gegen einen echten `khtool -q`-Dump einer KH 120 II
(Firmware 1_7_3) verifiziert (Stand: siehe Git-Historie). Bei anderen
Modellen/Firmware-Ständen können einzelne Pfade abweichen oder fehlen -
in dem Fall zeigt die jeweilige Entity "unknown", ohne die anderen Werte zu
beeinträchtigen (siehe "Polling" unten).

| Entity | Typ | Bereich | SSC-Pfad |
|---|---|---|---|
| Ausgangspegel | `number` | 0–120 dB | `audio/out/level` |
| Dimm (Default: deaktiviert, nicht bei KH 120 II vorhanden, siehe unten) | `number` | −120–0 dB | `audio/out/dimm` |
| Verzögerung | `number` | 0–3360 Samples @48kHz | `audio/out/delay` |
| Logo-Helligkeit* | `number` | 0–100 % | `ui/logo/brightness` |
| Auto-Standby-Zeit (Default: deaktiviert, Bereich unverifiziert) | `number` | 1–90 min | `device/standby/auto_standby_time` |
| Standby-Schwellwert (Default: deaktiviert, Bereich unverifiziert) | `number` | −90–0 dB | `device/standby/level` |
| Bass/Mitten/Höhen (Default: deaktiviert, Bereich unverifiziert) | `number` | −12–12 dB | `ui/bass_gain`, `ui/mid_gain`, `ui/treble_gain` |
| Stummschaltung | `switch` | – | `audio/out/mute` |
| Phasenumkehr (Default: deaktiviert) | `switch` | – | `audio/out/phaseinversion` |
| Auto-Standby ein/aus (Default: deaktiviert, unverifiziert) | `switch` | – | `device/standby/enabled` |
| Eingangsverstärkung | `sensor` | dB | `ui/input_gain` |
| Eingangspegel live | `sensor` | dB, pro Kanal, angezeigt wird der lautere Kanal | `m/in/level` |
| Standby-Countdown (Default: deaktiviert) | `sensor` | min | `device/standby/countdown` |
| Gerätename, Hardware-Version, aktueller Eingang, Eingangs-Interface-Typ, Steuerungsmodus (Diagnose) | `sensor` | Text | `device/name`, `device/identity/hw_version`, `audio/in/current_input`, `audio/in/interface`, `ui/control_mode` |
| Eingang übersteuert (Clip) | `binary_sensor` | – | `m/in/clip` (pro Kanal, "Problem" wenn irgendein Kanal clippt) |
| Warnung (Diagnose) | `binary_sensor` | – | `warnings` ("Problem" wenn ≠ `NO_WARNING`) |
| Einstellungen speichern* | `button` | – | `device/save_settings` |
| Gerät identifizieren (Logo blinkt) | `button` | – | `device/identification/visual` |

\* **Nur** bei KH 80 / KH 150 / KH 120 II – laut khtool-Dokumentation nicht bei
KH 750 DSP verfügbar. Die Integration erkennt das Modell automatisch beim
Einrichten und blendet diese Entities für die KH 750 aus.

Standardmäßig deaktivierte Entities kannst du in **Einstellungen → Geräte &
Dienste → [Gerät] → Entities** manuell aktivieren.

## Polling

Alle Werte eines Lautsprechers werden alle 30 Sekunden abgeholt - und zwar
**jeder Wert einzeln** (ein Blattpfad pro SSC-Nachricht), nicht als
Sammelnachricht und nicht als Container-Abfrage. Grund (per zwei
Hardware-Tests bestätigt): Die Firmware lehnt sowohl eine Sammelnachricht
mit mehreren Blättern (sobald eines davon unbekannt ist) als auch eine
Container-Abfrage wie `{"device":null}` komplett ab. Nur einzelne, konkrete,
existierende Blattpfade funktionieren zuverlässig - genau das macht auch
khtool laut eigenem Log intern so (modellspezifische Liste bekannter
Einzelpfade). Lehnt das Gerät einen einzelnen Wert ab (z. B. `dimm` auf der
KH 120 II), wird nur dieser übersprungen - die übrigen Werte werden
trotzdem aktualisiert.

## Bekannte Grenzen

- Der 7-Band-Equalizer wird bewusst nicht abgebildet (komplexe Array-Struktur,
  hohes Risiko für Fehlbedienung) – bei Bedarf gerne als Erweiterung.
- **Werksreset absichtlich NICHT implementiert:** `device/restore` wäre ein
  möglicher SSC-Pfad dafür, aber es gibt keine verifizierte Quelle für den
  korrekten Wert bei KH-Monitoren (der bekannte Wert `FACTORY_DEFAULTS`/
  `AUDIO_DEFAULTS` stammt aus der Doku eines anderen Sennheiser-Produkts,
  TeamConnect Ceiling 2, und muss hier nicht gelten). Neumanns **offizieller**
  Weg für einen Werksreset läuft über eine physische Schalterfolge am Gerät
  selbst, nicht über das Netzwerk:
  - **KH 80 DSP:** Beim Booten (Logo noch rot) den SETTINGS-Schalter
    mehrfach hoch/runter bewegen, bis das Logo kurz pink flackert.
  - **KH 750 DSP:** Beim Booten (Power-LED durchgehend rot) den
    AUTO STANDBY/STANDBY-Schalter mehrfach hoch/runter bewegen.
  - **KH 120 II / KH 150:** Beim Booten (Logo blinkt) den CONTROL-Schalter
    mehrfach hoch/runter bewegen, bis das Logo kurz schnell rot/pink blinkt.
  
  (Quelle: [Neumann KH Monitor Troubleshooting](https://help.neumann.com/hc/en-us/articles/39978248897049-KH-Monitor-Troubleshooting))
- **Klangregler (Bass/Mitten/Höhen) und Auto-Standby-Werte sind unverifiziert:**
  Wertebereiche sind nicht offiziell dokumentiert und nicht gegen echte
  Hardware getestet - konservativ geschätzt. Lehnt das Gerät einen Wert ab,
  zeigt HA eine klare Fehlermeldung statt eines stillen Fehlschlags oder
  eines unerwarteten Verhaltens. Alle diese Entities sind deshalb
  standardmäßig deaktiviert - erst nach bewusster Aktivierung durch dich
  sichtbar.
- `dimm` (`audio/out/dimm`) existiert per Hardware-Test auf einer KH 120 II
  (Firmware 1_7_3) NICHT - die Entity bleibt bestehen (evtl. bei anderen
  Modellen wie der KH 750 DSP vorhanden), zeigt aber "unknown" und wirft beim
  Versuch, den Wert zu ändern, eine klare Fehlermeldung statt eines stillen
  Fehlschlags.
- `solo` (`audio/out/solo`) wurde entfernt - taucht im vollständigen
  Geräte-Dump der KH 120 II nicht auf, ist von diesem Modell/dieser Firmware
  offenbar nicht unterstützt.
- Frühere Versionen dieser Integration gingen (basierend auf der
  KH-80-Beispieldoku von khtool) von getrennten Ein-/Ausgangs-Phasenumkehr-
  Pfaden aus (`audio/in/phase_invert`, `audio/out/phase_correction`). Ein
  echter Hardware-Test hat gezeigt: Es gibt nur EINE Phasenumkehr
  (`audio/out/phaseinversion`) für den gesamten Ausgang.

