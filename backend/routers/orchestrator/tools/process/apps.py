"""Turning the process table into the applications a person would recognise.

"Which apps are running?" is not a request for the process table. A raw `ps` answer contains kernel
threads, other users' daemons, session plumbing, and twenty Chrome subprocesses - it answers the
letter of the question and misses all of its intent. The grouping, filtering and honesty about what
can and cannot be seen therefore happen here, deterministically, rather than as an instruction the
model may or may not follow.

Two things this module refuses to fake:

- **Foreground vs background.** X11 lets any client enumerate windows, so on X11 an app's windows can
  be found and named. Wayland compositors deliberately do not, so on Wayland that information does not
  exist for us and every app is reported with an unknown state. The output says which case it is in a
  CONFIDENCE line, and the agent's prompt branches on it. A silent degradation - claiming an app is
  "background" because no window was found on a system that never reports windows - would be a
  fabrication, and the trace panel's whole promise is that Opsy says what it actually checked.
- **Memory precision.** A group's memory is summed RSS across its processes, and RSS counts shared
  pages once per process, so a multi-process app's total is an upper bound. That caveat ships in the
  output rather than living only in a comment here.
"""
import logging
import os
import shutil
import subprocess

from dataclasses import dataclass, field

logger = logging.getLogger("tools.process")

PS_TIMEOUT = 15
WM_TIMEOUT = 5

# `ps` truncates comm to 15 characters (the kernel's TASK_COMM_LEN is 16), which is why several
# entries below are matched by prefix and why some denylist entries look cut off. That truncation is
# not a typo to be fixed - "chromium-browse" and "gnome-keyring-d" are what the field actually holds.
PS_FORMAT = "pid,ppid,uid,pcpu,pmem,rss,etimes,stat,comm,args"
_PS_FIELDS = 10


@dataclass(frozen=True)
class Process:
    pid: int
    ppid: int
    uid: int
    cpu: float
    mem: float
    rss_kb: int
    etimes: int
    stat: str
    comm: str
    args: str


@dataclass
class AppGroup:
    name: str
    cpu: float = 0.0
    rss_kb: int = 0
    count: int = 0
    oldest_etimes: int = 0
    renderers: int = 0
    pids: list = field(default_factory=list)
    windows: list = field(default_factory=list)

    @property
    def state(self):
        """Only ever "foreground" on evidence. The caller replaces this with "unknown" when window
        data was unavailable, since "background" would then be a claim about something never seen."""
        return "foreground" if self.windows else "background"


# ---- Session detection ----

def detect_session():
    """What kind of graphical session this is, and whether window data can be read from it.

    Returns a dict with session_type, desktop, window_source and confidence. Confidence is "full"
    only when windows can genuinely be enumerated - anything else is "degraded" with a reason, so the
    limitation is stated rather than inferred."""
    session_type = (os.environ.get("XDG_SESSION_TYPE") or "").strip().lower()
    desktop = (os.environ.get("XDG_CURRENT_DESKTOP") or os.environ.get("DESKTOP_SESSION") or "").strip()

    # XDG_SESSION_TYPE is not always set (some display managers, most containers), so fall back to
    # whichever display socket is actually advertised.
    if not session_type:
        if os.environ.get("WAYLAND_DISPLAY"):
            session_type = "wayland"
        elif os.environ.get("DISPLAY"):
            session_type = "x11"
        else:
            session_type = "unknown"

    if session_type == "wayland":
        return {
            "session_type": "wayland",
            "desktop": desktop,
            "window_source": None,
            "confidence": "degraded",
            "reason": (
                "Wayland compositors do not expose the window list to external tools, so which "
                "applications have a visible window cannot be determined."
            ),
        }

    if session_type != "x11":
        return {
            "session_type": session_type,
            "desktop": desktop,
            "window_source": None,
            "confidence": "degraded",
            "reason": (
                "This is not a graphical session, so there are no windows to enumerate. Only "
                "processes can be seen."
            ),
        }

    if shutil.which("wmctrl") is None:
        return {
            "session_type": "x11",
            "desktop": desktop,
            "window_source": None,
            "confidence": "degraded",
            "reason": (
                "wmctrl is not installed, so the window list cannot be read even though this X11 "
                "session would allow it. Installing wmctrl would enable it."
            ),
        }

    return {
        "session_type": "x11",
        "desktop": desktop,
        "window_source": "wmctrl",
        "confidence": "full",
        "reason": "",
    }


