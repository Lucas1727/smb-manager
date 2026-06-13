"""Privileged Samba share management.

Everything in this module runs as root (it is only imported by the daemon).
Shares are stored in Samba's *registry* config rather than by editing
/etc/samba/smb.conf as text -- this is atomic and avoids fragile parsing.

The one-time bootstrap adds `include = registry` to smb.conf so that smbd
actually reads the registry shares.
"""

from __future__ import annotations

import logging
import os
import re
import shutil
import subprocess

log = logging.getLogger("smb-manager.samba")

SMB_CONF = "/etc/samba/smb.conf"
SERVICE = "smb"  # Fedora's smbd unit is named `smb`


class SambaError(Exception):
    """Raised when an underlying system command fails."""


def _run(argv: list[str], *, check: bool = True, input_text: str | None = None) -> str:
    """Run a command, returning stdout. Raises SambaError on failure."""
    log.debug("run: %s", " ".join(argv))
    proc = subprocess.run(
        argv,
        capture_output=True,
        text=True,
        input=input_text,
    )
    if check and proc.returncode != 0:
        raise SambaError(
            f"`{' '.join(argv)}` failed ({proc.returncode}): "
            f"{proc.stderr.strip() or proc.stdout.strip()}"
        )
    return proc.stdout


# --------------------------------------------------------------------------- #
# One-time bootstrap                                                          #
# --------------------------------------------------------------------------- #

def ensure_registry_enabled() -> None:
    """Make smb.conf read shares from the registry, and start smbd."""
    try:
        with open(SMB_CONF, "r", encoding="utf-8") as fh:
            conf = fh.read()
    except FileNotFoundError:
        conf = "[global]\n\tworkgroup = WORKGROUP\n\tserver role = standalone server\n"

    if not re.search(r"^\s*include\s*=\s*registry", conf, re.MULTILINE):
        # Insert `include = registry` into the [global] section.
        if re.search(r"^\s*\[global\]", conf, re.MULTILINE | re.IGNORECASE):
            conf = re.sub(
                r"(^\s*\[global\][^\n]*\n)",
                r"\1\tinclude = registry\n",
                conf,
                count=1,
                flags=re.MULTILINE | re.IGNORECASE,
            )
        else:
            conf = "[global]\n\tinclude = registry\n\n" + conf

        # Keep a backup the first time we touch the file.
        if os.path.exists(SMB_CONF) and not os.path.exists(SMB_CONF + ".smb-manager.bak"):
            shutil.copy2(SMB_CONF, SMB_CONF + ".smb-manager.bak")
        with open(SMB_CONF, "w", encoding="utf-8") as fh:
            fh.write(conf)
        log.info("enabled registry config in %s", SMB_CONF)

    # Make sure the service is up; ignore failure so listing still works.
    _run(["systemctl", "enable", "--now", SERVICE], check=False)


def _reload() -> None:
    """Tell a running smbd to re-read config (no client disruption)."""
    _run(["smbcontrol", "all", "reload-config"], check=False)


# --------------------------------------------------------------------------- #
# SELinux + firewall                                                          #
# --------------------------------------------------------------------------- #

# Filesystems that store SELinux labels in xattrs, where per-file labeling
# works. Anything else (FUSE, exFAT/NTFS/vfat, network mounts) cannot hold a
# samba_share_t label and needs the export boolean instead.
_LABELABLE_FS = {"ext2", "ext3", "ext4", "xfs", "btrfs", "gfs2"}


def _fstype(path: str) -> str:
    return _run(
        ["findmnt", "-no", "FSTYPE", "--target", path], check=False
    ).strip()


def _apply_selinux(path: str, read_only: bool) -> None:
    """Allow smbd to serve `path` under SELinux.

    On ordinary disk filesystems we label the directory ``samba_share_t``. On
    filesystems that can't hold per-file labels -- FUSE (the usual driver for
    external NTFS/exFAT drives under /run/media), vfat, network mounts -- that
    label can't be applied, so we instead enable the host-wide
    ``samba_export_all_{ro,rw}`` boolean, which lets smbd access files
    regardless of their SELinux type.
    """
    if not shutil.which("setsebool"):
        return  # no SELinux tooling present -- nothing to do.

    fstype = _fstype(path)
    if fstype in _LABELABLE_FS and shutil.which("semanage"):
        # Persistent fcontext rule + relabel; ignore "already exists".
        _run(
            ["semanage", "fcontext", "-a", "-t", "samba_share_t", f"{path}(/.*)?"],
            check=False,
        )
        _run(["restorecon", "-R", path], check=False)
    else:
        # Unlabelable filesystem: grant smbd blanket export access. These
        # booleans are host-wide and persistent (-P).
        _run(["setsebool", "-P", "samba_export_all_ro", "on"], check=False)
        if not read_only:
            _run(["setsebool", "-P", "samba_export_all_rw", "on"], check=False)


