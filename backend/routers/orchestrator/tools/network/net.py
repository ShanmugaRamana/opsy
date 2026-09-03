"""Turning raw network state into the answers people actually ask for.

"Is my internet working?" is not a request for `ifconfig` output, and "what is using my network?" is
not a request for two hundred socket rows. Both are questions a command can only answer sideways, so
the layered verdict and the socket grouping happen here, deterministically, rather than as an
instruction the model may or may not follow. This is the network counterpart to `process/apps.py`.

Three things this module refuses to fake:

- **Where connectivity broke.** `connectivity_check` walks five rungs - link, address, gateway, DNS,
  internet - and reports which one failed. Collapsing them into one "are you online" boolean throws
  away the only distinction that matters: DNS failing while the internet is reachable is a resolver
  problem, and both failing is an upstream problem, and they have nothing to do with each other.
- **Who owns a socket.** `ss -p` only names the owning process for sockets the caller owns, unless it
  is running as root. So sockets that could not be attributed are reported as unattributed and
  counted, never guessed at, and the output carries a CONFIDENCE line the agent's prompt branches on.
  This is the same honesty problem as Wayland and windows, handled the same way.
- **What a filtered probe proves.** ICMP is dropped by plenty of networks, so a failed ping is not
  evidence of a failed connection. The internet rung is decided by a completed TCP handshake, with
  ping kept only as a secondary signal that is reported as such.

Reaching outward is bounded deliberately. `connectivity_check` opens a TCP connection to a fixed
well-known resolver address on port 443 and sends no payload; `captive_portal_check`, which is the
only thing here that makes an HTTP request, is a separate command the agent has to choose rather than
a rung that fires on every question. Nothing here ever probes a host supplied by the model.
"""
import logging
import os
import re
import socket
import struct
import subprocess
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field

logger = logging.getLogger("tools.network")

CMD_TIMEOUT = 10
PROBE_TIMEOUT = 2.0
PING_TIMEOUT = 8
DNS_TIMEOUT = 6

SYS_NET = "/sys/class/net"

# Fixed, well-known resolvers. These are the only destinations this module will ever open a socket
# to, and they are never taken from the model or the user's message.
PROBE_TARGETS = (("1.1.1.1", 443), ("9.9.9.9", 443))
PROBE_PING_TARGET = "1.1.1.1"
# Resolved through the system resolver to test name resolution the way applications experience it.
PROBE_NAME = "one.one.one.one"
PORTAL_URL = "http://connectivity-check.gstatic.com/generate_204"

# A busy machine can hold thousands of sockets; these bound the output without hiding the totals,
# which are always reported as counts even when the rows are truncated.
MAX_APP_ROWS = 20
MAX_PEER_ROWS = 15


# ---- Small shared helpers ----

def _run(argv, timeout=CMD_TIMEOUT):
    """Returns (stdout, error). Never raises - a missing binary is a fact about the machine."""
    try:
        result = subprocess.run(argv, capture_output=True, text=True, timeout=timeout)
    except FileNotFoundError:
        return "", f"{argv[0]} is not installed on this system"
    except subprocess.TimeoutExpired:
        return "", f"{argv[0]} timed out after {timeout}s"
    except OSError as e:
        return "", f"error running {argv[0]}: {e}"

    stdout = (result.stdout or "").strip()
    if result.returncode != 0 and not stdout:
        return "", (result.stderr or "").strip() or f"{argv[0]} exited with code {result.returncode}"
    return stdout, None


def _read(path):
    """Returns (text, error) for a /proc or /sys file. Reading `carrier` on a down interface raises
    EINVAL rather than returning anything, which is why every read here is guarded."""
    try:
        with open(path) as handle:
            return handle.read().strip(), None
    except FileNotFoundError:
        return "", f"{path} does not exist on this system"
    except PermissionError:
        return "", f"reading {path} requires elevated permissions"
    except OSError as e:
        return "", f"error reading {path}: {e}"


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


def format_rate(bytes_per_second):
    if bytes_per_second >= 1024 * 1024:
        return f"{bytes_per_second / (1024 * 1024):.2f} MB/s"
    if bytes_per_second >= 1024:
        return f"{bytes_per_second / 1024:.1f} KB/s"
    return f"{bytes_per_second:.0f} B/s"


def format_bytes(count):
    for unit, size in (("GB", 1024 ** 3), ("MB", 1024 ** 2), ("KB", 1024)):
        if count >= size:
            return f"{count / size:.1f} {unit}"
    return f"{count} B"


# ---- Interfaces, straight from /sys ----

@dataclass(frozen=True)
class Interface:
    name: str
    kind: str
    operstate: str
    carrier: str  # up | down | unknown
    mac: str
    mtu: str


