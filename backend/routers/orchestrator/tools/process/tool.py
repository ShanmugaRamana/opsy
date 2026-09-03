"""Allow-listed, read-only observations about processes, load and services.

Same contract as the disk tool: the caller only ever selects an id (plus, for some, a single argument
value), never argv, never a shell string. Nothing here writes, signals or reconfigures anything -
there is no kill, no renice, no systemctl start. Quitting an app is a mutating action and belongs
behind the permission flow, not in a fixed allow-list the agent can call freely.

Three kinds of observation:

- **command** - a fixed argv, run with shell=False.
- **file** - a fixed path under /proc, read directly.
- **python** - computed in `apps.py`. `running_apps` is the important one: grouping the process table
  into recognisable applications is the difference between answering "which apps are running" and
  dumping 300 rows at someone, and it has to be deterministic rather than a hope about the model.
"""
import logging
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from . import apps

logger = logging.getLogger("tools.process")

MAX_OUTPUT_CHARS = 3000
ARG_TOKEN = "{arg}"

# name/unit values become one argv token and never touch a shell, so this validates for usability -
# and to keep an obviously wrong value from reaching a binary as a confusing syntax error.
_NAME_RE = re.compile(r"^[A-Za-z0-9._@:-]{1,128}$")


@dataclass(frozen=True)
class ProcessCommand:
    label: str
    description: str
    kind: str = "command"
    argv: tuple = ()
    file_path: str = ""
    handler: str = ""  # for kind="python"
    arg_mode: str = "none"  # none | optional | required
    arg_kind: str = "pid"  # pid | name | unit | path
    default_arg: str = ""
    requires: str = ""
    timeout: int = 15
    needs_root: bool = False
    postprocess: str = ""
    limit: int = 20


def _autostart_dir():
    return str(Path.home() / ".config" / "autostart")


