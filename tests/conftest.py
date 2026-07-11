"""Gemeinsame Test-Konfiguration.

Macht das Repo-Root importierbar (`custom_components.neumann_kh...`),
unabhängig davon, aus welchem Verzeichnis pytest gestartet wird.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