def _interface_kind(name):
    """What an interface actually is. Read from /sys rather than guessed from the name, except for
    the container and virtual-bridge families, which are only recognisable by their naming."""
    if name == "lo":
        return "loopback"
    if os.path.exists(f"{SYS_NET}/{name}/wireless") or os.path.exists(f"{SYS_NET}/{name}/phy80211"):
        return "wifi"
    if os.path.exists(f"{SYS_NET}/{name}/tun_flags") or name.startswith(("tun", "tap", "wg")):
        return "tunnel"
    if os.path.exists(f"{SYS_NET}/{name}/bridge"):
        return "bridge"
    if os.path.exists(f"{SYS_NET}/{name}/bonding"):
        return "bond"
    if name.startswith(("docker", "veth", "br-", "virbr", "vmnet", "cni", "flannel")):
        return "virtual"
    if os.path.exists(f"{SYS_NET}/{name}/device"):
        return "ethernet"
    return "unknown"


def list_interfaces():
    """Every interface with its link state. Pure file reads - works with no networking tools at all."""
    try:
        names = sorted(os.listdir(SYS_NET))
    except OSError as e:
        logger.warning(f"could not list {SYS_NET}: {e}")
        return []

    interfaces = []
    for name in names:
        operstate, _ = _read(f"{SYS_NET}/{name}/operstate")
        # `carrier` is only readable while the interface is administratively up; on a down interface
        # the read fails, which is itself the answer rather than an error worth reporting.
        raw_carrier, carrier_error = _read(f"{SYS_NET}/{name}/carrier")
        carrier = "unknown" if carrier_error else ("up" if raw_carrier == "1" else "down")
        mac, _ = _read(f"{SYS_NET}/{name}/address")
        mtu, _ = _read(f"{SYS_NET}/{name}/mtu")

        interfaces.append(
            Interface(
                name=name,
                kind=_interface_kind(name),
                operstate=operstate or "unknown",
                carrier=carrier,
                mac=mac or "",
                mtu=mtu or "",
            )
        )
    return interfaces


def interface_exists(name):
    return bool(name) and os.path.isdir(f"{SYS_NET}/{name}")


def interface_names():
    try:
        return sorted(os.listdir(SYS_NET))
    except OSError:
        return []


# ---- Routing, straight from /proc ----

def default_gateway():
    """(gateway_ip, interface) from /proc/net/route, or (None, None).

    Parsed from /proc rather than shelling out to `ip route`, so the most load-bearing fact in the
    whole ladder does not depend on iproute2 being installed."""
    text, error = _read("/proc/net/route")
    if error:
        return None, None

    for line in text.splitlines()[1:]:
        parts = line.split()
        if len(parts) < 4:
            continue
        iface, destination, gateway, flags = parts[0], parts[1], parts[2], parts[3]
        try:
            # A default route is destination 0.0.0.0 with RTF_GATEWAY (0x2) set.
            if destination != "00000000" or not int(flags, 16) & 0x2:
                continue
            # The field is a little-endian hex address, not a readable one.
            return socket.inet_ntoa(struct.pack("<L", int(gateway, 16))), iface
        except (ValueError, OSError, struct.error):
            continue
    return None, None


