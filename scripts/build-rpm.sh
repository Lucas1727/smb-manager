#!/usr/bin/env bash
# Build an installable RPM from this checkout in one shot.
#
#   ./build-rpm.sh            # build binary RPM (default)
#   ./build-rpm.sh srpm       # build only the source RPM
#   ./build-rpm.sh mock       # clean-room build via mock (catches missing deps)
#
# The binary build uses packages already on your system. Before distributing,
# run the `mock` target -- it builds in a minimal chroot and is the real test
# that BuildRequires/Requires are complete.
set -euo pipefail

REPO="$(cd "$(dirname "$0")/.." && pwd)"
SPEC="$REPO/packaging/smb-manager.spec"

# Pull Name/Version straight from the spec so the tarball name always matches.
NAME=$(rpmspec -q --qf '%{name}\n' "$SPEC" 2>/dev/null | head -1)
VERSION=$(rpmspec -q --qf '%{version}\n' "$SPEC" 2>/dev/null | head -1)
PKG="${NAME}-${VERSION}"
MOCK_ROOT="${MOCK_ROOT:-fedora-$(rpm -E %fedora)-$(uname -m)}"

TOPDIR="$(rpm -E %_topdir)"   # usually ~/rpmbuild
mkdir -p "$TOPDIR"/{SOURCES,SPECS,SRPMS,RPMS,BUILD}

echo ">> staging source tarball: ${PKG}.tar.gz"
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT
mkdir -p "$TMP/$PKG"
rsync -a \
    --exclude='.git' --exclude='__pycache__' --exclude='dist' \
    --exclude='build' --exclude='*.egg-info' \
    "$REPO"/ "$TMP/$PKG/"
tar -C "$TMP" -czf "$TOPDIR/SOURCES/${PKG}.tar.gz" "$PKG"
cp "$SPEC" "$TOPDIR/SPECS/"

case "${1:-binary}" in
    srpm)
        rpmbuild -bs "$TOPDIR/SPECS/$(basename "$SPEC")"
        ;;
    mock)
        rpmbuild -bs "$TOPDIR/SPECS/$(basename "$SPEC")"
        SRPM=$(ls -t "$TOPDIR"/SRPMS/${PKG}-*.src.rpm | head -1)
        echo ">> mock build in $MOCK_ROOT"
        mock -r "$MOCK_ROOT" "$SRPM"
        echo ">> artifacts in /var/lib/mock/${MOCK_ROOT}/result/"
        ;;
    binary|"")
        rpmbuild -bb "$TOPDIR/SPECS/$(basename "$SPEC")"
        echo
        echo ">> built:"
        ls -1 "$TOPDIR"/RPMS/noarch/${PKG}-*.rpm
        echo ">> install with: sudo dnf install <path-above>"
        ;;
    *)
        echo "usage: $0 [binary|srpm|mock]" >&2
        exit 2
        ;;
esac