PROCESS_COMMANDS: dict[str, ProcessCommand] = {
    # ---- The grouped application view ----
    "running_apps": ProcessCommand(
        "Running applications",
        "Open applications, grouped so a multi-process app counts once, with summed CPU and memory. "
        "The right answer to 'which apps are running'. States whether window data is available.",
        kind="python", handler="running_apps", timeout=30,
    ),
    "session_info": ProcessCommand(
        "Graphical session",
        "Display server (X11 or Wayland), desktop environment, and whether window information can be "
        "read at all.",
        kind="python", handler="session_info",
    ),
    # ---- Process listings ----
    "process_list": ProcessCommand(
        "Process list",
        "Every process with CPU, memory and state, busiest first. The raw table, including daemons.",
        argv=("ps", "-eo", "pid,ppid,user,pcpu,pmem,rss,etimes,stat,comm", "--sort=-pcpu"),
        postprocess="top_lines", limit=40,
    ),
    "top_cpu": ProcessCommand(
        "Top CPU consumers", "The processes using the most CPU right now, with full command lines.",
        argv=("ps", "-eo", "pid,user,pcpu,pmem,rss,etimes,args", "--sort=-pcpu"),
        postprocess="top_lines", limit=15,
    ),
    "top_memory": ProcessCommand(
        "Top memory consumers", "The processes holding the most resident memory, largest first.",
        argv=("ps", "-eo", "pid,user,pcpu,pmem,rss,etimes,args", "--sort=-rss"),
        postprocess="top_lines", limit=15,
    ),
    "process_tree": ProcessCommand(
        "Process tree", "Parent/child structure, showing which application spawned what.",
        argv=("pstree", "-p"), requires="pstree", postprocess="top_lines", limit=60,
    ),
    "process_count": ProcessCommand(
        "Process count", "How many processes exist, counted rather than listed.",
        argv=("ps", "-e", "--no-headers"), postprocess="count_lines",
    ),
    "zombies": ProcessCommand(
        "Zombie processes",
        "Defunct processes and their parents. A zombie holds a process-table slot until its parent "
        "reaps it.",
        argv=("ps", "-eo", "pid,ppid,stat,comm"), postprocess="only_zombies",
    ),
    "stuck_processes": ProcessCommand(
        "Uninterruptible processes",
        "Processes blocked in D state, which means stuck in the kernel on I/O rather than busy on CPU. "
        "These cannot be killed until the I/O completes.",
        argv=("ps", "-eo", "pid,stat,wchan:20,comm"), postprocess="only_stuck",
    ),
    "long_running": ProcessCommand(
        "Longest running processes", "What has been running longest, oldest first.",
        argv=("ps", "-eo", "pid,user,etimes,pcpu,args", "--sort=-etimes"),
        postprocess="top_lines", limit=20,
    ),
    "nice_levels": ProcessCommand(
        "Process priorities",
        "Nice and priority values. Explains why something is starved or hogging despite low load.",
        argv=("ps", "-eo", "pid,ni,pri,pcpu,comm", "--sort=ni"), postprocess="top_lines", limit=25,
    ),
    # ---- One specific process ----
    "find_process": ProcessCommand(
        "Find process by name",
        "Whether a named program is running, and as which PIDs. Start here when asked about a "
        "specific application.",
        argv=("pgrep", "-a", ARG_TOKEN), arg_mode="required", arg_kind="name", requires="pgrep",
    ),
    "process_detail": ProcessCommand(
        "Process detail", "Everything about one process: owner, CPU, memory, start time, state, command.",
        argv=("ps", "-p", ARG_TOKEN, "-o", "pid,ppid,user,pcpu,pmem,rss,vsz,etime,lstart,stat,ni,args"),
        arg_mode="required", arg_kind="pid",
    ),
    "process_status": ProcessCommand(
        "Process status (kernel)",
        "Detailed kernel-side state for one process: threads, memory breakdown, context switches.",
        kind="file", file_path=f"/proc/{ARG_TOKEN}/status", arg_mode="required", arg_kind="pid",
    ),
    "process_threads": ProcessCommand(
        "Process threads",
        "Per-thread CPU inside one process. Distinguishes one hot thread from genuine parallelism.",
        argv=("ps", "-L", "-p", ARG_TOKEN, "-o", "pid,tid,pcpu,stat,comm"),
        arg_mode="required", arg_kind="pid", postprocess="top_lines", limit=25,
    ),
    "process_children": ProcessCommand(
        "Process children", "The direct subprocesses of one process, with their resource use.",
        argv=("ps", "--ppid", ARG_TOKEN, "-o", "pid,pcpu,pmem,rss,etimes,args"),
        arg_mode="required", arg_kind="pid", postprocess="top_lines", limit=30,
    ),
    "process_open_files": ProcessCommand(
        "Process open files", "Files, sockets and devices one process has open.",
        argv=("lsof", "-p", ARG_TOKEN), arg_mode="required", arg_kind="pid", requires="lsof",
        timeout=30, postprocess="top_lines", limit=40,
    ),
    "process_memory_map": ProcessCommand(
        "Process memory map", "Where one process's memory actually went, by mapping.",
        argv=("pmap", "-x", ARG_TOKEN), arg_mode="required", arg_kind="pid", requires="pmap",
        postprocess="top_lines", limit=30,
    ),
    "process_io": ProcessCommand(
        "Process I/O", "How much one process has read and written.",
        kind="file", file_path=f"/proc/{ARG_TOKEN}/io", arg_mode="required", arg_kind="pid",
    ),
    "process_limits": ProcessCommand(
        "Process limits",
        "Resource ceilings for one process, including the open-file limit behind 'too many open files'.",
        kind="file", file_path=f"/proc/{ARG_TOKEN}/limits", arg_mode="required", arg_kind="pid",
    ),
    # ---- Windows (X11 only) ----
    "window_list": ProcessCommand(
        "Open windows", "Open windows with the PID that owns each. Only works on X11.",
        argv=("wmctrl", "-lpG"), requires="wmctrl",
    ),
    "active_window": ProcessCommand(
        "Focused window", "The window that currently has focus. Only works on X11.",
        argv=("xdotool", "getactivewindow", "getwindowname"), requires="xdotool",
    ),
    # ---- System load ----
    "load_average": ProcessCommand(
        "Load average",
        "1/5/15-minute run-queue load. Read it against the core count, not on its own.",
        kind="file", file_path="/proc/loadavg",
    ),
    "cpu_count": ProcessCommand(
        "CPU cores", "How many cores load and CPU percentages should be judged against.",
        argv=("nproc",), requires="nproc",
    ),
    "memory_usage": ProcessCommand(
        "Memory usage", "RAM and swap: used, free, available, cached.",
        argv=("free", "-h"), requires="free",
    ),
    "cpu_pressure": ProcessCommand(
        "CPU pressure", "How much time tasks spend stalled waiting for CPU.",
        kind="file", file_path="/proc/pressure/cpu",
    ),
    "memory_pressure": ProcessCommand(
        "Memory pressure",
        "How much time tasks stall on memory. The real signal for thrashing, better than free alone.",
        kind="file", file_path="/proc/pressure/memory",
    ),
    "io_pressure_procs": ProcessCommand(
        "I/O pressure", "How much time tasks stall on I/O. Pairs with stuck_processes.",
        kind="file", file_path="/proc/pressure/io",
    ),
    "uptime": ProcessCommand(
        "Uptime", "How long the machine has been running.", argv=("uptime", "-p"), requires="uptime",
    ),
    "top_snapshot": ProcessCommand(
        "Top snapshot", "One conventional top frame: load, task states, CPU and memory totals.",
        argv=("top", "-b", "-n", "1"), requires="top", timeout=30, postprocess="top_lines", limit=30,
    ),
    "cpu_sample": ProcessCommand(
        "Sampled CPU per process",
        "Per-process CPU measured over an interval, rather than the since-boot average ps reports.",
        argv=("pidstat", "1", "2"), requires="pidstat", timeout=30, postprocess="top_lines", limit=30,
    ),
    "vm_stats": ProcessCommand(
        "Virtual memory statistics",
        "Run queue length, context switches, and swap in/out activity sampled over two seconds.",
        argv=("vmstat", "1", "2"), requires="vmstat", timeout=30,
    ),
    # ---- Services ----
    "services": ProcessCommand(
        "Running services", "System services that are currently running.",
        argv=("systemctl", "list-units", "--type=service", "--state=running", "--no-pager", "--plain"),
        requires="systemctl", postprocess="top_lines", limit=40,
    ),
    "user_services": ProcessCommand(
        "User services",
        "Per-session services. Desktop applications and their helpers often live here rather than "
        "under the system manager.",
        argv=("systemctl", "--user", "list-units", "--type=service", "--state=running", "--no-pager", "--plain"),
        requires="systemctl", postprocess="top_lines", limit=40,
    ),
    "failed_services": ProcessCommand(
        "Failed services", "Services that failed to start or crashed.",
        argv=("systemctl", "list-units", "--state=failed", "--no-pager", "--plain"), requires="systemctl",
    ),
    "service_status": ProcessCommand(
        "Service status", "One service in detail, including recent log lines and its main PID.",
        argv=("systemctl", "status", ARG_TOKEN, "--no-pager"), arg_mode="required", arg_kind="unit",
        requires="systemctl", postprocess="top_lines", limit=30,
    ),
    "enabled_at_boot": ProcessCommand(
        "Enabled at boot", "Services configured to start themselves at boot.",
        argv=("systemctl", "list-unit-files", "--state=enabled", "--no-pager", "--plain"),
        requires="systemctl", postprocess="top_lines", limit=40,
    ),
    "timers": ProcessCommand(
        "Scheduled timers", "Work scheduled to wake up periodically, and when it last ran.",
        argv=("systemctl", "list-timers", "--no-pager", "--plain"), requires="systemctl",
        postprocess="top_lines", limit=25,
    ),
    "autostart_entries": ProcessCommand(
        "Login autostart", "Desktop applications configured to launch at login.",
        argv=("ls", "-1", ARG_TOKEN), arg_mode="optional", arg_kind="path", default_arg=_autostart_dir(),
    ),
    # ---- Sandboxed and containerised apps ----
    "flatpak_running": ProcessCommand(
        "Running Flatpak apps",
        "Flatpak applications currently running. Their processes are hard to recognise in ps, so "
        "check here when an app seems missing.",
        argv=("flatpak", "ps"), requires="flatpak",
    ),
    "snap_services": ProcessCommand(
        "Snap services", "Running snap services.", argv=("snap", "services"), requires="snap",
    ),
    "containers": ProcessCommand(
        "Running containers", "Docker containers currently running.",
        argv=("docker", "ps"), requires="docker", timeout=30,
    ),
    "podman_containers": ProcessCommand(
        "Running Podman containers", "Podman containers currently running.",
        argv=("podman", "ps"), requires="podman", timeout=30,
    ),
}