def local_address_for(target):
    """The source address the kernel would use to reach `target`, or None.

    A UDP `connect` sends no packets - it only asks the routing table which local address applies - so
    this reads the effective address without iproute2 and without touching the network."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.settimeout(PROBE_TIMEOUT)
        sock.connect((target, 9))
        return sock.getsockname()[0]
    except OSError:
        return None
    finally:
        sock.close()


# ---- Resolvers ----

def _resolvers_from_resolv_conf():
    text, error = _read("/etc/resolv.conf")
    if error:
        return []
    return [
        line.split()[1]
        for line in text.splitlines()
        if line.strip().startswith("nameserver") and len(line.split()) > 1
    ]


def _upstream_resolvers():
    """The resolvers behind a systemd-resolved stub, from `resolvectl status`.

    /etc/resolv.conf on a systemd-resolved system says 127.0.0.53, which is a local stub. Pinging it
    proves nothing, so the real upstream servers are read separately where they can be."""
    text, error = _run(["resolvectl", "status"])
    if error:
        return []

    servers = []
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith(("DNS Servers:", "Current DNS Server:")):
            servers.extend(stripped.split(":", 1)[1].split())

    # Preserve order while removing the duplicates that come from a server appearing both as the
    # current one and in the full list.
    return list(dict.fromkeys(server for server in servers if server))


def resolvers():
    """(configured, upstream) - what resolv.conf says, and what is really behind it if that is a
    local stub."""
    configured = _resolvers_from_resolv_conf()
    stub = any(server.startswith("127.") for server in configured)
    return configured, _upstream_resolvers() if stub else []


# ---- Probes ----

def tcp_probe(host, port, timeout=PROBE_TIMEOUT):
    """A completed TCP handshake, with no payload sent. Returns (ok, detail)."""
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True, f"TCP handshake to {host}:{port} completed"
    except socket.timeout:
        return False, f"TCP connection to {host}:{port} timed out after {timeout:.0f}s"
    except OSError as e:
        return False, f"TCP connection to {host}:{port} failed ({e.strerror or e})"


def ping(host, count=1, wait=2, timeout=PING_TIMEOUT):
    """Returns (ok, output_or_error). ICMP is filtered on plenty of networks, so a False here means
    "did not answer ping", never "is offline"."""
    output, error = _run(["ping", "-c", str(count), "-W", str(wait), host], timeout=timeout)
    if error:
        return False, error
    return "0% packet loss" in output or " 0.0% packet loss" in output, output


def _neighbour_state(address):
    """What the ARP/neighbour table says about an address - a gateway that answers at layer 2 but
    not to ping is a meaningfully different fault from one that is simply absent."""
    text, error = _run(["ip", "neigh", "show", address])
    if error or not text:
        return None
    for line in text.splitlines():
        if line.split() and line.split()[0] == address:
            for state in ("REACHABLE", "STALE", "DELAY", "PROBE", "PERMANENT", "FAILED", "INCOMPLETE"):
                if state in line:
                    return state
    return None


# ---- The ladder ----

@dataclass
class Rung:
    name: str
    status: str = "unknown"  # ok | fail | unknown
    detail: str = ""


LADDER_ORDER = ("link", "address", "gateway", "dns", "internet")


def _check_link(gateway_iface):
    """Is there a cable or an associated radio at all."""
    rung = Rung("link")
    interfaces = [i for i in list_interfaces() if i.name != "lo"]

    if not interfaces:
        rung.status = "fail"
        rung.detail = "no network interfaces exist on this machine besides loopback"
        return rung, None

    # The interface carrying the default route is the one that matters; without a default route, any
    # interface that is up will do to establish that the hardware side is working.
    candidates = [i for i in interfaces if i.name == gateway_iface] or interfaces
    up = [i for i in candidates if i.operstate == "up" and i.carrier in ("up", "unknown")]

    if up:
        chosen = up[0]
        rung.status = "ok"
        rung.detail = f"{chosen.name} ({chosen.kind}) is up with a carrier"
        return rung, chosen

    down = ", ".join(f"{i.name} ({i.operstate}, carrier {i.carrier})" for i in candidates[:4])
    rung.status = "fail"
    rung.detail = f"no interface has a carrier: {down}"
    return rung, None


def _check_address(gateway_ip):
    rung = Rung("address")
    address = local_address_for(gateway_ip or PROBE_PING_TARGET)

    if address is None:
        rung.status = "fail"
        rung.detail = "no route to any destination, so no source address could be determined"
    elif address.startswith("169.254."):
        rung.status = "fail"
        rung.detail = (
            f"the address is {address}, a link-local autoconfiguration address. DHCP never answered, "
            "so the link is up but nothing assigned an address"
        )
    else:
        rung.status = "ok"
        rung.detail = f"using source address {address}"
    return rung, address


def _check_gateway(gateway_ip):
    rung = Rung("gateway")
    if gateway_ip is None:
        rung.status = "fail"
        rung.detail = "no default route is configured, so there is no gateway to reach"
        return rung

    reachable, _ = ping(gateway_ip, count=2, wait=1)
    if reachable:
        rung.status = "ok"
        rung.detail = f"gateway {gateway_ip} answers ping"
        return rung

    state = _neighbour_state(gateway_ip)
    if state in ("REACHABLE", "STALE", "DELAY", "PROBE", "PERMANENT"):
        rung.status = "ok"
        rung.detail = (
            f"gateway {gateway_ip} does not answer ping but is {state} in the neighbour table, so it "
            "is present and responding at layer 2. Many routers drop ICMP by policy"
        )
        return rung

    rung.status = "fail"
    rung.detail = (
        f"gateway {gateway_ip} does not answer ping"
        + (f" and is {state} in the neighbour table" if state else " and has no neighbour entry")
    )
    return rung


def _check_dns():
    """Resolution through nsswitch and the system resolver, which is what applications use. `dig`
    would query a server directly and could succeed on a machine where every application still
    fails."""
    rung = Rung("dns")
    output, error = _run(["getent", "hosts", PROBE_NAME], timeout=DNS_TIMEOUT)

    if error and "not installed" in error:
        # Fall back to the resolver this process would use. Less faithful to nsswitch, but better
        # than reporting nothing.
        try:
            socket.setdefaulttimeout(DNS_TIMEOUT)
            socket.getaddrinfo(PROBE_NAME, None)
            rung.status = "ok"
            rung.detail = f"{PROBE_NAME} resolved (via this process's resolver; getent is unavailable)"
        except (socket.gaierror, OSError) as e:
            rung.status = "fail"
            rung.detail = f"{PROBE_NAME} did not resolve ({e})"
        finally:
            socket.setdefaulttimeout(None)
        return rung

    if error or not output:
        rung.status = "fail"
        rung.detail = f"{PROBE_NAME} did not resolve through the system resolver"
        return rung

    rung.status = "ok"
    rung.detail = f"{PROBE_NAME} resolved to {output.split()[0]}"
    return rung


def _check_internet():
    """Decided by a TCP handshake, never by ping. Returns the rung plus whether ICMP also worked, so
    a network that filters ICMP can be reported as exactly that rather than as an outage."""
    rung = Rung("internet")
    for host, port in PROBE_TARGETS:
        ok, detail = tcp_probe(host, port)
        if ok:
            rung.status = "ok"
            rung.detail = detail
            icmp_ok, _ = ping(PROBE_PING_TARGET, count=1, wait=2)
            return rung, icmp_ok

    rung.status = "fail"
    rung.detail = (
        "no TCP connection could be established to "
        + " or ".join(f"{h}:{p}" for h, p in PROBE_TARGETS)
    )
    return rung, False


def _verdict(rungs):
    """(failed_at, severity). Severity is never stronger than the rungs support - that rule is
    enforced again in the report parser, because it is the one claim a model is most tempted to
    round up."""
    failed = [name for name in LADDER_ORDER if rungs[name].status == "fail"]
    if not failed:
        return None, "online"

    first = failed[0]
    # DNS is the one rung that can fail on its own without meaning "no connectivity": the machine can
    # reach the internet by address and simply cannot turn names into addresses.
    if failed == ["dns"] and rungs["internet"].status == "ok":
        return "dns", "degraded"
    return first, "offline"


def connectivity_check(arg=None):
    """The layered verdict. Returns text for the model, never raises."""
    gateway_ip, gateway_iface = default_gateway()

    link, chosen = _check_link(gateway_iface)
    rungs = {"link": link}

    if link.status == "fail":
        # Every rung above link would fail for the same reason, and reporting five failures for one
        # cause invites the model to describe five problems.
        for name in ("address", "gateway", "dns", "internet"):
            rungs[name] = Rung(name, "unknown", "not checked: there is no working link to test on")
        icmp_ok = False
    else:
        address_rung, _ = _check_address(gateway_ip)
        rungs["address"] = address_rung
        rungs["gateway"] = _check_gateway(gateway_ip)
        rungs["dns"] = _check_dns()
        rungs["internet"], icmp_ok = _check_internet()

    failed_at, severity = _verdict(rungs)

    rows = [[name.upper(), rungs[name].status, rungs[name].detail] for name in LADDER_ORDER]
    parts = [
        f"VERDICT: {severity}",
        f"FAILED AT: {failed_at}" if failed_at else "FAILED AT: none - every layer checked out",
        "",
        _table(rows, ["LAYER", "STATUS", "DETAIL"]),
        "",
        f"GATEWAY: {gateway_ip or 'none configured'}"
        + (f" via {gateway_iface}" if gateway_iface else ""),
    ]

    configured, upstream = resolvers()
    if configured:
        line = f"RESOLVERS: {', '.join(configured)}"
        if upstream:
            line += f" (a local stub; upstream servers are {', '.join(upstream[:4])})"
        parts.append(line)

    if rungs["internet"].status == "ok" and not icmp_ok:
        parts.append(
            "NOTE: the internet is reachable over TCP but does not answer ping. ICMP is filtered on "
            "this path. Do not describe this machine as offline, and do not use ping alone as "
            "evidence of an outage."
        )

    parts.append(
        "NOTE: this verdict describes this machine's own view. Nothing here observes the router's "
        "internals or the ISP, so do not attribute a fault to either as though it had been checked."
    )
    return "\n".join(parts)


def ping_gateway(arg=None):
    """The gateway probe on its own, for when the LAN itself is the question."""
    gateway_ip, gateway_iface = default_gateway()
    if gateway_ip is None:
        return (
            "No default route is configured, so this machine has no gateway to reach. That is itself "
            "the fault: without a default route nothing outside the local subnet is reachable."
        )

    ok, output = ping(gateway_ip, count=4, wait=2)
    state = _neighbour_state(gateway_ip)
    header = f"GATEWAY: {gateway_ip}" + (f" via {gateway_iface}" if gateway_iface else "")
    neighbour = f"NEIGHBOUR TABLE: {state}" if state else "NEIGHBOUR TABLE: no entry"

    if ok:
        return f"{header}\n{neighbour}\n\n{output}"
    return (
        f"{header}\n{neighbour}\n\n"
        f"The gateway did not answer ping. {output}\n\n"
        "NOTE: many routers drop ICMP by policy. A REACHABLE or STALE neighbour entry above means the "
        "gateway is present and answering at layer 2 despite the ping result."
    )


def ping_dns_server(arg=None):
    """Are the configured resolvers reachable at all - a different question from whether resolution
    works, and the one that separates a broken resolver from a broken path to it."""
    configured, upstream = resolvers()
    targets = [s for s in (upstream or configured) if not s.startswith("127.")]

    if not configured:
        return "No nameservers are configured in /etc/resolv.conf, so name resolution cannot work."
    if not targets:
        return (
            f"The only configured resolver is {', '.join(configured)}, which is a local stub, and no "
            "upstream server could be read from resolvectl. There is nothing external to probe; use "
            "dns_servers to see what the stub is forwarding to."
        )

    rows = []
    for server in targets[:4]:
        icmp_ok, _ = ping(server, count=2, wait=1)
        tcp_ok, tcp_detail = tcp_probe(server, 53)
        rows.append([
            server,
            "yes" if icmp_ok else "no",
            "yes" if tcp_ok else "no",
            tcp_detail if not tcp_ok else "",
        ])

    return (
        f"CONFIGURED: {', '.join(configured)}\n"
        + (f"UPSTREAM: {', '.join(upstream)}\n" if upstream else "")
        + "\n"
        + _table(rows, ["SERVER", "ANSWERS PING", "ACCEPTS TCP/53", "DETAIL"])
        + "\n\nNOTE: a resolver that accepts TCP on port 53 is reachable even if it ignores ping. "
        "Reachability is not the same as working resolution - use system_lookup for that."
    )


def captive_portal_check(arg=None):
    """Is something intercepting traffic. The only outbound HTTP request in this module."""
    request = urllib.request.Request(PORTAL_URL, headers={"User-Agent": "Opsy/1.0"})
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            status = response.status
            body = response.read(512)
            final_url = response.geturl()
    except urllib.error.HTTPError as e:
        return (
            f"The connectivity check endpoint returned HTTP {e.code}, which a plain internet "
            "connection never does. Something on this network is intercepting HTTP requests - "
            "typically a captive portal waiting for sign-in."
        )
    except (urllib.error.URLError, OSError, ValueError) as e:
        return (
            f"The connectivity check could not be completed ({e}). This is consistent with having no "
            "internet access at all rather than with a captive portal; run connectivity_check to see "
            "which layer is failing."
        )

    if status == 204 and not body:
        return (
            "No captive portal. The connectivity check returned HTTP 204 with an empty body, exactly "
            "as an uninterrupted connection should."
        )
    return (
        f"A captive portal is intercepting traffic. The connectivity check returned HTTP {status} "
        f"with {len(body)} bytes of content from {final_url}, where an uninterrupted connection "
        "returns 204 with no body. Signing in through a browser will usually clear it."
    )


# ---- Sockets ----

@dataclass
class SocketRow:
    netid: str
    state: str
    local: str
    peer: str
    program: str = ""
    pid: int = 0


@dataclass
class ConnectionGroup:
    name: str
    established: int = 0
    listening: int = 0
    other: int = 0
    pids: set = field(default_factory=set)
    peers: list = field(default_factory=list)
    exposed: bool = False

    @property
    def total(self):
        return self.established + self.listening + self.other


_PROCESS_RE = re.compile(r'\("([^"]+)",pid=(\d+)')
_LISTEN_STATES = {"LISTEN", "UNCONN"}


def parse_ss_output(text):
    """Parses `ss -tunap` output. Split out from the subprocess call so the parsing and grouping can
    be exercised against captured output without a live machine."""
    rows = []
    for line in text.splitlines():
        parts = line.split()
        # Netid State Recv-Q Send-Q Local:Port Peer:Port [Process]
        if len(parts) < 6 or parts[0].lower() == "netid":
            continue

        match = _PROCESS_RE.search(line)
        program, pid = ("", 0)
        if match:
            program = match.group(1)
            try:
                pid = int(match.group(2))
            except ValueError:
                pid = 0

        rows.append(
            SocketRow(
                netid=parts[0],
                state=parts[1],
                local=parts[4],
                peer=parts[5],
                program=program,
                pid=pid,
            )
        )
    return rows


def _own_pids():
    """Opsy's own process and its ancestors, read from /proc.

    Opsy answering a question about the machine should not report its own API socket back as one of
    the user's network connections. Mirrors the same exclusion the process agent makes."""
    own = {os.getpid()}
    current = os.getpid()
    for _ in range(16):  # bounded, so a malformed /proc cannot loop forever
        text, error = _read(f"/proc/{current}/stat")
        if error or not text:
            break
        # comm can contain spaces and brackets, so ppid is read from after the closing paren.
        closing = text.rfind(")")
        fields = text[closing + 1:].split() if closing != -1 else []
        if len(fields) < 2:
            break
        try:
            parent = int(fields[1])
        except ValueError:
            break
        if parent <= 1 or parent in own:
            break
        own.add(parent)
        current = parent
    return own


