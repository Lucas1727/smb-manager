"""Root-privileged D-Bus daemon for SMB Manager.

This is the *only* component that runs as root. The unprivileged GTK UI talks
to it over the system bus. Every state-changing method is gated by polkit, so
the user gets a native authentication prompt -- the UI itself never needs
elevated rights.

Activated on demand by dbus-daemon via the system-services file; it can also be
run directly for development.
"""

from __future__ import annotations

import json
import logging
import sys

import gi

gi.require_version("Gio", "2.0")
from gi.repository import Gio, GLib  # noqa: E402

from . import samba  # noqa: E402

log = logging.getLogger("smb-manager.daemon")

BUS_NAME = "org.smbmanager.Manager"
OBJECT_PATH = "/org/smbmanager/Manager"
POLKIT_ACTION = "org.smbmanager.manage-shares"

INTROSPECTION_XML = """
<node>
  <interface name='org.smbmanager.Manager'>
    <method name='ListShares'>
      <arg type='s' name='shares_json' direction='out'/>
    </method>
    <method name='AddShare'>
      <arg type='s' name='name' direction='in'/>
      <arg type='s' name='path' direction='in'/>
      <arg type='s' name='comment' direction='in'/>
      <arg type='b' name='read_only' direction='in'/>
      <arg type='b' name='guest_ok' direction='in'/>
    </method>
    <method name='RemoveShare'>
      <arg type='s' name='name' direction='in'/>
    </method>
    <method name='SetUserPassword'>
      <arg type='s' name='username' direction='in'/>
      <arg type='s' name='password' direction='in'/>
    </method>
    <method name='GetServiceStatus'>
      <arg type='s' name='status' direction='out'/>
    </method>
  </interface>
</node>
"""

# How long the daemon stays alive with no calls before exiting (seconds).
IDLE_TIMEOUT = 30


class Daemon:
    def __init__(self) -> None:
        self._loop = GLib.MainLoop()
        self._conn: Gio.DBusConnection | None = None
        self._idle_source: int | None = None

    # ----- lifecycle ------------------------------------------------------ #

    def run(self) -> int:
        self._conn = Gio.bus_get_sync(Gio.BusType.SYSTEM, None)
        node = Gio.DBusNodeInfo.new_for_xml(INTROSPECTION_XML)
        self._conn.register_object(
            OBJECT_PATH,
            node.lookup_interface(BUS_NAME),
            self._on_method_call,
            None,
            None,
        )
        Gio.bus_own_name_on_connection(
            self._conn,
            BUS_NAME,
            Gio.BusNameOwnerFlags.NONE,
            None,
            lambda *_: (log.error("lost bus name"), self._loop.quit()),
        )
        self._bump_idle()
        log.info("daemon ready on %s", BUS_NAME)
        self._loop.run()
        return 0

    def _bump_idle(self) -> None:
        if self._idle_source is not None:
            GLib.source_remove(self._idle_source)
        self._idle_source = GLib.timeout_add_seconds(
            IDLE_TIMEOUT, lambda: (self._loop.quit(), False)[1]
        )

    # ----- polkit --------------------------------------------------------- #

    def _check_auth(self, sender: str) -> bool:
        """Ask polkit whether `sender` may perform the privileged action."""
        authority = Gio.DBusProxy.new_sync(
            self._conn,
            Gio.DBusProxyFlags.NONE,
            None,
            "org.freedesktop.PolicyKit1",
            "/org/freedesktop/PolicyKit1/Authority",
            "org.freedesktop.PolicyKit1.Authority",
            None,
        )
        # Build the whole tuple in one GLib.Variant call: round-tripping the
        # subject through .unpack() would turn the a{sv} value back into a plain
        # str, which then fails to re-pack ("Expected GLib.Variant, but got str").
        params = GLib.Variant(
            "((sa{sv})sa{ss}us)",
            (
                ("system-bus-name", {"name": GLib.Variant("s", sender)}),
                POLKIT_ACTION,
                {},
                1,  # AllowUserInteraction -> shows the auth dialog
                "",
            ),
        )
        result = authority.call_sync(
            "CheckAuthorization", params, Gio.DBusCallFlags.NONE, -1, None
        )
        is_authorized, _is_challenge, _details = result.unpack()[0]
        return bool(is_authorized)

    # ----- dispatch ------------------------------------------------------- #

    def _on_method_call(
        self,
        _connection,
        sender,
        _object_path,
        _interface_name,
        method_name,
        parameters,
        invocation,
    ) -> None:
        self._bump_idle()
        try:
            if method_name == "ListShares":
                payload = json.dumps(samba.list_shares())
                invocation.return_value(GLib.Variant("(s)", (payload,)))
                return

            if method_name == "GetServiceStatus":
                invocation.return_value(
                    GLib.Variant("(s)", (samba.service_status(),))
                )
                return

            # Everything below mutates the system -> require authorization.
            if not self._check_auth(sender):
                invocation.return_dbus_error(
                    f"{BUS_NAME}.NotAuthorized",
                    "Authorization required to manage shares.",
                )
                return

            args = parameters.unpack()
            if method_name == "AddShare":
                samba.add_share(*args)
            elif method_name == "RemoveShare":
                samba.remove_share(*args)
            elif method_name == "SetUserPassword":
                samba.set_user_password(*args)
            else:
                invocation.return_dbus_error(
                    f"{BUS_NAME}.UnknownMethod", method_name
                )
                return

            invocation.return_value(GLib.Variant("()", ()))

        except samba.SambaError as exc:
            log.warning("%s failed: %s", method_name, exc)
            invocation.return_dbus_error(f"{BUS_NAME}.Error", str(exc) or repr(exc))
        except Exception as exc:  # noqa: BLE001 -- never crash the daemon
            log.exception("unhandled error in %s", method_name)
            invocation.return_dbus_error(f"{BUS_NAME}.Error", repr(exc))


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(name)s: %(message)s",
    )
    return Daemon().run()


if __name__ == "__main__":
    sys.exit(main())
