"""Authenticated download of backup and discovery exports.

Earlier versions wrote these exports as JSON files under `/config/www/`, which
Home Assistant serves under `/local/` **without any authentication** - anyone
who could reach the HA instance could fetch a device export by guessing the
file name. Nothing is written to disk any more: the data already lives in the
HA store (see storage.py) and is served from there through this view, which
requires authentication like any other HA API endpoint.

Persistent notifications link to it via a signed URL, so a click in the
notification works in the browser without an Authorization header while the
endpoint itself stays protected.
"""

from __future__ import annotations

from typing import Any

from aiohttp import web
from homeassistant.components.http import HomeAssistantView
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from . import storage
from .const import CONF_SERIAL, DOMAIN

EXPORT_KIND_BACKUP = "backup"
EXPORT_KIND_DISCOVERY = "discovery"

_URL_BASE = f"/api/{DOMAIN}/export"
_VIEW_REGISTERED_KEY = f"{DOMAIN}_export_view_registered"


def async_export_path(entry: ConfigEntry, kind: str) -> str:
    """Build the (unsigned) URL path for one entry's export."""
    return f"{_URL_BASE}/{kind}/{entry.entry_id}"


class NeumannKHExportView(HomeAssistantView):
    """Serves a stored backup or discovery record as a JSON download."""

    url = _URL_BASE + "/{kind}/{entry_id}"
    name = f"api:{DOMAIN}:export"
    # requires_auth is on by default; spelled out because it is the whole
    # point of this view.
    requires_auth = True

    async def get(self, request: web.Request, kind: str, entry_id: str) -> web.Response:
        hass: HomeAssistant = request.app["hass"]

        entry = hass.config_entries.async_get_entry(entry_id)
        if entry is None or entry.domain != DOMAIN:
            return web.Response(status=404)

        serial = entry.data.get(CONF_SERIAL) or entry.entry_id
        record: dict[str, Any] | None
        if kind == EXPORT_KIND_BACKUP:
            record = await storage.async_get_backup(hass, serial)
        elif kind == EXPORT_KIND_DISCOVERY:
            record = await storage.async_get_discovery(hass, serial)
        else:
            return web.Response(status=404)

        if record is None:
            return web.Response(status=404)

        # The stored record already carries a masked serial only.
        filename = f"{DOMAIN}_{kind}_{entry_id}.json"
        return self.json(
            record,
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )


def async_register_export_view(hass: HomeAssistant) -> None:
    """Register the view once, no matter how many speakers are set up."""
    # Deliberately not stored in hass.data[DOMAIN]: that dict is keyed by
    # entry_id and is emptied per entry on unload. The view stays registered
    # for the lifetime of the HA process, so its marker must too.
    if hass.data.get(_VIEW_REGISTERED_KEY):
        return
    hass.http.register_view(NeumannKHExportView())
    hass.data[_VIEW_REGISTERED_KEY] = True