def _read_sockets():
    """(rows, error). `-a` includes listening sockets, `-p` attaches process information where the
    caller is entitled to see it, `-n` keeps ports numeric so nothing here triggers a DNS lookup."""
    text, error = _run(["ss", "-tunap"], timeout=20)
    if error:
        return [], f"the socket table could not be read: {error}"
    rows = parse_ss_output(text)
    if not rows:
        return [], "the socket table came back empty, which should not happen"
    return rows, None


def _confidence_block(unattributed, total):
    if unattributed == 0:
        return (
            "SOCKET ATTRIBUTION: every socket was matched to a program.\n"
            "CONFIDENCE: full - which program owns each connection is known."
        )

    root = os.geteuid() == 0
    reason = (
        "some sockets are held by the kernel or by processes that exited between listing and reading"
        if root
        else "Opsy is not running as root, so sockets belonging to other users cannot be attributed "
        "to a program. Running Opsy with sudo would attribute them"
    )
    return (
        f"SOCKET ATTRIBUTION: {unattributed} of {total} sockets could not be matched to a program. "
        f"{reason}.\n"
        "CONFIDENCE: degraded - the connection counts are accurate, but which program owns the "
        "unattributed sockets is unknown. Do not guess at their owners."
    )


def app_connections(arg=None):
    """Sockets grouped by application. Returns text for the model, never raises."""
    rows, error = _read_sockets()
    if error:
        return error

    own = _own_pids()
    groups = {}
    unattributed = 0
    own_sockets = 0

    for row in rows:
        if row.pid and row.pid in own:
            own_sockets += 1
            continue

        if row.program:
            name = row.program
        else:
            unattributed += 1
            name = "unattributed"

        group = groups.get(name)
        if group is None:
            group = groups[name] = ConnectionGroup(name=name)

        if row.pid:
            group.pids.add(row.pid)

        if row.state in _LISTEN_STATES:
            group.listening += 1
            # 0.0.0.0 and [::] mean reachable from the network; 127.0.0.1 does not. This is the whole
            # answer to "is this port exposed", so it is computed here rather than left to the model.
            if row.local.startswith(("0.0.0.0:", "*:", "[::]:")):
                group.exposed = True
        elif row.state == "ESTAB":
            group.established += 1
            if row.peer and row.peer != "*:*":
                group.peers.append(row.peer)
        else:
            group.other += 1

    counted = len(rows) - own_sockets
    if not groups:
        return (
            f"{_confidence_block(unattributed, counted)}\n\n"
            "CONNECTIONS: none. No process on this machine currently holds a network socket."
        )

    ordered = sorted(groups.values(), key=lambda g: (-g.total, g.name))
    shown = ordered[:MAX_APP_ROWS]

    table_rows = []
    for group in shown:
        peers = sorted(set(group.peers))
        detail = ""
        if peers:
            detail = ", ".join(peers[:3])
            if len(peers) > 3:
                detail += f", +{len(peers) - 3} more"
        if group.exposed:
            detail = f"listening on all interfaces; {detail}" if detail else "listening on all interfaces"

        table_rows.append([
            group.name,
            str(group.established),
            str(group.listening),
            str(len(group.pids)) if group.pids else "-",
            detail or "-",
        ])

    headers = ["PROGRAM", "ESTABLISHED", "LISTENING", "PROCS", "DETAIL"]
    parts = [
        _confidence_block(unattributed, counted),
        "",
        f"CONNECTIONS ({len(ordered)} programs holding {counted} sockets)",
        _table(table_rows, headers),
    ]

    if len(ordered) > MAX_APP_ROWS:
        parts.append(f"\n[{len(ordered) - MAX_APP_ROWS} further programs not shown, smallest first]")
    if own_sockets:
        parts.append(f"HIDDEN: {own_sockets} sockets belonging to Opsy itself are not shown.")

    parts.append(
        "NOTE: a socket listening on 0.0.0.0 or [::] accepts connections from the network; one on "
        "127.0.0.1 accepts only from this machine. Say which when asked whether a port is exposed."
    )
    return "\n".join(parts)


