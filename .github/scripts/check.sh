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

# NOT a gate yet: `ruff format --check` reports 23 files at the time of
# writing, and reformatting them is a decision of its own, not something to
# smuggle in with a bug fix. Named here so the omission is visible.
step "ruff format: NOT ENFORCED"
"$PYTHON" -m ruff format --check --no-cache "$PACKAGE" tests tools || true

step "pytest (full run, e2e included)"
"$PYTHON" -m pytest tests/ -q -m ""

step "compile every module"
"$PYTHON" -m compileall -q "$PACKAGE"

# Dead parallel stacks misled debugging in sibling projects; confidence 90
# keeps false positives near zero.
step "dead code (vulture)"
if "$PYTHON" -c "import vulture" 2>/dev/null; then
    "$PYTHON" -m vulture "$PACKAGE" --min-confidence 90
else
    echo "SKIPPED: vulture not installed - dead parallel stacks stay invisible"
fi

if [ -f .github/mutations/plan.json ]; then
    step "mutation run"
    "$PYTHON" .github/scripts/mutate.py .github/mutations/plan.json
else
    step "mutation run: SKIPPED"
    echo "no mutation plan - decorative tests stay invisible until one exists"
fi

printf '\nAll gates green.\n'