_PYTHON_HANDLERS = {"running_apps": apps.running_apps, "session_info": apps.session_info}


def command_label(command_id):
    entry = PROCESS_COMMANDS.get(command_id)
    return entry.label if entry else str(command_id)


def tool_schema_properties():
    """Returns {command_id: description}, used to build each provider's tool schema."""
    return {cid: entry.description for cid, entry in PROCESS_COMMANDS.items()}


# ---- Argument validation ----

def validate_arg(raw, arg_kind):
    """Returns (value, None) or (None, error_message).

    The value becomes one element of an argv list and never touches a shell, so this validates for
    usability rather than injection - but a PID that does not exist is worth catching here, so the
    agent gets a clear answer instead of a bare 'no such process' from ps."""
    if raw is None or str(raw).strip() == "":
        return None, "no value given"

    text = str(raw).strip()
    if "\x00" in text:
        return None, "the value contains a null byte"

    if arg_kind == "pid":
        if not text.isdigit():
            return None, f"'{text}' is not a process id. Pass the numeric PID."
        if not Path(f"/proc/{text}").exists():
            return None, (
                f"no process with PID {text} is running. It may have exited since it was listed - "
                "re-check the process list."
            )
        return text, None

    if arg_kind in ("name", "unit"):
        if not _NAME_RE.match(text):
            return None, f"'{text}' is not a valid {arg_kind}."
        return text, None

    # path
    candidate = Path(text).expanduser()
    if not candidate.is_absolute():
        return None, f"path must be absolute, got '{text}'"
    try:
        resolved = candidate.resolve()
    except OSError as e:
        return None, f"could not resolve path '{text}': {e}"
    if not resolved.exists():
        return None, f"path does not exist: {resolved}"
    return str(resolved), None


