# SMB Manager (Fedora)

A GTK4 / libadwaita desktop app for **sharing local folders over SMB** on
Fedora. Pick a folder, give it a name, and it becomes a network share — no
hand-editing `smb.conf`.

## How it works

```
┌────────────────────┐   D-Bus (system bus)    ┌─────────────────────────┐
│  GTK4 UI            │ ──────────────────────► │  smb-manager-daemon   │
│  (runs as you)      │                         │  (runs as root)         │
│  app.py / window.py │ ◄────── polkit ───────► │  daemon.py / samba.py   │
└────────────────────┘   auth prompt on writes  └───────────┬─────────────┘
                                                            │
                                              net conf / smbpasswd / smbcontrol
                                              semanage + restorecon (SELinux)
                                              firewall-cmd (firewalld)
                                                            ▼
                                                    Samba registry + smbd
```

- The **UI is unprivileged.** It never edits system files directly.
- The **daemon is the only root component.** Each state-changing D-Bus method
  is gated by **polkit** (`org.smbmanager.manage-shares`), so the user sees a
  native authentication dialog rather than the app running as root.
- Shares live in **Samba's registry** (`net conf …`), not in a text file —
  atomic and parse-free. A one-time bootstrap adds `include = registry` to
  `smb.conf`.
- Creating a share also handles the Fedora-specific plumbing: **SELinux**
  labeling (`samba_share_t`), **firewalld** (`samba` service), and starting the
  `smb` unit.

## Layout

| Path | Purpose |
|---|---|
| `src/smbmanager/app.py`, `window.py` | GTK4 UI (unprivileged) |
| `src/smbmanager/client.py` | D-Bus client used by the UI |
| `src/smbmanager/daemon.py` | Root D-Bus service + polkit checks |
| `src/smbmanager/samba.py` | `net conf` / SELinux / firewall logic |
| `data/*.policy` | polkit action definition |
| `data/*.Manager.service`, `*.conf` | D-Bus activation + bus policy |
| `data/*.desktop` | App launcher |
| `packaging/smb-manager.spec` | RPM build |

## Develop & run

Install the runtime dependencies (Fedora):

```bash
sudo dnf install python3-gobject gtk4 libadwaita samba polkit \
                 policycoreutils-python-utils firewalld
```

Wire up the daemon, polkit policy and D-Bus files from this checkout:

```bash
./install-dev.sh            # uses sudo only where required
```

Run the UI:

```bash
PYTHONPATH=src python3 -m smbmanager.app
```

Adding a share will pop a polkit authentication dialog. Verify from another
machine (or `smbclient -L localhost -U <user>`).

Tear down the system files again:

```bash
./install-dev.sh uninstall
```

## Build an RPM

```bash
# from a release tarball named smb-manager-0.1.0.tar.gz in ~/rpmbuild/SOURCES
rpmbuild -ba packaging/smb-manager.spec
```

For distribution, push the spec + tarball to **Fedora COPR** for automated
builds and a yum repo.

## Status

Scaffold / proof of concept. Working: list, add, remove shares; Samba user
passwords; SELinux + firewall handling. Not yet done: per-user access control
UI, editing existing shares, share-level user lists, icon assets, tests.