def remote_peers(arg=None):
    """Established connections grouped by the far end rather than by the program."""
    rows, error = _read_sockets()
    if error:
        return error

    own = _own_pids()
    peers = {}
    for row in rows:
        if row.state != "ESTAB" or (row.pid and row.pid in own):
            continue
        # Split off the port, keeping IPv6 brackets intact.
        address = row.peer.rsplit(":", 1)[0] if ":" in row.peer else row.peer
        if not address or address == "*":
            continue
        entry = peers.setdefault(address, {"count": 0, "programs": set(), "ports": set()})
        entry["count"] += 1
        if row.program:
            entry["programs"].add(row.program)
        port = row.peer.rsplit(":", 1)[1] if ":" in row.peer else ""
        if port:
            entry["ports"].add(port)

    if not peers:
        return "No established connections. Nothing on this machine is currently talking to a remote host."

    ordered = sorted(peers.items(), key=lambda item: (-item[1]["count"], item[0]))
    table_rows = [
        [
            address,
            str(entry["count"]),
            ",".join(sorted(entry["ports"])[:4]) or "-",
            ", ".join(sorted(entry["programs"])[:3]) or "unattributed",
        ]
        for address, entry in ordered[:MAX_PEER_ROWS]
    ]

    parts = [
        f"REMOTE PEERS ({len(ordered)} distinct hosts across "
        f"{sum(e['count'] for e in peers.values())} established connections)",
        _table(table_rows, ["REMOTE ADDRESS", "CONNS", "PORTS", "PROGRAMS"]),
    ]
    if len(ordered) > MAX_PEER_ROWS:
        parts.append(f"\n[{len(ordered) - MAX_PEER_ROWS} further hosts not shown]")
    parts.append(
        "NOTE: addresses are not resolved to names, because doing so would issue a DNS query per "
        "host. Port 443 is ordinary encrypted web traffic and is not evidence of anything unusual."
    )
    return "\n".join(parts)


