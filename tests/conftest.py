"""Shared test configuration.

Makes the repo root importable (`custom_components.neumann_kh...`)
regardless of the directory pytest is started from.

The suite targets Linux (WSL2 or CI) and does not run on native Windows:
pytest-homeassistant-custom-component imports `homeassistant.runner` at
collection time, which imports the Unix-only `fcntl` module.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
