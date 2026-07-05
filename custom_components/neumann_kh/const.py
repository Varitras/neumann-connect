"""Konstanten für die Neumann KH (SSC) Integration.

Dieses Modul sammelt alle festen Werte an einer Stelle:
- Domain-Name der Integration
- Konfigurationsschlüssel (config_entry.data / options)
- Standardwerte (Port, Update-Intervall)
- SSC-Adresspfade (siehe Sennheiser Sound Control Protocol Spezifikation
  und https://github.com/schwinn/khtool)
- Produktnamen, die zusätzliche Funktionen unterstützen (Logo-Helligkeit,
  save_settings) - laut khtool nur KH 80 / KH 150 / KH 120 II, NICHT KH 750 DSP.
"""

from __future__ import annotations

DOMAIN = "neumann_kh"

# --- Config Entry Keys ---------------------------------------------------
CONF_INTERFACE = "interface"  # Netzwerk-Interface für IPv6 Link-Local Scope-ID
CONF_SERIAL = "serial"  # Seriennummer, dient als eindeutige ID
CONF_MODEL = "model"  # Produktname (z. B. "KH 120 II", "KH 750 DSP")

# --- Standardwerte ---------------------------------------------------------
DEFAULT_PORT = 45  # SSC-Standardport lt. Sennheiser-Spezifikation
DEFAULT_TIMEOUT = 3.0  # Sekunden, Verbindungs-/Antwort-Timeout
DEFAULT_QUERY_SETTLE = 0.4  # Sekunden Ruhezeit, bis Mehrfachantworten als vollständig gelten
UPDATE_INTERVAL_SECONDS = 30

# Modelle, die Logo-Helligkeit + save_settings unterstützen (lt. khtool-Doku)
MODELS_WITH_LOGO_AND_SAVE = ("KH 80", "KH 150", "KH 120", "KH 120 II")

# --- Zeroconf/mDNS-Gerätesuche ---------------------------------------------
# Lt. SSC-Spezifikation muss jedes SSC-Gerät, das TCP unterstützt, sich per
# DNS-SD unter diesem Dienst-Typ bekannt machen.
SSC_ZEROCONF_SERVICE_TYPE = "_ssc._tcp.local."
SCAN_DURATION_SECONDS = 4.0

# --- SSC Adresspfade (als Tupel von Schlüsseln, für verschachteltes JSON) ---
#
# WICHTIG: Ursprünglich basierten diese Pfade auf dem KH-80-Beispiel aus der
# khtool-Dokumentation. Ein echter `khtool -q`-Dump einer KH 120 II
# (Firmware 1_7_3) hat gezeigt, dass mehrere Pfade beim KH 120 II ANDERS
# heißen bzw. gar nicht existieren. Die Pfade unten sind gegen diesen
# realen Dump verifiziert.
#
# Zur Abfrage-Strategie (zwei gescheiterte Ansätze, bevor der aktuelle
# funktionierte): (1) Eine Sammelnachricht mit mehreren Blättern scheitert
# komplett, sobald auch nur EIN Blatt darin unbekannt ist ("message not
# understood", Fehler 400). (2) Eine Container-Abfrage wie {"device":null}
# wird von der Firmware ebenfalls nicht unterstützt ("address not found",
# Fehler 404). Es funktionieren NUR einzelne, konkrete, existierende
# Blattpfade - siehe POLL_PATHS unten und coordinator.py.
PATH_IDENTITY_VENDOR = ("device", "identity", "vendor")
PATH_IDENTITY_PRODUCT = ("device", "identity", "product")
PATH_IDENTITY_SERIAL = ("device", "identity", "serial")
PATH_IDENTITY_VERSION = ("device", "identity", "version")

PATH_SAVE_SETTINGS = ("device", "save_settings")

PATH_LOGO_BRIGHTNESS = ("ui", "logo", "brightness")

# Eingangsverstärkung: liegt bei der KH 120 II unter "ui", NICHT unter
# "audio/in/gain" (das war die falsche KH-80-Annahme).
PATH_INPUT_GAIN = ("ui", "input_gain")

PATH_OUTPUT_LEVEL = ("audio", "out", "level")
PATH_OUTPUT_DIMM = ("audio", "out", "dimm")  # nicht im -q-Dump enthalten - evtl. modellabhängig, siehe README
PATH_OUTPUT_DELAY = ("audio", "out", "delay")
PATH_OUTPUT_MUTE = ("audio", "out", "mute")
# Es gibt nur EINE Phasenumkehr für den gesamten Ausgang, keine getrennte
# Ein-/Ausgangs-Phasenumkehr (die alte "phase_correction"/"phase_invert"
# Unterscheidung existiert bei der KH 120 II nicht).
PATH_OUTPUT_PHASE_INVERSION = ("audio", "out", "phaseinversion")

# Live-Pegelmessung: liegt unter "m/in/level" und liefert eine LISTE von
# Werten (ein Wert pro Kanal, z. B. [-122.8, -122.8]), kein Einzelwert.
PATH_METER_INPUT_LEVEL = ("m", "in", "level")

