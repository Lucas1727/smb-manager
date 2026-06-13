Name:           smb-manager
Version:        0.1.0
Release:        1%{?dist}
Summary:        A GTK4 UI for sharing folders over SMB

License:        MIT
URL:            https://example.com/smb-manager
Source0:        %{name}-%{version}.tar.gz

BuildArch:      noarch
BuildRequires:  python3-devel
BuildRequires:  pyproject-rpm-macros
BuildRequires:  systemd-rpm-macros

Requires:       python3-gobject
Requires:       gtk4
Requires:       libadwaita
Requires:       samba
Requires:       polkit
# semanage / restorecon, for labeling shared dirs with samba_share_t
Requires:       policycoreutils-python-utils
Requires:       policycoreutils
# firewalld is optional at runtime; the daemon degrades gracefully without it
Recommends:     firewalld
# Pulls in the Requires(post)/Requires(preun)/Requires(postun) on systemd
# needed by the %%systemd_* scriptlet macros below.
%{?systemd_requires}

%description
SMB Manager provides a desktop UI for exporting local folders as SMB
network shares. An unprivileged GTK front-end talks to a small root daemon
over D-Bus; privileged actions are authorized through polkit. Shares are
stored in Samba's registry configuration.

%prep
%autosetup

%generate_buildrequires
%pyproject_buildrequires

%build
%pyproject_wheel

%install
%pyproject_install

# Relocate the daemon console script to libexec; it is not a user command.
mkdir -p %{buildroot}%{_libexecdir}
mv %{buildroot}%{_bindir}/smb-manager-daemon \
   %{buildroot}%{_libexecdir}/smb-manager-daemon

install -Dm644 data/org.smbmanager.App.desktop \
   %{buildroot}%{_datadir}/applications/org.smbmanager.App.desktop
install -Dm644 data/org.smbmanager.policy \
   %{buildroot}%{_datadir}/polkit-1/actions/org.smbmanager.policy
install -Dm644 data/org.smbmanager.Manager.service \
   %{buildroot}%{_datadir}/dbus-1/system-services/org.smbmanager.Manager.service
install -Dm644 data/org.smbmanager.Manager.conf \
   %{buildroot}%{_datadir}/dbus-1/system.d/org.smbmanager.Manager.conf
install -Dm644 data/smb-manager-daemon.service \
   %{buildroot}%{_unitdir}/smb-manager-daemon.service

# The daemon is D-Bus-activated (it has no [Install] section), so these macros
# don't enable it at boot -- they just keep systemd's view in sync. dbus-daemon
# and polkitd pick up the dropped .conf/.policy files automatically via inotify.
%post
%systemd_post smb-manager-daemon.service

%preun
%systemd_preun smb-manager-daemon.service

%postun
%systemd_postun smb-manager-daemon.service

%files
%license LICENSE
%doc README.md
%{_bindir}/smb-manager
%{_libexecdir}/smb-manager-daemon
%{python3_sitelib}/smbmanager/
%{python3_sitelib}/smb_manager-*.dist-info/
%{_datadir}/applications/org.smbmanager.App.desktop
%{_datadir}/polkit-1/actions/org.smbmanager.policy
%{_datadir}/dbus-1/system-services/org.smbmanager.Manager.service
%{_datadir}/dbus-1/system.d/org.smbmanager.Manager.conf
%{_unitdir}/smb-manager-daemon.service

%changelog
* Wed Jun 10 2026 You <you@example.com> - 0.1.0-1
- Initial package
