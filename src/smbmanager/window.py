"""Main application window (GTK4 + libadwaita)."""

from __future__ import annotations

import threading

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gio, GLib, GObject, Gtk  # noqa: E402

from .client import Client, DaemonError  # noqa: E402


class SmbManagerWindow(Adw.ApplicationWindow):
    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self.set_title("SMB Manager")
        self.set_default_size(640, 520)

        self._client = Client()

        # ----- header bar ------------------------------------------------- #
        header = Adw.HeaderBar()
        add_btn = Gtk.Button(icon_name="list-add-symbolic")
        add_btn.set_tooltip_text("Add share")
        add_btn.connect("clicked", self._on_add_clicked)
        header.pack_start(add_btn)

        refresh_btn = Gtk.Button(icon_name="view-refresh-symbolic")
        refresh_btn.set_tooltip_text("Refresh")
        refresh_btn.connect("clicked", lambda *_: self.refresh())
        header.pack_end(refresh_btn)

        # ----- content ---------------------------------------------------- #
        self._toasts = Adw.ToastOverlay()
        self._stack = Gtk.Stack()
        self._toasts.set_child(self._stack)

        # Empty-state page.
        self._empty = Adw.StatusPage(
            icon_name="folder-remote-symbolic",
            title="No Shared Folders",
            description="Click + to share a folder over SMB.",
        )
        self._stack.add_named(self._empty, "empty")

        # List page.
        self._list = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE)
        self._list.add_css_class("boxed-list")
        clamp = Adw.Clamp(margin_top=18, margin_bottom=18,
                          margin_start=18, margin_end=18)
        clamp.set_child(self._list)
        scroller = Gtk.ScrolledWindow()
        scroller.set_child(clamp)
        self._stack.add_named(scroller, "list")

        toolbar = Adw.ToolbarView()
        toolbar.add_top_bar(header)
        toolbar.set_content(self._toasts)
        self.set_content(toolbar)

        self.refresh()

    # ----- data ----------------------------------------------------------- #

    def refresh(self) -> None:
        try:
            shares = self._client.list_shares()
            status = self._client.service_status()
        except DaemonError as exc:
            self._toast(f"Could not reach service: {exc}")
            return

        child = self._list.get_first_child()
        while child is not None:
            self._list.remove(child)
            child = self._list.get_first_child()

        if not shares:
            self._stack.set_visible_child_name("empty")
            return

        self._stack.set_visible_child_name("list")
        for share in shares:
            self._list.append(self._make_row(share, status))

    def _make_row(self, share: dict, status: str) -> Adw.ActionRow:
        subtitle = share["path"]
        tags = []
        if share["read_only"]:
            tags.append("read-only")
        if share["guest_ok"]:
            tags.append("guest")
        if tags:
            subtitle += "  ·  " + ", ".join(tags)

        row = Adw.ActionRow(title=share["name"], subtitle=subtitle)
        row.add_prefix(Gtk.Image.new_from_icon_name("folder-publicshare-symbolic"))

        remove = Gtk.Button(icon_name="user-trash-symbolic")
        remove.add_css_class("flat")
        remove.set_valign(Gtk.Align.CENTER)
        remove.set_tooltip_text("Remove share")
        remove.connect("clicked", lambda *_: self._confirm_remove(share["name"]))
        row.add_suffix(remove)
        return row

    # ----- actions -------------------------------------------------------- #

    def _on_add_clicked(self, _button) -> None:
        dialog = AddShareDialog(self)
        dialog.connect("share-requested", self._on_share_requested)
        dialog.present(self)

    def _on_share_requested(self, _dialog, name, path, comment, read_only, guest_ok):
        self._run_privileged(
            lambda: self._client.add_share(name, path, comment, read_only, guest_ok),
            success=f"Shared “{name}”",
        )

    def _confirm_remove(self, name: str) -> None:
        dialog = Adw.AlertDialog(
            heading=f"Remove “{name}”?",
            body="The share is removed from Samba. The folder and its files stay on disk.",
        )
        dialog.add_response("cancel", "Cancel")
        dialog.add_response("remove", "Remove")
        dialog.set_response_appearance("remove", Adw.ResponseAppearance.DESTRUCTIVE)
        dialog.connect(
            "response",
            lambda _d, resp: resp == "remove"
                             and self._run_privileged(
                lambda: self._client.remove_share(name),
                success=f"Removed “{name}”",
            ),
        )
        dialog.present(self)

    def _run_privileged(self, fn, *, success: str) -> None:
        """Run a daemon call (which may pop a polkit dialog) off the UI thread."""

        def worker():
            try:
                fn()
                GLib.idle_add(self._after, True, success)
            except DaemonError as exc:
                GLib.idle_add(self._after, False, str(exc))

        threading.Thread(target=worker, daemon=True).start()

    def _after(self, ok: bool, message: str) -> bool:
        self._toast(message)
        if ok:
            self.refresh()
        return False  # one-shot idle callback

    def _toast(self, text: str) -> None:
        self._toasts.add_toast(Adw.Toast(title=text, timeout=4))