# ---- Throughput ----

def _counters(name):
    rx, rx_error = _read(f"{SYS_NET}/{name}/statistics/rx_bytes")
    tx, tx_error = _read(f"{SYS_NET}/{name}/statistics/tx_bytes")
    if rx_error or tx_error:
        return None
    try:
        return int(rx), int(tx)
    except ValueError:
        return None


def interface_throughput(arg=None):
    """What is actually moving right now, sampled over one second.

    /proc/net/dev and every counter in /sys are cumulative since boot, which cannot answer "is
    something saturating my link at this moment". Two reads a second apart can, and unlike ifstat,
    nload or bmon it needs nothing installed."""
    if arg:
        if not interface_exists(arg):
            return (
                f"'{arg}' is not an interface on this machine. Available: "
                f"{', '.join(interface_names()) or 'none'}."
            )
        names = [arg]
    else:
        names = [i.name for i in list_interfaces() if i.name != "lo" and i.operstate == "up"]
        if not names:
            return "No interface is up, so nothing can be carrying traffic. Check link_status."

    first = {name: _counters(name) for name in names}
    time.sleep(1.0)
    second = {name: _counters(name) for name in names}

    rows = []
    for name in names:
        start, end = first.get(name), second.get(name)
        if start is None or end is None:
            rows.append([name, "unreadable", "unreadable", "-", "-"])
            continue
        rx_rate = max(0, end[0] - start[0])
        tx_rate = max(0, end[1] - start[1])
        rows.append([
            name,
            format_rate(rx_rate),
            format_rate(tx_rate),
            format_bytes(end[0]),
            format_bytes(end[1]),
        ])

    return (
        _table(rows, ["INTERFACE", "DOWN NOW", "UP NOW", "TOTAL RX", "TOTAL TX"])
        + "\n\nNOTE: the two 'now' columns are measured over a single one-second sample, so they show "
        "the current rate rather than a since-boot average. A one-second sample can miss bursty "
        "traffic; the totals are cumulative since boot."
    )


