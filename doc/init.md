Sample init scripts and service configuration for b3chaind
==========================================================

Sample scripts and configuration files for systemd, Upstart and OpenRC
can be found in the contrib/init folder.

    contrib/init/b3chaind.service:    systemd service unit configuration
    contrib/init/b3chaind.openrc:     OpenRC compatible SysV style init script
    contrib/init/b3chaind.openrcconf: OpenRC conf.d file
    contrib/init/b3chaind.conf:       Upstart service configuration file
    contrib/init/b3chaind.init:       CentOS compatible SysV style init script

Service User
---------------------------------

All three Linux startup configurations assume the existence of a "b3chain" user
and group.  They must be created before attempting to use these scripts.
The macOS configuration assumes b3chaind will be set up for the current user.

Configuration
---------------------------------

Running b3chaind as a daemon does not require any manual configuration. You may
set the `rpcauth` setting in the `b3chain.conf` configuration file to override
the default behaviour of using a special cookie for authentication.

This password does not have to be remembered or typed as it is mostly used
as a fixed token that b3chaind and client programs read from the configuration
file, however it is recommended that a strong and secure password be used
as this password is security critical to securing the wallet should the
wallet be enabled.

If b3chaind is run with the "-server" flag (set by default), and no rpcpassword is set,
it will use a special cookie file for authentication. The cookie is generated with random
content when the daemon starts, and deleted when it exits. Read access to this file
controls who can access it through RPC.

By default the cookie is stored in the data directory, but its location can be
overridden with the option `-rpccookiefile`. Default file permissions for the
cookie are "owner" (i.e. user read/writeable) via default application-wide file
umask of `0077`, but these can be overridden with the `-rpccookieperms` option.

This allows for running b3chaind without having to do any manual configuration.

`conf`, `pid`, and `wallet` accept relative paths which are interpreted as
relative to the data directory. `wallet` *only* supports relative paths.

To generate an example configuration file that describes the configuration settings,
see [contrib/devtools/README.md](../contrib/devtools/README.md#gen-bitcoin-confsh).

Paths
---------------------------------

### Linux

All three configurations assume several paths that might need to be adjusted.

    Binary:              /usr/bin/b3chaind
    Configuration file:  /etc/b3chain/b3chain.conf
    Data directory:      /var/lib/b3chaind
    PID file:            /var/run/b3chaind/b3chaind.pid (OpenRC and Upstart) or
                         /run/b3chaind/b3chaind.pid (systemd)
    Lock file:           /var/lock/subsys/b3chaind (CentOS)

The PID directory (if applicable) and data directory should both be owned by the
b3chain user and group. It is advised for security reasons to make the
configuration file and data directory only readable by the b3chain user and
group. Access to b3chain-cli and other b3chaind rpc clients can then be
controlled by group membership.

NOTE: When using the systemd .service file, the creation of the aforementioned
directories and the setting of their permissions is automatically handled by
systemd. Directories are given a permission of 710, giving the b3chain group
access to files under it _if_ the files themselves give permission to the
b3chain group to do so. This does not allow
for the listing of files under the directory.

NOTE: It is not currently possible to override `datadir` in
`/etc/b3chain/b3chain.conf` with the current systemd, OpenRC, and Upstart init
files out-of-the-box. This is because the command line options specified in the
init files take precedence over the configurations in
`/etc/b3chain/b3chain.conf`. However, some init systems have their own
configuration mechanisms that would allow for overriding the command line
options specified in the init files (e.g. setting `B3CHAIND_DATADIR` for
OpenRC).

### macOS

    Binary:              /usr/local/bin/b3chaind
    Configuration file:  ~/Library/Application Support/B3Chain/b3chain.conf
    Data directory:      ~/Library/Application Support/B3Chain
    Lock file:           ~/Library/Application Support/B3Chain/.lock

Installing Service Configuration
-----------------------------------

### systemd

Installing this .service file consists of just copying it to
/usr/lib/systemd/system directory, followed by the command
`systemctl daemon-reload` in order to update running systemd configuration.

To test, run `systemctl start b3chaind` and to enable for system startup run
`systemctl enable b3chaind`

NOTE: When installing for systemd in Debian/Ubuntu the .service file needs to be copied to the /lib/systemd/system directory instead.

### OpenRC

Rename b3chaind.openrc to b3chaind and drop it in /etc/init.d.  Double
check ownership and permissions and make it executable.  Test it with
`/etc/init.d/b3chaind start` and configure it to run on startup with
`rc-update add b3chaind`

### Upstart (for Debian/Ubuntu based distributions)

Upstart is the default init system for Debian/Ubuntu versions older than 15.04. If you are using version 15.04 or newer and haven't manually configured upstart you should follow the systemd instructions instead.

Drop b3chaind.conf in /etc/init.  Test by running `service b3chaind start`
it will automatically start on reboot.

NOTE: This script is incompatible with CentOS 5 and Amazon Linux 2014 as they
use old versions of Upstart and do not supply the start-stop-daemon utility.

### CentOS

Copy b3chaind.init to /etc/init.d/b3chaind. Test by running `service b3chaind start`.

Using this script, you can adjust the path and flags to the b3chaind program by
setting the B3CHAIND and FLAGS environment variables in the file
/etc/sysconfig/b3chaind. You can also use the DAEMONOPTS environment variable here.

### macOS

Copy org.b3chain.b3chaind.plist into ~/Library/LaunchAgents. Load the launch agent by
running `launchctl load ~/Library/LaunchAgents/org.b3chain.b3chaind.plist`.

This Launch Agent will cause b3chaind to start whenever the user logs in.

NOTE: This approach is intended for those wanting to run b3chaind as the current user.
You will need to modify org.b3chain.b3chaind.plist if you intend to use it as a
Launch Daemon with a dedicated b3chain user.

Auto-respawn
-----------------------------------

Auto respawning is currently only configured for Upstart and systemd.
Reasonable defaults have been chosen but YMMV.