def _read_windows():
    """PID -> window titles, from `wmctrl -lpG`.

    Returns (mapping, error). An error here downgrades confidence rather than raising: a window
    manager that refuses the request is a fact about the session, not a crash."""
    try:
        result = subprocess.run(
            ["wmctrl", "-lpG"], capture_output=True, text=True, timeout=WM_TIMEOUT
        )
    except (OSError, subprocess.TimeoutExpired) as e:
        return {}, f"the window list could not be read ({e})"

    if result.returncode != 0:
        detail = (result.stderr or "").strip() or f"exit code {result.returncode}"
        return {}, f"the window list could not be read ({detail})"

    windows = {}
    for line in result.stdout.splitlines():
        # id desktop pid x y width height host title
        parts = line.split(None, 8)
        if len(parts) < 9:
            continue
        try:
            pid = int(parts[2])
        except ValueError:
            continue
        title = parts[8].strip()
        if pid and title:
            windows.setdefault(pid, []).append(title)

    return windows, None


# ---- Reading the process table ----

def parse_ps_output(text):
    """Parses `ps -eo PS_FORMAT --no-headers` output. Split out from the subprocess call so the
    parsing and grouping can be exercised against captured output without a live machine."""
    processes = []
    for line in text.splitlines():
        # args is last and contains spaces, so everything before it splits on a fixed field count.
        parts = line.split(None, _PS_FIELDS - 1)
        if len(parts) < _PS_FIELDS:
            continue
        try:
            processes.append(
                Process(
                    pid=int(parts[0]),
                    ppid=int(parts[1]),
                    uid=int(parts[2]),
                    cpu=float(parts[3]),
                    mem=float(parts[4]),
                    rss_kb=int(parts[5]),
                    etimes=int(parts[6]),
                    stat=parts[7],
                    comm=parts[8],
                    args=parts[9],
                )
            )
        except ValueError:
            continue
    return processes


def read_processes():
    """The full process table. Returns (processes, error); never raises."""
    try:
        result = subprocess.run(
            ["ps", "-eo", PS_FORMAT, "--no-headers"],
            capture_output=True,
            text=True,
            timeout=PS_TIMEOUT,
        )
    except FileNotFoundError:
        return [], "ps is not available on this system, so the process table cannot be read."
    except subprocess.TimeoutExpired:
        return [], f"Reading the process table timed out after {PS_TIMEOUT}s."
    except OSError as e:
        return [], f"Error reading the process table: {e}"

    if result.returncode != 0 and not result.stdout.strip():
        return [], f"ps failed: {(result.stderr or '').strip() or f'exit code {result.returncode}'}"

    processes = parse_ps_output(result.stdout)

    if not processes:
        return [], "The process table came back empty, which should not happen."

    return processes, None


# ---- Filtering ----

# User-owned processes that are session plumbing rather than applications. A person asking what they
# have open does not mean their portal daemon.
_INFRA_COMMS = {
    "systemd", "sd-pam", "dbus-daemon", "dbus-broker", "dbus-broker-lau",
    "pipewire", "pipewire-pulse", "wireplumber", "pulseaudio", "pipewire-media-",
    "gnome-keyring-d", "ssh-agent", "gpg-agent", "gpgconf", "dirmngr", "keyboxd",
    "gnome-shell", "gnome-session-b", "gnome-session-c", "plasmashell", "plasma_session",
    "kwin_x11", "kwin_wayland", "mutter", "mutter-x11-fram", "Xorg", "Xwayland", "xfwm4",
    "kded5", "kded6", "krunner", "ksmserver", "kglobalaccel5", "kwalletd5", "kwalletd6",
    "obexd", "geoclue", "colord", "rtkit-daemon", "upowerd", "accounts-daemon",
    "polkit-gnome-au", "polkitd", "gcr-ssh-agent", "gcr-prompter",
    "bash", "sh", "zsh", "fish", "dash", "ksh", "ps", "sleep", "tmux", "screen",
}