# ---- Post-processing ----
#
# ps output carries a header row that the model needs to read the columns, so every post-processor
# preserves it. There is no shell, so what a pipeline would do with head/grep happens here instead.

def _split_header(output):
    lines = output.splitlines()
    return (lines[0], lines[1:]) if lines else ("", [])


def _postprocess_top_lines(output, entry):
    header, rows = _split_header(output)
    if len(rows) <= entry.limit:
        return output
    kept = "\n".join(rows[: entry.limit])
    return f"{header}\n{kept}\n\n[{len(rows) - entry.limit} further rows not shown]"


def _postprocess_count_lines(output, entry):
    count = sum(1 for line in output.splitlines() if line.strip())
    return f"{count} processes."


def _filter_by_stat(output, column, predicate, empty_message):
    header, rows = _split_header(output)
    matched = []
    for row in rows:
        parts = row.split()
        if len(parts) > column and predicate(parts[column]):
            matched.append(row)
    if not matched:
        return empty_message
    return "\n".join([header] + matched)


def _postprocess_only_zombies(output, entry):
    return _filter_by_stat(
        output, 2, lambda stat: stat.startswith("Z"),
        "No zombie processes. Every process that has exited has been reaped by its parent.",
    )


def _postprocess_only_stuck(output, entry):
    return _filter_by_stat(
        output, 1, lambda stat: stat.startswith("D"),
        "No processes are blocked in uninterruptible I/O.",
    )