def _open_firewall() -> None:
    if not shutil.which("firewall-cmd"):
        return
    _run(["firewall-cmd", "--permanent", "--add-service=samba"], check=False)
    _run(["firewall-cmd", "--reload"], check=False)


# --------------------------------------------------------------------------- #
# Share CRUD via `net conf`                                                   #
# --------------------------------------------------------------------------- #

_VALID_NAME = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9 _\-]{0,79}$")


def _validate_name(name: str) -> None:
    if name.lower() == "global" or not _VALID_NAME.match(name):
        raise SambaError(f"invalid share name: {name!r}")


def list_shares() -> list[dict]:
    """Return all registry shares (excluding [global])."""
    out = _run(["net", "conf", "listshares"], check=False)
    shares = []
    for raw in out.splitlines():
        name = raw.strip()
        if not name or name.lower() == "global":
            continue
        shares.append(_show_share(name))
    return shares


def _show_share(name: str) -> dict:
    out = _run(["net", "conf", "showshare", name], check=False)
    params: dict[str, str] = {}
    for line in out.splitlines():
        if "=" in line:
            key, _, value = line.partition("=")
            params[key.strip().lower()] = value.strip()
    read_only = params.get("read only", params.get("writeable", "no"))
    return {
        "name": name,
        "path": params.get("path", ""),
        "comment": params.get("comment", ""),
        "read_only": read_only.lower() in ("yes", "true", "1")
        if "read only" in params
        else params.get("writeable", "yes").lower() in ("no", "false", "0"),
        "guest_ok": params.get("guest ok", "no").lower() in ("yes", "true", "1"),
    }


def add_share(
        name: str,
        path: str,
        comment: str = "",
        read_only: bool = False,
        guest_ok: bool = False,
) -> None:
    """Create or update a share and wire up the surrounding system bits."""
    _validate_name(name)
    if not os.path.isabs(path):
        raise SambaError(f"path must be absolute: {path!r}")

    ensure_registry_enabled()

    os.makedirs(path, exist_ok=True)
    _apply_selinux(path, read_only)
    _open_firewall()

    # Replace any existing definition so this is idempotent.
    _run(["net", "conf", "delshare", name], check=False)

    # Create with only the required args. addshare's optional positional args
    # use a "writeable=y"/"guest_ok=N" syntax that is easy to get wrong; we set
    # every option explicitly with setparm instead, which is unambiguous.
    _run(["net", "conf", "addshare", name, path])
    _setparm(name, "path", path)
    _setparm(name, "read only", "yes" if read_only else "no")
    _setparm(name, "guest ok", "yes" if guest_ok else "no")
    _setparm(name, "browseable", "yes")
    if comment:
        _setparm(name, "comment", comment)
    if guest_ok:
        _setparm(name, "guest only", "no")

    _reload()
    log.info("added share %s -> %s", name, path)


def _setparm(share: str, key: str, value: str) -> None:
    # check=True: a failed setparm means the share is misconfigured, so surface
    # it rather than silently leaving a half-built share.
    _run(["net", "conf", "setparm", share, key, value])


def remove_share(name: str) -> None:
    """Delete a share definition (leaves the directory on disk untouched)."""
    _validate_name(name)
    _run(["net", "conf", "delshare", name])
    _reload()
    log.info("removed share %s", name)


# --------------------------------------------------------------------------- #
# Samba users                                                                 #
# --------------------------------------------------------------------------- #

def set_user_password(username: str, password: str) -> None:
    """Add/update a Samba user. The system account must already exist."""
    if not re.match(r"^[a-z_][a-z0-9_-]*$", username):
        raise SambaError(f"invalid username: {username!r}")
    # `smbpasswd -s -a` reads the password twice from stdin.
    _run(
        ["smbpasswd", "-s", "-a", username],
        input_text=f"{password}\n{password}\n",
    )
    log.info("set samba password for %s", username)


def service_status() -> str:
    return _run(["systemctl", "is-active", SERVICE], check=False).strip() or "unknown"