# Prefix matches, for families whose members are numerous or truncated by ps.
_INFRA_PREFIXES = (
    "systemd-", "gsd-", "gvfs", "xdg-", "ibus-", "at-spi", "fcitx",
    "tracker-", "localsearch", "tinysparql", "goa-", "evolution-", "kaccess",
    "gnome-shell-cal", "gjs",
)


def _is_kernel_thread(process):
    """Kernel threads are children of kthreadd (pid 2) and show their name in brackets."""
    if process.pid == 2 or process.ppid == 2:
        return True
    return process.args.startswith("[") and process.args.endswith("]")


def _is_infrastructure(process):
    comm = process.comm
    if comm in _INFRA_COMMS:
        return True
    return any(comm.startswith(prefix) for prefix in _INFRA_PREFIXES)


def _own_tree(processes):
    """Every pid belonging to Opsy itself - its ancestors, itself, and its children.

    Opsy asking a question about the machine should not report itself back as one of the user's open
    applications, and the `ps` it just spawned is not an app either."""
    self_pid = os.getpid()
    by_pid = {p.pid: p for p in processes}
    children = {}
    for process in processes:
        children.setdefault(process.ppid, []).append(process.pid)

    own = {self_pid}

    # Ancestors: walk up to init, so the uvicorn/python parent is excluded too.
    current = by_pid.get(self_pid)
    seen = set()
    while current is not None and current.ppid > 1 and current.ppid not in seen:
        seen.add(current.ppid)
        own.add(current.ppid)
        current = by_pid.get(current.ppid)

    # Descendants: the subprocesses this observation itself created.
    stack = [self_pid]
    while stack:
        for child in children.get(stack.pop(), []):
            if child not in own:
                own.add(child)
                stack.append(child)

    return own


# ---- Grouping ----

@dataclass(frozen=True)
class GroupRule:
    """One canonical application and the ways its processes can be recognised.

    Rules are ordered and the first match wins, so a more specific browser is listed before a more
    generic one that shares its engine."""

    name: str
    comms: tuple = ()
    comm_prefixes: tuple = ()
    args_contains: tuple = ()

    def matches(self, process):
        if process.comm in self.comms:
            return True
        if any(process.comm.startswith(prefix) for prefix in self.comm_prefixes):
            return True
        if self.args_contains:
            args = process.args.lower()
            return any(needle in args for needle in self.args_contains)
        return False