# Clip-Indikator: liegt unter "m/in/clip", ebenfalls eine LISTE (ein
# Bool-Wert pro Kanal), analog zu PATH_METER_INPUT_LEVEL.
PATH_METER_CLIP = ("m", "in", "clip")

# Auto-Standby (Energiesparfunktion). Wertebereiche für auto_standby_time
# (Minuten) und level (dB-Schwellwert) sind NICHT offiziell dokumentiert -
# die Grenzen unten sind konservative Schätzwerte basierend auf dem
# beobachteten Standardwert (30 Minuten / -60 dB). Das Gerät lehnt zu weit
# außerhalb liegende Werte im Zweifel einfach ab (siehe SSCDeviceError).
PATH_STANDBY_ENABLED = ("device", "standby", "enabled")
PATH_STANDBY_AUTO_TIME = ("device", "standby", "auto_standby_time")
PATH_STANDBY_LEVEL = ("device", "standby", "level")
PATH_STANDBY_COUNTDOWN = ("device", "standby", "countdown")  # nur lesbar, Restzeit bis Standby

# Gerät identifizieren: True lässt lt. SSC-Konvention (siehe Sennheiser SSC
# Developer's Guide, "identification"-Container) das Logo/die LEDs kurz
# blinken, um das physische Gerät zu finden.
PATH_IDENTIFY = ("device", "identification", "visual")

# Klangregler. ACHTUNG: Die Firmware liefert diese Werte als JSON-STRINGS
# (z. B. "0"), nicht als Zahlen - siehe value_is_string in number.py.
# Wertebereich NICHT offiziell dokumentiert und NICHT gegen echte Hardware
# verifiziert (bewusst vorsichtig gewählt).
PATH_UI_BASS_GAIN = ("ui", "bass_gain")
PATH_UI_MID_GAIN = ("ui", "mid_gain")
PATH_UI_TREBLE_GAIN = ("ui", "treble_gain")

# Reine Info-/Diagnose-Pfade (nur lesbar)
PATH_DEVICE_NAME = ("device", "name")
PATH_IDENTITY_HW_VERSION = ("device", "identity", "hw_version")
PATH_INPUT_CURRENT = ("audio", "in", "current_input")
PATH_INPUT_INTERFACE_TYPE = ("audio", "in", "interface")
PATH_UI_CONTROL_MODE = ("ui", "control_mode")
PATH_WARNINGS = ("warnings",)  # Top-Level-Schlüssel, keine Verschachtelung

# Blattpfade, die der Coordinator bei jedem Poll-Zyklus EINZELN abfragt
# (jeweils eine eigene, spezifische SSC-Nachricht - siehe coordinator.py für
# die Begründung: weder Sammelnachrichten noch Container-Abfragen wie
# {"device":null} werden von der getesteten Firmware unterstützt, NUR
# einzelne, konkrete, existierende Blattpfade funktionieren zuverlässig).
# Geräte-Identität (Hersteller/Modell/Seriennummer) wird bewusst NICHT
# wiederholt gepollt - die wird bereits einmalig beim Einrichten abgefragt
# und in den Config-Entry-Daten gespeichert.
POLL_PATHS = (
    PATH_INPUT_GAIN,
    PATH_OUTPUT_LEVEL,
    PATH_OUTPUT_DIMM,
    PATH_OUTPUT_DELAY,
    PATH_OUTPUT_MUTE,
    PATH_OUTPUT_PHASE_INVERSION,
    PATH_METER_INPUT_LEVEL,
    PATH_METER_CLIP,
    PATH_STANDBY_ENABLED,
    PATH_STANDBY_AUTO_TIME,
    PATH_STANDBY_LEVEL,
    PATH_STANDBY_COUNTDOWN,
    PATH_UI_BASS_GAIN,
    PATH_UI_MID_GAIN,
    PATH_UI_TREBLE_GAIN,
    PATH_DEVICE_NAME,
    PATH_IDENTITY_HW_VERSION,
    PATH_INPUT_CURRENT,
    PATH_INPUT_INTERFACE_TYPE,
    PATH_UI_CONTROL_MODE,
    PATH_WARNINGS,
)

# Wertebereiche lt. khtool --help
LEVEL_MIN = 0.0
LEVEL_MAX = 120.0
DIMM_MIN = -120.0
DIMM_MAX = 0.0
DELAY_MIN = 0
DELAY_MAX = 3360
BRIGHTNESS_MIN = 0
BRIGHTNESS_MAX = 100

# Unten: NICHT offiziell dokumentiert, NICHT gegen echte Hardware
# verifiziert - konservativ geschätzt anhand beobachteter Standardwerte.
# Das Gerät lehnt außerhalb seines tatsächlichen Bereichs liegende Werte
# einfach ab (SSCDeviceError -> klare HA-Fehlermeldung, kein Risiko).
STANDBY_AUTO_TIME_MIN = 1
STANDBY_AUTO_TIME_MAX = 90
STANDBY_LEVEL_MIN = -90.0
STANDBY_LEVEL_MAX = 0.0
TONE_GAIN_MIN = -12.0
TONE_GAIN_MAX = 12.0