_POSTPROCESSORS = {
    "top_lines": _postprocess_top_lines,
    "count_lines": _postprocess_count_lines,
    "only_zombies": _postprocess_only_zombies,
    "only_stuck": _postprocess_only_stuck,
}

_PERMISSION_MARKERS = ("permission denied", "must be root", "operation not permitted", "are you root")


def execute_process_command(command_id, arg=None):
    """Runs the allow-listed observation for command_id and returns its output as text. Never raises:
    an unknown id, a bad argument, a missing binary, a permission problem or a timeout all return a
    short explanatory string, so the caller always has something to reason about."""
    entry = PROCESS_COMMANDS.get(command_id)
    if entry is None:
        return f"Error: unknown command '{command_id}'. Valid commands: {', '.join(PROCESS_COMMANDS)}."

    resolved_arg = None
    if entry.arg_mode != "none":
        if arg:
            resolved_arg, error = validate_arg(arg, entry.arg_kind)
            if error:
                return f"Error: {error}"
        elif entry.arg_mode == "required":
            hint = {
                "pid": "a process id. Run find_process or top_cpu first to get one",
                "name": "a program name, such as firefox",
                "unit": "a service unit name, such as bluetooth.service",
                "path": "an absolute directory path",
            }[entry.arg_kind]
            return f"{entry.label} needs {hint}, then call this again with that value as the argument."
        else:
            resolved_arg = entry.default_arg or None

    if entry.kind == "python":
        try:
            return _PYTHON_HANDLERS[entry.handler]()
        except Exception as e:  # a computed view must not be able to take the turn down
            logger.exception(f"{entry.label} failed")
            return f"Error computing {entry.label.lower()}: {e}"

    if entry.kind == "file":
        path = entry.file_path.replace(ARG_TOKEN, resolved_arg or "")
        try:
            return Path(path).read_text().strip()[:MAX_OUTPUT_CHARS] or f"{path} is empty."
        except FileNotFoundError:
            return f"{path} does not exist on this system."
        except PermissionError:
            return f"Reading {path} requires elevated permissions."
        except OSError as e:
            return f"Error reading {path}: {e}"

    if entry.requires and shutil.which(entry.requires) is None:
        return f"{entry.requires} is not installed on this system, so {entry.label.lower()} is unavailable."

    argv = []
    for token in entry.argv:
        if token == ARG_TOKEN:
            if resolved_arg:
                argv.append(resolved_arg)
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

    if result.returncode != 0:
        combined = f"{stdout}\n{stderr}".strip().lower()
        if entry.needs_root and any(marker in combined for marker in _PERMISSION_MARKERS):
            return (
                f"{entry.label} requires elevated permissions, so it could not be read. "
                "Running Opsy with sudo would allow this check."
            )
        # pgrep exits 1 when nothing matched, which is an answer rather than a failure.
        if not stdout and command_id == "find_process":
            return f"No running process matches '{resolved_arg}'."
        if not stdout:
            return f"{entry.label} failed: {stderr or f'exit code {result.returncode}'}"

    if entry.postprocess and stdout:
        stdout = _POSTPROCESSORS[entry.postprocess](stdout, entry)

    if not stdout:
        return f"{entry.label} returned no output."

    return stdout[:MAX_OUTPUT_CHARS]
