#!/bin/sh
# Definition of done, as one command.
#
# Rules this script keeps:
#   * Stop at the first failure.
#   * A skipped gate says so, loudly. A gate that quietly waves through is a lie.
#   * Nothing machine-local is hard-coded; the interpreter arrives via $PYTHON.
#
# The suite is Linux-only (pytest-homeassistant-custom-component imports
# homeassistant.runner -> fcntl), so run this under WSL2 or CI, not native
# Windows.
set -eu
cd "$(git rev-parse --show-toplevel)"

PYTHON="${PYTHON:-python3}"
PACKAGE="custom_components/neumann_kh"

step() { printf '\n== %s ==\n' "$1"; }

step "ruff check"
"$PYTHON" -m ruff check --no-cache .

step "ruff format --check"
"$PYTHON" -m ruff format --check --no-cache "$PACKAGE" tests tools

step "pytest (full run, e2e included)"
"$PYTHON" -m pytest tests/ -q -m ""

step "compile every module"
"$PYTHON" -m compileall -q "$PACKAGE"

# No dead-code gate. vulture was measured against this package and does not
# work here: at confidence 90 all five hits are framework contracts (zeroconf's
# callback signature, Home Assistant's **kwargs on async_turn_on/off), at 60 it
# reports every async_setup_entry, async_press and property, because a Home
# Assistant integration is almost entirely called by the framework. It also
# exits 0 with findings, so the gate could never have failed. The two dead
# functions this project did have were found by review.

if [ -f .github/mutations/plan.json ]; then
    step "mutation run"
    "$PYTHON" .github/scripts/mutate.py .github/mutations/plan.json
else
    step "mutation run: SKIPPED"
    echo "no mutation plan - decorative tests stay invisible until one exists"
fi

printf '\nAll gates green.\n'