# ---- Proxy and VPN ----

_PROXY_VARS = ("http_proxy", "https_proxy", "ftp_proxy", "all_proxy", "no_proxy")


def proxy_settings(arg=None):
    """Proxy configuration across all three places it can be set.

    A half-configured proxy is one of the most common causes of "the browser works but nothing else
    does", and no single command shows the environment, the desktop setting and /etc/environment
    together."""
    lines = []

    env = {}
    for var in _PROXY_VARS:
        for key in (var, var.upper()):
            if os.environ.get(key):
                env[key] = os.environ[key]
    if env:
        lines.append("ENVIRONMENT:")
        lines.extend(f"  {k}={v}" for k, v in sorted(env.items()))
    else:
        lines.append("ENVIRONMENT: no proxy variables are set in Opsy's own environment.")
        lines.append(
            "  NOTE: this is Opsy's environment, not the desktop session's. An application launched "
            "from a desktop menu may still have different settings."
        )

    text, error = _read("/etc/environment")
    if not error and text:
        matched = [
            line for line in text.splitlines()
            if any(var in line.lower() for var in ("proxy",))
        ]
        lines.append("")
        lines.append(
            "/etc/environment: " + ("\n  " + "\n  ".join(matched) if matched else "no proxy entries.")
        )

    output, gs_error = _run(["gsettings", "get", "org.gnome.system.proxy", "mode"])
    if not gs_error:
        lines.append("")
        lines.append(f"GNOME PROXY MODE: {output}")
        if output.strip("' ") == "manual":
            for schema, keys in (
                ("org.gnome.system.proxy.http", ("host", "port")),
                ("org.gnome.system.proxy.https", ("host", "port")),
            ):
                values = []
                for key in keys:
                    value, key_error = _run(["gsettings", "get", schema, key])
                    values.append(value if not key_error else "?")
                lines.append(f"  {schema.rsplit('.', 1)[-1]}: {':'.join(values)}")

    return "\n".join(lines)


