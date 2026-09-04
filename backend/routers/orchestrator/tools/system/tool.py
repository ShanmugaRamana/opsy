"""Read-only observations about what this machine *is*, as opposed to what it is storing, running or
connected to - those three are the disk, process and network groups.

This is the base agent's allow-list, and it exists for the same reason theirs do: the caller selects
a command id, never an argv, so these run with no approval card in front of them. Anything outside
the list is still available to the agent through request_command, where the user sees the exact
command and decides.
"""
import getpass
import logging
import os
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger("tools.system")

MAX_OUTPUT_CHARS = 3000

# Substituted at execution time. NAME is a caller-supplied package or binary name, validated first;
# USER is this process's own username, which the caller never supplies.
NAME_TOKEN = "{name}"
USER_TOKEN = "{user}"

# Reported by session_environment. An allow-list, never os.environ itself: a developer's environment
# routinely holds API keys, tokens and connection strings, and a tool group that hands those to a
# model has leaked them - to the provider, into the stored transcript, and into the next turn's
# context. These are the variables that actually answer "what session am I in".
_ENV_ALLOW_LIST = (
    "USER", "LOGNAME", "HOME", "SHELL", "PATH", "TERM", "LANG", "LC_ALL",
    "XDG_CURRENT_DESKTOP", "XDG_SESSION_TYPE", "XDG_SESSION_DESKTOP", "DESKTOP_SESSION",
    "WAYLAND_DISPLAY", "DISPLAY", "container",
)

# Tried in order; the first one installed answers a package query. Each is (binary, argv template),
# where the argv is Opsy's own - the caller only ever supplies the package name. Several of these
# binaries are refused outright on the ad-hoc command path, which is exactly the split the network
# group already draws: a mutating binary is safe here because the subcommand is fixed and not
# parsed out of anything a model wrote.
_PACKAGE_MANAGERS = (
    ("dpkg-query", ("dpkg-query", "-W", "-f=${Package} ${Version} [${Status}]\n", NAME_TOKEN)),
    ("rpm", ("rpm", "-q", "--queryformat", "%{NAME} %{VERSION}-%{RELEASE}\n", NAME_TOKEN)),
    ("pacman", ("pacman", "-Qi", NAME_TOKEN)),
    ("apk", ("apk", "info", "-e", NAME_TOKEN)),
    ("xbps-query", ("xbps-query", "-p", "pkgver", NAME_TOKEN)),
)

# A package or binary name, not an option and not a path. Checked before the name reaches an argv so
# a value like "-rf" or "--force" cannot become a flag on a command Opsy chose.
_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._+@-]{0,99}$")


@dataclass(frozen=True)
class SystemCommand:
    """One allow-listed observation. `kind` decides how it is answered: "command" runs a fixed argv,
    "file" reads a fixed file, "env" reports the allow-listed environment, and "package" picks
    whichever package manager this machine has. The caller only ever selects an id, plus a name for
    the commands that take one."""

    label: str
    description: str
    kind: str = "command"
    argv: tuple = ()
    file_path: str = ""
    name_mode: str = "none"  # none | required
    requires: str = ""  # binary that must be present
    timeout: int = 10


SYSTEM_COMMANDS: dict[str, SystemCommand] = {
    # ---- What this machine is ----
    "os_release": SystemCommand(
        "Operating system", "Distribution name, version and ID from /etc/os-release. The starting "
        "point for any question about which Linux this is.",
        kind="file", file_path="/etc/os-release",
    ),
    "distro_details": SystemCommand(
        "Distribution details", "Distributor, release and codename via lsb_release. Useful where "
        "/etc/os-release is thin.",
        argv=("lsb_release", "-a"), requires="lsb_release",
    ),
    "kernel": SystemCommand(
        "Kernel and architecture", "Kernel name, release, version, machine architecture and hostname.",
        argv=("uname", "-a"),
    ),
    "kernel_cmdline": SystemCommand(
        "Kernel command line", "The parameters this kernel was booted with, including root device "
        "and any boot-time overrides.",
        kind="file", file_path="/proc/cmdline",
    ),
    "hostname": SystemCommand(
        "Hostname", "This machine's network node name.", argv=("uname", "-n"),
    ),
    "virtualization": SystemCommand(
        "Virtualization", "Whether this is bare metal, a virtual machine or a container, and which "
        "technology.",
        argv=("systemd-detect-virt",), requires="systemd-detect-virt",
    ),
    "init_system": SystemCommand(
        "Init system", "The systemd version and build options, which identifies the init system and "
        "how the machine is managed.",
        argv=("systemctl", "--version"), requires="systemctl",
    ),
    "uptime": SystemCommand(
        "Uptime", "How long this machine has been running, and the load averages alongside it.",
        argv=("uptime",),
    ),
    # ---- Time and locale ----
    "time_settings": SystemCommand(
        "Time and timezone", "Local and universal time, the configured timezone, and whether NTP "
        "synchronisation is active.",
        argv=("timedatectl", "status"), requires="timedatectl",
    ),
    "date_time": SystemCommand(
        "Current date and time", "The current date, time and timezone offset. The fallback where "
        "timedatectl is not present.",
        argv=("date",),
    ),
    "locale": SystemCommand(
        "Locale", "Language, character encoding and regional formatting settings.",
        argv=("locale",),
    ),
    # ---- Who is using it ----
    "current_user": SystemCommand(
        "Current user", "The user Opsy is running as, with its uid, gid and group memberships.",
        argv=("id",),
    ),
    "user_account": SystemCommand(
        "User account", "This user's account entry: home directory and login shell.",
        argv=("getent", "passwd", USER_TOKEN), requires="getent",
    ),
    "logged_in_users": SystemCommand(
        "Logged-in users", "Who is currently logged in, on which terminal, and since when.",
        argv=("who",),
    ),
    "shells_available": SystemCommand(
        "Installed shells", "The login shells available on this system.",
        kind="file", file_path="/etc/shells",
    ),
    "session_environment": SystemCommand(
        "Session environment", "Desktop environment, session type, display server, shell, locale and "
        "PATH for this session. A fixed set of variables, not the whole environment.",
        kind="env",
    ),
    # ---- What is installed ----
    "which_binary": SystemCommand(
        "Locate a program", "Whether a named program is on PATH and where it lives. Use this for "
        "'is X installed'. Needs a name.",
        argv=("which", NAME_TOKEN), name_mode="required", requires="which",
    ),
    "package_info": SystemCommand(
        "Package version", "A named package's installed version, through whichever package manager "
        "this system uses (dpkg, rpm, pacman, apk). Needs a name.",
        kind="package", name_mode="required",
    ),
}


