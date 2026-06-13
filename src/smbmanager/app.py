"""GTK application entry point (unprivileged)."""

from __future__ import annotations

import sys

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gio  # noqa: E402

from .window import SmbManagerWindow  # noqa: E402

APP_ID = "org.smbmanager.App"


class SmbManagerApp(Adw.Application):
    def __init__(self) -> None:
        super().__init__(
            application_id=APP_ID,
            flags=Gio.ApplicationFlags.DEFAULT_FLAGS,
        )

    def do_activate(self) -> None:
        win = self.props.active_window
        if not win:
            win = SmbManagerWindow(application=self)
        win.present()


def main() -> int:
    return SmbManagerApp().run(sys.argv)


if __name__ == "__main__":
    sys.exit(main())