def vpn_status(arg=None):
    """Tunnel interfaces and the routes they claim. Never prints key material."""
    tunnels = [i for i in list_interfaces() if i.kind == "tunnel"]
    if not tunnels:
        return (
            "No tunnel interfaces exist. No VPN of the tun, tap or WireGuard kind is currently "
            "established. A VPN implemented purely as a proxy would not appear here - check "
            "proxy_settings for that."
        )

    rows = [
        [i.name, i.operstate, i.carrier, i.mtu or "-"]
        for i in tunnels
    ]
    parts = [
        f"TUNNEL INTERFACES ({len(tunnels)})",
        _table(rows, ["NAME", "STATE", "CARRIER", "MTU"]),
    ]

    routes, route_error = _run(["ip", "route", "show"])
    if not route_error and routes:
        claimed = [
            line for line in routes.splitlines()
            if any(f"dev {t.name}" in line for t in tunnels)
        ]
        parts.append("")
        parts.append("ROUTES THROUGH TUNNELS:")
        parts.extend(f"  {line}" for line in claimed[:15] or ["  none - the tunnel carries no routes"])

    # `wg show` prints public keys and endpoints. `wg show all dump` is deliberately not used: its
    # first field is the interface's private key.
    wg_output, wg_error = _run(["wg", "show"])
    if not wg_error and wg_output:
        parts.append("")
        parts.append("WIREGUARD:")
        parts.extend(f"  {line}" for line in wg_output.splitlines()[:25])

    parts.append("")
    parts.append(
        "NOTE: a default route through a tunnel means all traffic is carried by it; a handful of "
        "specific routes means a split tunnel, where only some destinations use the VPN. Check "
        "policy_rules as well, since policy routing can redirect traffic without appearing here."
    )
    return "\n".join(parts)


# ---- The overview ----

def network_overview(arg=None):
    """Interfaces, addresses, gateway and resolvers in one call - the sensible opening move for
    anything that is not a fault report."""
    interfaces = list_interfaces()
    if not interfaces:
        return "No network interfaces could be read from /sys/class/net on this machine."

    addresses = {}
    output, error = _run(["ip", "-br", "addr", "show"])
    if not error:
        for line in output.splitlines():
            parts = line.split()
            if parts:
                addresses[parts[0].split("@")[0]] = " ".join(parts[2:]) if len(parts) > 2 else ""

    gateway_ip, gateway_iface = default_gateway()
    configured, upstream = resolvers()

    rows = []
    for interface in interfaces:
        rows.append([
            interface.name,
            interface.kind,
            interface.operstate,
            interface.carrier,
            addresses.get(interface.name, "-") or "-",
            "default route" if interface.name == gateway_iface else "",
        ])

    parts = [
        f"INTERFACES ({len(interfaces)})",
        _table(rows, ["NAME", "KIND", "STATE", "CARRIER", "ADDRESSES", "NOTE"]),
        "",
        f"DEFAULT GATEWAY: {gateway_ip or 'none configured'}"
        + (f" via {gateway_iface}" if gateway_iface else ""),
        f"RESOLVERS: {', '.join(configured) if configured else 'none configured'}"
        + (f" (local stub; upstream {', '.join(upstream[:4])})" if upstream else ""),
    ]

    if error:
        parts.append(
            f"NOTE: per-interface addresses could not be read ({error}), so the ADDRESSES column is "
            "empty. Link state and the gateway above are read from /proc and /sys and are accurate."
        )

    nm_output, nm_error = _run(["nmcli", "-t", "-f", "DEVICE,STATE,CONNECTION", "dev", "status"])
    if not nm_error and nm_output:
        parts.append("")
        parts.append("NETWORKMANAGER:")
        parts.extend(f"  {line}" for line in nm_output.splitlines()[:12])

    return "\n".join(parts)