# Chrome alone can be 20+ rows in ps - renderer, GPU, utility, zygote and crashpad processes - and
# collapsing those into one entry is the single biggest difference between running a command and
# answering the question.
_GROUP_RULES = (
    GroupRule("Google Chrome", comms=("chrome", "chrome_crashpad"),
              comm_prefixes=("chrome_crashpad",), args_contains=("/opt/google/chrome", "google-chrome")),
    GroupRule("Microsoft Edge", comms=("msedge",), args_contains=("microsoft-edge",)),
    GroupRule("Brave", comms=("brave",), args_contains=("brave-browser",)),
    GroupRule("Vivaldi", comms=("vivaldi-bin",), args_contains=("vivaldi",)),
    GroupRule("Opera", comms=("opera",), args_contains=("/usr/lib/x86_64-linux-gnu/opera",)),
    GroupRule("Chromium", comms=("chromium", "chromium-browse"), args_contains=("/chromium",)),
    GroupRule("Firefox", comms=("firefox", "firefox-bin", "firefox-esr"),
              args_contains=("/firefox", "firefox-esr")),
    GroupRule("Thunderbird", comms=("thunderbird",), args_contains=("/thunderbird",)),
    GroupRule("Visual Studio Code", comms=("code", "code-oss", "codium"),
              args_contains=("/usr/share/code", "vscode", "code-oss")),
    GroupRule("Slack", comms=("slack",), args_contains=("/slack",)),
    GroupRule("Discord", comms=("Discord", "discord"), args_contains=("/discord",)),
    GroupRule("Spotify", comms=("spotify",), args_contains=("/spotify",)),
    GroupRule("Signal", comms=("signal-desktop",), args_contains=("signal-desktop",)),
    GroupRule("Telegram", comms=("telegram-desktop", "Telegram"), args_contains=("/telegram",)),
    GroupRule("Obsidian", comms=("obsidian",), args_contains=("/obsidian",)),
    GroupRule("Zoom", comms=("zoom",), args_contains=("/zoom",)),
    GroupRule("Microsoft Teams", comms=("teams",), args_contains=("/teams",)),
    GroupRule("Steam", comms=("steam", "steamwebhelper"), args_contains=("/steam",)),
    GroupRule("Docker Desktop", comms=("docker-desktop",), args_contains=("docker-desktop",)),
    GroupRule("LibreOffice", comms=("soffice.bin", "oosplash"), args_contains=("libreoffice",)),
    GroupRule("VLC", comms=("vlc",), args_contains=("/vlc",)),
    GroupRule("GIMP", comms=("gimp",), args_contains=("/gimp",)),
    GroupRule("Blender", comms=("blender",), args_contains=("/blender",)),
    GroupRule("Terminal", comms=("gnome-terminal-", "konsole", "alacritty", "kitty", "xterm",
                                 "terminator", "tilix", "wezterm-gui", "foot")),
    GroupRule("Files", comms=("nautilus", "dolphin", "thunar", "nemo")),
    # JetBrains IDEs run as a JVM, so the binary name says nothing - the main class in args does.
    GroupRule("IntelliJ IDEA", args_contains=("idea.platform", "/idea",)),
    GroupRule("PyCharm", args_contains=("/pycharm",)),
    GroupRule("WebStorm", args_contains=("/webstorm",)),
    GroupRule("Android Studio", args_contains=("android-studio",)),
)


def _pretty_name(comm):
    """A readable name for an application with no explicit rule."""
    base = comm.rsplit("/", 1)[-1]
    cleaned = base.replace("-", " ").replace("_", " ").strip()
    return cleaned[:1].upper() + cleaned[1:] if cleaned else base


def group_processes(processes):
    """Collapses a filtered process list into applications, summing their resources."""
    groups = {}

    for process in processes:
        name = None
        for rule in _GROUP_RULES:
            if rule.matches(process):
                name = rule.name
                break
        if name is None:
            name = _pretty_name(process.comm)

        group = groups.get(name)
        if group is None:
            group = groups[name] = AppGroup(name=name)

        group.cpu += process.cpu
        group.rss_kb += process.rss_kb
        group.count += 1
        group.pids.append(process.pid)
        # The app has been running since its longest-lived process started.
        group.oldest_etimes = max(group.oldest_etimes, process.etimes)
        if "--type=renderer" in process.args:
            group.renderers += 1

    return groups


# ---- Formatting ----

def format_uptime(seconds):
    if seconds < 60:
        return f"{seconds}s"
    if seconds < 3600:
        return f"{seconds // 60}m"
    if seconds < 86400:
        hours, rest = divmod(seconds, 3600)
        return f"{hours}h {rest // 60}m"
    days, rest = divmod(seconds, 86400)
    return f"{days}d {rest // 3600}h"


def format_memory(rss_kb):
    if rss_kb >= 1024 * 1024:
        return f"{rss_kb / (1024 * 1024):.1f} GB"
    if rss_kb >= 1024:
        return f"{rss_kb / 1024:.0f} MB"
    return f"{rss_kb} KB"


def _table(rows, headers):
    """Fixed-width columns, so the model reads a table rather than guessing at delimiters."""
    widths = [len(h) for h in headers]
    for row in rows:
        for index, cell in enumerate(row):
            widths[index] = max(widths[index], len(cell))

    lines = ["  ".join(h.ljust(widths[i]) for i, h in enumerate(headers)).rstrip()]
    for row in rows:
        lines.append("  ".join(cell.ljust(widths[i]) for i, cell in enumerate(row)).rstrip())
    return "\n".join(lines)