class AddShareDialog(Adw.Dialog):
    __gsignals__ = {
        "share-requested": (
            GObject.SignalFlags.RUN_FIRST,
            None,
            (str, str, str, bool, bool),
        ),
    }

    def __init__(self, parent) -> None:
        super().__init__(title="Share a Folder")
        self.set_content_width(420)
        self._parent = parent
        self._folder: Gio.File | None = None

        page = Adw.PreferencesPage()
        group = Adw.PreferencesGroup()
        page.add(group)

        self._name = Adw.EntryRow(title="Share name")
        self._name.connect("changed", lambda *_: self._validate())
        group.add(self._name)

        self._folder_row = Adw.ActionRow(
            title="Folder", subtitle="None selected"
        )
        choose = Gtk.Button(label="Choose…", valign=Gtk.Align.CENTER)
        choose.connect("clicked", self._choose_folder)
        self._folder_row.add_suffix(choose)
        group.add(self._folder_row)

        self._comment = Adw.EntryRow(title="Description (optional)")
        group.add(self._comment)

        self._read_only = Adw.SwitchRow(
            title="Read-only", subtitle="Clients cannot write files"
        )
        group.add(self._read_only)

        self._guest = Adw.SwitchRow(
            title="Allow guests", subtitle="Access without a username/password"
        )
        group.add(self._guest)

        # header with Cancel / Create
        header = Adw.HeaderBar(show_start_title_buttons=False,
                               show_end_title_buttons=False)
        cancel = Gtk.Button(label="Cancel")
        cancel.connect("clicked", lambda *_: self.close())
        header.pack_start(cancel)

        self._create = Gtk.Button(label="Create")
        self._create.add_css_class("suggested-action")
        self._create.set_sensitive(False)
        self._create.connect("clicked", self._on_create)
        header.pack_end(self._create)

        toolbar = Adw.ToolbarView()
        toolbar.add_top_bar(header)
        toolbar.set_content(page)
        self.set_child(toolbar)

    def _choose_folder(self, _button) -> None:
        chooser = Gtk.FileDialog(title="Select folder to share")
        chooser.select_folder(self._parent, None, self._on_folder_chosen)

    def _on_folder_chosen(self, dialog, result) -> None:
        try:
            self._folder = dialog.select_folder_finish(result)
        except GLib.Error:
            return  # user cancelled
        self._folder_row.set_subtitle(self._folder.get_path())
        if not self._name.get_text().strip():
            self._name.set_text(self._folder.get_basename() or "")
        self._validate()

    def _validate(self) -> None:
        self._create.set_sensitive(
            bool(self._name.get_text().strip()) and self._folder is not None
        )

    def _on_create(self, _button) -> None:
        self.emit(
            "share-requested",
            self._name.get_text().strip(),
            self._folder.get_path(),
            self._comment.get_text().strip(),
            self._read_only.get_active(),
            self._guest.get_active(),
        )
        self.close()
