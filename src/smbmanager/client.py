"""Thin client over the system-bus daemon, used by the GTK UI.

Calls block briefly; AddShare/RemoveShare may trigger a polkit dialog, so the
UI runs them off the main loop (see window.py).
"""

from __future__ import annotations

import json

import gi

gi.require_version("Gio", "2.0")
from gi.repository import Gio, GLib  # noqa: E402

BUS_NAME = "org.smbmanager.Manager"
OBJECT_PATH = "/org/smbmanager/Manager"


class DaemonError(Exception):
    pass


class Client:
    def __init__(self) -> None:
        self._proxy = Gio.DBusProxy.new_for_bus_sync(
            Gio.BusType.SYSTEM,
            Gio.DBusProxyFlags.NONE,
            None,
            BUS_NAME,
            OBJECT_PATH,
            BUS_NAME,
            None,
        )

    def _call(self, method: str, variant: GLib.Variant | None = None) -> GLib.Variant:
        try:
            return self._proxy.call_sync(
                method,
                variant,
                Gio.DBusCallFlags.NONE,
                -1,  # the polkit prompt can take a while; no client timeout
                None,
            )
        except GLib.Error as exc:
            raise DaemonError(_clean(exc.message)) from exc

    def list_shares(self) -> list[dict]:
        result = self._call("ListShares")
        return json.loads(result.unpack()[0])

    def service_status(self) -> str:
        return self._call("GetServiceStatus").unpack()[0]

    def add_share(
        self,
        name: str,
        path: str,
        comment: str,
        read_only: bool,
        guest_ok: bool,
    ) -> None:
        self._call(
            "AddShare",
            GLib.Variant("(sssbb)", (name, path, comment, read_only, guest_ok)),
        )

    def remove_share(self, name: str) -> None:
        self._call("RemoveShare", GLib.Variant("(s)", (name,)))

    def set_user_password(self, username: str, password: str) -> None:
        self._call(
            "SetUserPassword", GLib.Variant("(ss)", (username, password))
        )


def _clean(message: str) -> str:
    """Strip the GDBus remote-error prefix for friendlier display."""
    marker = "org.smbmanager.Manager."
    if marker in message:
        message = message.split(":", 1)[-1].strip()
    return message