def command_label(command_id):
    entry = SYSTEM_COMMANDS.get(command_id)
    return entry.label if entry else str(command_id)


def tool_schema_properties():
    """Returns {command_id: description}, used to build each provider's tool schema."""
    return {cid: entry.description for cid, entry in SYSTEM_COMMANDS.items()}


def validate_name(raw):
    """Returns (name, None) or (None, error_message).

    The name becomes one element of an argv list Opsy assembled, so this is not about shell escaping
    - there is no shell - but about keeping a value from turning into an option on a command the user
    never approved."""
    if raw is None or str(raw).strip() == "":
        return None, "no name given"

    name = str(raw).strip()
    if not _NAME_RE.match(name):
        return None, (
            f"'{name}' is not a plain package or program name - letters, digits and . _ + - @ only, "
            "and it cannot start with a dash"
        )
    return name, None


def _read_environment():
    present = [f"{key}={os.environ[key]}" for key in _ENV_ALLOW_LIST if os.environ.get(key)]
    if not present:
        return "None of the session environment variables Opsy reads are set."
    return "\n".join(present)


def _run_package_query(name):
    for binary, argv_template in _PACKAGE_MANAGERS:
        if shutil.which(binary) is None:
            continue

        argv = [name if token == NAME_TOKEN else token for token in argv_template]
        try:
            result = subprocess.run(argv, capture_output=True, text=True, timeout=15)
        except subprocess.TimeoutExpired:
            return f"Querying {binary} for '{name}' timed out."
        except OSError as e:
            return f"Error querying {binary} for '{name}': {e}"

        stdout = result.stdout.strip()
        if result.returncode != 0 or not stdout:
            # Not an error worth hiding: "not installed" is the answer to the question that was
            # asked, and the package manager's own words say it better than a generic message.
            detail = result.stderr.strip() or stdout
            return f"{binary} reports no installed package named '{name}'." + (f" ({detail})" if detail else "")
        return stdout[:MAX_OUTPUT_CHARS]

    return (
        "No supported package manager was found on this system "
        f"({', '.join(binary for binary, _ in _PACKAGE_MANAGERS)}), so package versions cannot be "
        "looked up. A program's presence can still be checked with which_binary."
    )


def execute_system_command(command_id, name=None):
    """Runs the allow-listed observation for command_id and returns its output as text. Never raises:
    an unknown id, a bad name, a missing binary or a timeout all return a short explanatory string,
    so the caller always has something to reason about."""
    entry = SYSTEM_COMMANDS.get(command_id)
    if entry is None:
        return f"Error: unknown command '{command_id}'. Valid commands: {', '.join(SYSTEM_COMMANDS)}."

    resolved_name = None
    if entry.name_mode == "required":
        resolved_name, error = validate_name(name)
        if error:
            return f"Error: {entry.label} needs a name - {error}."

    if entry.kind == "env":
        return _read_environment()

    if entry.kind == "package":
        return _run_package_query(resolved_name)

    if entry.kind == "file":
        try:
            return Path(entry.file_path).read_text().strip()[:MAX_OUTPUT_CHARS] or f"{entry.file_path} is empty."
        except FileNotFoundError:
            return f"{entry.file_path} does not exist on this system."
        except PermissionError:
            return f"Reading {entry.file_path} requires elevated permissions."
        except OSError as e:
            return f"Error reading {entry.file_path}: {e}"

    if entry.requires and shutil.which(entry.requires) is None:
        return f"{entry.requires} is not installed on this system, so {entry.label.lower()} is unavailable."

    argv = []
    for token in entry.argv:
        if token == NAME_TOKEN:
            argv.append(resolved_name)
        elif token == USER_TOKEN:
            argv.append(getpass.getuser())
        else:
            argv.append(token)

    try:
        result = subprocess.run(argv, capture_output=True, text=True, timeout=entry.timeout)
    except subprocess.TimeoutExpired:
        return f"{entry.label} timed out after {entry.timeout}s."
    except OSError as e:
        logger.warning(f"{entry.label} ({' '.join(argv)}) failed: {e}")
        return f"Error running {entry.label}: {e}"

    stdout = result.stdout.strip()
    stderr = result.stderr.strip()

    if result.returncode != 0 and not stdout:
        # which(1) exits non-zero for a program that is not installed, and that is the answer rather
        # than a failure, so it is reported as such instead of as an error.
        if command_id == "which_binary":
            return f"'{resolved_name}' is not on PATH, so it is not installed (or not visible to this user)."
        return f"{entry.label} failed: {stderr or f'exit code {result.returncode}'}"

    if not stdout:
        return f"{entry.label} returned no output."

    return stdout[:MAX_OUTPUT_CHARS]
