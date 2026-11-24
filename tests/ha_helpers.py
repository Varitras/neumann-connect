"""Test helpers that come from whichever Home Assistant test plugin is installed.

Home Assistant ships its own plugin since 2026.11. The job for the minimum
version runs an older release and still needs the plugin before it. Once
hacs.json reaches 2026.11, the import below is all that stays.

Never import this from conftest.py: the nested pytest run in
test_deprecations.py loads conftest before the plugin, and the plugin then
refuses to start because the recorder is already imported.
"""

try:
    from pytest_homeassistant.common import MockConfigEntry
except ModuleNotFoundError as error:
    if error.name != "pytest_homeassistant":
        raise
    from pytest_homeassistant_custom_component.common import MockConfigEntry

__all__ = ["MockConfigEntry"]
