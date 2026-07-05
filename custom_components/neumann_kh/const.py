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
# realen Dump verifiziert. Nicht-existierende Pfade wurden entfernt, da ein
# einzelner unbekannter Pfad in einer SSC-Anfrage laut Testergebnis
# ("message not understood", OSC-Fehler 400) die GESAMTE Anfrage zum
# Scheitern bringt - deshalb fragt der Coordinator jetzt ganze Container ab
# (siehe SSC_POLL_CONTAINERS) statt einzelne, möglicherweise falsche Blätter.
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

# Container, die der Coordinator bei jedem Poll-Zyklus EINZELN (als jeweils
# eigene SSC-Nachricht) abfragt. Das Gerät expandiert einen Container
# automatisch in alle vorhandenen Blätter - dadurch muss nie ein
# möglicherweise falscher/nicht-existierender Blattname geraten werden.
SSC_POLL_CONTAINERS = ("device", "ui", "audio", "m")

# Wertebereiche lt. khtool --help
LEVEL_MIN = 0.0
LEVEL_MAX = 120.0
DIMM_MIN = -120.0
DIMM_MAX = 0.0
DELAY_MIN = 0
DELAY_MAX = 3360
BRIGHTNESS_MIN = 0
BRIGHTNESS_MAX = 100