def _session_block(session, window_error=None):
    desktop = f", desktop={session['desktop']}" if session["desktop"] else ""
    lines = [f"DISPLAY SERVER: {session['session_type']}{desktop}"]

    if session["confidence"] == "full":
        lines.append(f"WINDOW DATA: available via {session['window_source']}")
        lines.append("CONFIDENCE: full - applications and their windows can both be seen.")
    else:
        reason = window_error or session["reason"]
        lines.append(f"WINDOW DATA: unavailable. {reason}")
        lines.append(
            "CONFIDENCE: degraded - applications are grouped from the process table only. Do not "
            "describe any application as foreground, focused or background."
        )
    return "\n".join(lines)


def running_apps():
    """The grouped application view. Returns text for the model, never raises."""
    processes, error = read_processes()
    if error:
        return error

    session = detect_session()
    windows = {}
    window_error = None
    if session["confidence"] == "full":
        windows, window_error = _read_windows()
        if window_error:
            session = {**session, "confidence": "degraded", "window_source": None}

    own = _own_tree(processes)
    uid = os.getuid()

    kernel = daemons = infra = 0
    mine = []
    for process in processes:
        if process.pid in own:
            continue
        if _is_kernel_thread(process):
            kernel += 1
        elif process.uid != uid:
            daemons += 1
        elif _is_infrastructure(process):
            infra += 1
        else:
            mine.append(process)

    hidden = kernel + daemons + infra
    if not mine:
        return (
            f"{_session_block(session, window_error)}\n\n"
            "APPLICATIONS: none. No user-facing application processes are running - only kernel "
            f"threads, system daemons and session services ({hidden} processes)."
        )

    groups = group_processes(mine)

    known_windows = session["confidence"] == "full"
    if known_windows:
        for group in groups.values():
            for pid in group.pids:
                group.windows.extend(windows.get(pid, []))

    ordered = sorted(groups.values(), key=lambda g: (-g.cpu, -g.rss_kb))

    rows = []
    for group in ordered:
        state = group.state if known_windows else "unknown"
        detail = ""
        if group.renderers:
            plural = "" if group.renderers == 1 else "es"
            detail = f"{group.renderers} renderer process{plural}"
        if known_windows and group.windows:
            titles = "; ".join(group.windows[:3])
            if len(group.windows) > 3:
                titles += f"; +{len(group.windows) - 3} more"
            detail = f"{detail}; {titles}" if detail else titles

        rows.append([
            group.name,
            f"{group.cpu:.1f}",
            format_memory(group.rss_kb),
            str(group.count),
            format_uptime(group.oldest_etimes),
            state,
            detail or "-",
        ])

    headers = ["NAME", "CPU%", "MEMORY", "PROCS", "RUNNING FOR", "STATE", "DETAIL"]
    windowed = sum(1 for g in ordered if g.windows) if known_windows else 0

    parts = [
        _session_block(session, window_error),
        "",
        f"APPLICATIONS ({len(ordered)} grouped from {len(mine)} user processes"
        + (f", {windowed} with visible windows)" if known_windows else ")"),
        _table(rows, headers),
        "",
        f"HIDDEN: {hidden} processes not shown ({kernel} kernel threads, {daemons} other users' "
        f"daemons, {infra} session services). Use process_list if the raw table is genuinely needed.",
        "NOTE: memory is summed RSS across each application's processes. RSS counts shared pages once "
        "per process, so a multi-process application's total is an upper bound, not an exact figure.",
    ]
    return "\n".join(parts)


def session_info():
    """Just the display-server picture, for when that is the whole question."""
    session = detect_session()
    windows = {}
    window_error = None
    if session["confidence"] == "full":
        windows, window_error = _read_windows()
        if window_error:
            session = {**session, "confidence": "degraded", "window_source": None}

    lines = [_session_block(session, window_error)]
    if session["confidence"] == "full":
        lines.append(f"OPEN WINDOWS: {sum(len(t) for t in windows.values())} across {len(windows)} processes")
    return "\n".join(lines)
