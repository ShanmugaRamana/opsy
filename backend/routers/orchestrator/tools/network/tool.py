"""Allow-listed, read-only observations about connectivity, interfaces, routing, DNS and sockets.

Same contract as the disk and process tools: the caller only ever selects an id (plus, for some, a
single argument value), never argv, never a shell string. Nothing here configures, connects,
disconnects, flushes or reconfigures anything - there is no `nmcli con up`, no `ip link set`, no
`resolvectl flush-caches`. Reconnecting a network is a mutating action and does not belong in a fixed
allow-list the agent can call freely.

Two boundaries are worth stating explicitly, because "read-only" alone does not settle them:

- **This machine's own view only.** Several commands here send packets - a ping, a traceroute, a DNS
  query - which is unavoidable when the question is "can I reach this". What is refused is reaching
  outward for its own sake: no host scanning, no packet capture, no throughput testing. Those are
  denied to `request_command` too, in `tools/command/tool.py`, with their own message.
- **No credentials, ever.** `nmcli con show` is exposed without `--show-secrets`, and the WireGuard,
  wpa_supplicant, NetworkManager and netplan configuration files are not exposed at all. Every one of
  them stores a PSK or a private key in plain text, and everything a command returns is sent to a
  model provider. Same call the process tool made about `/proc/<pid>/environ`.

Three kinds of observation, as in the process tool:

- **command** - a fixed argv, run with shell=False.
- **file** - a fixed path under /proc or /etc, read directly.
- **python** - computed in `net.py`. `connectivity_check` and `app_connections` are the important
  ones: a layered verdict and a socket table grouped by application are the difference between
  answering the question and dumping `ifconfig` at someone, and both have to be deterministic rather
  than a hope about the model.
"""
import logging
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from . import net

logger = logging.getLogger("tools.network")

MAX_OUTPUT_CHARS = 3000
ARG_TOKEN = "{arg}"

# A host becomes one argv token and never touches a shell, so this validates for usability - and to
# stop a value that begins with "-" from being read as an option by ping or dig.
_HOST_RE = re.compile(r"^\[?[A-Za-z0-9][A-Za-z0-9._:%-]{0,253}\]?$")


@dataclass(frozen=True)
class NetworkCommand:
    label: str
    description: str
    kind: str = "command"
    argv: tuple = ()
    file_path: str = ""
    handler: str = ""  # for kind="python"
    arg_mode: str = "none"  # none | optional | required
    arg_kind: str = "iface"  # iface | host | port
    requires: str = ""
    timeout: int = 15
    needs_root: bool = False
    postprocess: str = ""
    limit: int = 25


NETWORK_COMMANDS: dict[str, NetworkCommand] = {
    # ---- The computed views ----
    "connectivity_check": NetworkCommand(
        "Connectivity check",
        "Am I online, and if not, which layer failed. Walks link, address, gateway, DNS and internet "
        "and names the rung that broke. The right answer to 'is my internet working' and to 'why is "
        "it not working' - start here for any fault report.",
        kind="python", handler="connectivity_check", timeout=45,
    ),
    "network_overview": NetworkCommand(
        "Network overview",
        "Interfaces with their addresses and link state, the default gateway, and the resolvers in "
        "use. The 'what is my setup' answer and the sensible opening move for anything that is not a "
        "fault report.",
        kind="python", handler="network_overview", timeout=30,
    ),
    "app_connections": NetworkCommand(
        "Connections by application",
        "Network sockets grouped by the program that owns them, with established and listening counts. "
        "The right answer to 'what is using my network'. States whether socket ownership could be "
        "determined.",
        kind="python", handler="app_connections", timeout=30,
    ),
    "remote_peers": NetworkCommand(
        "Remote peers",
        "Established connections grouped by the remote host rather than by program. Answers 'what is "
        "my machine talking to'.",
        kind="python", handler="remote_peers", timeout=30,
    ),
    "interface_throughput": NetworkCommand(
        "Current throughput",
        "Bytes per second moving right now, sampled over one second. Every other counter is "
        "cumulative since boot and cannot show whether something is saturating the link at this "
        "moment.",
        kind="python", handler="interface_throughput", arg_mode="optional", arg_kind="iface",
        timeout=30,
    ),
    "proxy_settings": NetworkCommand(
        "Proxy configuration",
        "Proxy settings across the environment, the desktop and /etc/environment. A half-configured "
        "proxy is a common cause of 'the browser works but nothing else does'.",
        kind="python", handler="proxy_settings", timeout=20,
    ),
    "vpn_status": NetworkCommand(
        "VPN and tunnels",
        "Tunnel interfaces, the routes they carry and WireGuard peer state. Distinguishes a full "
        "tunnel from a split tunnel.",
        kind="python", handler="vpn_status", timeout=20,
    ),
    "ping_gateway": NetworkCommand(
        "Ping the gateway",
        "Is the local network itself healthy. Finds the default gateway and probes it, falling back "
        "to the neighbour table when the router drops ICMP.",
        kind="python", handler="ping_gateway", timeout=30,
    ),
    "ping_dns_server": NetworkCommand(
        "Probe the resolvers",
        "Are the configured DNS servers reachable at all. A different question from whether "
        "resolution works, and it separates a broken resolver from a broken path to it.",
        kind="python", handler="ping_dns_server", timeout=45,
    ),
    "captive_portal_check": NetworkCommand(
        "Captive portal check",
        "Is a portal intercepting traffic, as on hotel and airport networks. Makes one HTTP request "
        "to a fixed connectivity-check endpoint, so use it only when a portal is genuinely suspected.",
        kind="python", handler="captive_portal_check", timeout=20,
    ),
    # ---- Interfaces and link state ----
    "interfaces": NetworkCommand(
        "Interfaces and addresses",
        "Every interface with its IP addresses, one line each.",
        argv=("ip", "-br", "addr", "show"), requires="ip",
    ),
    "interface_detail": NetworkCommand(
        "Interface detail", "One interface in full: addresses, flags, MTU and state.",
        argv=("ip", "addr", "show", "dev", ARG_TOKEN), arg_mode="required", arg_kind="iface",
        requires="ip",
    ),
    "link_status": NetworkCommand(
        "Link status", "Up/down and carrier state per interface, without addresses.",
        argv=("ip", "-br", "link", "show"), requires="ip",
    ),
    "link_details": NetworkCommand(
        "Link types",
        "What each interface actually is: vlan, bridge, bond, tun or wireguard. A name alone does not "
        "say.",
        argv=("ip", "-d", "link", "show"), requires="ip", postprocess="top_lines", limit=40,
    ),
    "interface_stats": NetworkCommand(
        "Interface statistics",
        "Packets, errors, drops and overruns for one interface. Errors and drops point at the cable, "
        "the driver or the radio, which are local causes rather than the ISP.",
        argv=("ip", "-s", "link", "show", "dev", ARG_TOKEN), arg_mode="required", arg_kind="iface",
        requires="ip",
    ),
    "interface_speed": NetworkCommand(
        "Negotiated speed",
        "Link speed and duplex actually negotiated. A gigabit port running at 100Mb half-duplex is a "
        "severe fault that nothing else reveals.",
        argv=("ethtool", ARG_TOKEN), arg_mode="required", arg_kind="iface", requires="ethtool",
        postprocess="top_lines", limit=30,
    ),
    "interface_driver": NetworkCommand(
        "Interface driver", "Driver and firmware version, for a network card that misbehaves.",
        argv=("ethtool", "-i", ARG_TOKEN), arg_mode="required", arg_kind="iface", requires="ethtool",
    ),
    "net_dev_stats": NetworkCommand(
        "Interface counters",
        "Cumulative byte and packet counters for every interface since boot. Use "
        "interface_throughput for the current rate.",
        kind="file", file_path="/proc/net/dev",
    ),
    "mtu_settings": NetworkCommand(
        "MTU per interface",
        "The maximum packet size each interface accepts. A mismatch causes large transfers to hang "
        "while small ones succeed.",
        argv=("ip", "-o", "link", "show"), requires="ip", postprocess="mtu_only",
    ),
    "rfkill_status": NetworkCommand(
        "Radio blocks",
        "Whether a wireless radio is soft- or hard-blocked. The real answer to 'my wifi disappeared' - "
        "a hardware switch or a software block, not a driver fault.",
        argv=("rfkill", "list"), requires="rfkill",
    ),
    # ---- Wireless ----
    "wireless_status": NetworkCommand(
        "Wireless link",
        "SSID, signal strength in dBm, bitrate and frequency for one wireless interface. Signal below "
        "about -70 dBm explains a slow connection on its own.",
        argv=("iw", "dev", ARG_TOKEN, "link"), arg_mode="required", arg_kind="iface", requires="iw",
    ),
    "wireless_devices": NetworkCommand(
        "Wireless devices", "Every wireless interface and the mode it is operating in.",
        argv=("iw", "dev"), requires="iw",
    ),
    "wireless_signal": NetworkCommand(
        "Wireless signal levels",
        "Signal, noise and link quality per wireless interface, read from the kernel without needing "
        "iw installed.",
        kind="file", file_path="/proc/net/wireless",
    ),
    "wireless_station": NetworkCommand(
        "Access point statistics",
        "Per-connection statistics against the access point, including retry and failure counts. A "
        "high retry rate is what slow wifi usually is, and no ping test will reveal it.",
        argv=("iw", "dev", ARG_TOKEN, "station", "dump"), arg_mode="required", arg_kind="iface",
        requires="iw", postprocess="top_lines", limit=40,
    ),
    "wireless_scan": NetworkCommand(
        "Nearby networks",
        "Visible wireless networks with signal and channel, from the existing scan cache. Shows "
        "channel crowding, which is a common cause of slowness with a strong signal.",
        argv=("nmcli", "-f", "SSID,SIGNAL,CHAN,SECURITY", "dev", "wifi", "list", "--rescan", "no"),
        requires="nmcli", timeout=25, postprocess="top_lines", limit=30,
    ),
    "regulatory_domain": NetworkCommand(
        "Wireless regulatory domain",
        "The country code that decides which channels are legal. A wrong one silently removes usable "
        "spectrum.",
        argv=("iw", "reg", "get"), requires="iw", postprocess="top_lines", limit=25,
    ),
    # ---- Routing ----
    "routes": NetworkCommand(
        "Routing table", "The IPv4 routing table.",
        argv=("ip", "route", "show"), requires="ip", postprocess="top_lines", limit=30,
    ),
    "routes_v6": NetworkCommand(
        "IPv6 routing table", "The IPv6 routing table.",
        argv=("ip", "-6", "route", "show"), requires="ip", postprocess="top_lines", limit=30,
    ),
    "default_route": NetworkCommand(
        "Default route", "The gateway and the interface that reaches it.",
        argv=("ip", "route", "show", "default"), requires="ip",
    ),
    "route_to": NetworkCommand(
        "Route to a destination",
        "Which interface, gateway and source address a given destination would use. The answer to "
        "'why does this one site behave differently' and to most VPN and split-tunnel questions.",
        argv=("ip", "route", "get", ARG_TOKEN), arg_mode="required", arg_kind="host", requires="ip",
    ),
    "policy_rules": NetworkCommand(
        "Policy routing rules",
        "Rules that send traffic to different routing tables. VPN split tunnels live here and are "
        "invisible in the ordinary routing table.",
        argv=("ip", "rule", "show"), requires="ip", postprocess="top_lines", limit=25,
    ),
    "arp_table": NetworkCommand(
        "Neighbour table",
        "Which hosts on the local network have answered, and whether the gateway is reachable at "
        "layer 2.",
        argv=("ip", "neigh", "show"), requires="ip", postprocess="top_lines", limit=30,
    ),
    # ---- DNS ----
    "dns_servers": NetworkCommand(
        "DNS servers", "The resolvers actually in use, per link, as systemd-resolved sees them.",
        argv=("resolvectl", "status"), requires="resolvectl", postprocess="top_lines", limit=40,
    ),
    "dns_statistics": NetworkCommand(
        "DNS statistics", "Cache hit rate and failed transactions for the local resolver.",
        argv=("resolvectl", "statistics"), requires="resolvectl",
    ),
    "resolv_conf": NetworkCommand(
        "Resolver configuration",
        "What the classic resolver path is configured with. On systemd-resolved systems this points "
        "at a local stub rather than the real servers.",
        kind="file", file_path="/etc/resolv.conf",
    ),
    "nsswitch_config": NetworkCommand(
        "Name resolution order",
        "The order in which name sources are consulted. Explains the case where dig succeeds and "
        "applications still fail.",
        kind="file", file_path="/etc/nsswitch.conf",
    ),
    "hosts_file": NetworkCommand(
        "Hosts file",
        "Local name overrides, which explain a name that resolves to something unexpected.",
        kind="file", file_path="/etc/hosts",
    ),
    "dns_lookup": NetworkCommand(
        "DNS lookup", "Does this name resolve, and to what address.",
        argv=("dig", "+short", ARG_TOKEN), arg_mode="required", arg_kind="host", requires="dig",
        timeout=20,
    ),
    "dns_lookup_full": NetworkCommand(
        "DNS lookup (full)",
        "The complete answer with TTL, authority section and which server replied.",
        argv=("dig", ARG_TOKEN), arg_mode="required", arg_kind="host", requires="dig",
        timeout=20, postprocess="top_lines", limit=40,
    ),
    "system_lookup": NetworkCommand(
        "System name lookup",
        "Does the name resolve the way applications resolve it, through nsswitch and the system "
        "resolver. Use this rather than dig when the question is why an application cannot connect.",
        argv=("getent", "hosts", ARG_TOKEN), arg_mode="required", arg_kind="host", requires="getent",
        timeout=20,
    ),
    "reverse_lookup": NetworkCommand(
        "Reverse DNS lookup", "What name a given address claims to have.",
        argv=("dig", "-x", ARG_TOKEN), arg_mode="required", arg_kind="host", requires="dig",
        timeout=20, postprocess="top_lines", limit=25,
    ),
    # ---- Reachability and path ----
    "ping_host": NetworkCommand(
        "Ping a host", "Is a host reachable, and with what latency and packet loss.",
        argv=("ping", "-c", "4", "-W", "2", ARG_TOKEN), arg_mode="required", arg_kind="host",
        requires="ping", timeout=25,
    ),
    "traceroute_host": NetworkCommand(
        "Trace the route", "Where along the path packets stop or slow down.",
        argv=("traceroute", "-n", "-w", "2", "-q", "1", "-m", "20", ARG_TOKEN),
        arg_mode="required", arg_kind="host", requires="traceroute", timeout=90,
        postprocess="top_lines", limit=25,
    ),
    "tracepath_host": NetworkCommand(
        "Trace the path",
        "The same as traceroute but without needing raw sockets, and it reports the path MTU it "
        "discovers.",
        argv=("tracepath", "-n", ARG_TOKEN), arg_mode="required", arg_kind="host",
        requires="tracepath", timeout=90, postprocess="top_lines", limit=25,
    ),
    "mtr_report": NetworkCommand(
        "Per-hop loss report",
        "Packet loss and latency measured per hop. The single best way to find where on the path "
        "packets are being dropped.",
        argv=("mtr", "-r", "-c", "5", "-n", ARG_TOKEN), arg_mode="required", arg_kind="host",
        requires="mtr", timeout=90, postprocess="top_lines", limit=30,
    ),
    "mtu_probe": NetworkCommand(
        "Path MTU probe",
        "Sends an unfragmentable full-size packet. Failure here is a path MTU black hole, the fault "
        "where small requests succeed and large ones hang forever.",
        argv=("ping", "-M", "do", "-s", "1472", "-c", "2", "-W", "2", ARG_TOKEN),
        arg_mode="required", arg_kind="host", requires="ping", timeout=25,
    ),
    # ---- Sockets and ports ----
    "listening_ports": NetworkCommand(
        "Listening ports",
        "What is accepting connections and on which address. A socket on 0.0.0.0 is reachable from "
        "the network; one on 127.0.0.1 is not.",
        argv=("ss", "-tulnp"), requires="ss", postprocess="top_lines", limit=40,
    ),
    "active_connections": NetworkCommand(
        "Active sockets", "The raw socket table, including listeners.",
        argv=("ss", "-tunap"), requires="ss", timeout=20, postprocess="top_lines", limit=40,
    ),
    "established_connections": NetworkCommand(
        "Established connections",
        "Only the live conversations, without listeners or closing sockets.",
        argv=("ss", "-tnp", "state", "established"), requires="ss", timeout=20,
        postprocess="top_lines", limit=40,
    ),
    "connection_count": NetworkCommand(
        "Connection count", "How many sockets exist, counted rather than listed.",
        argv=("ss", "-tun"), requires="ss", postprocess="count_lines",
    ),
    "socket_summary": NetworkCommand(
        "Socket summary", "Totals by protocol and state.",
        argv=("ss", "-s"), requires="ss",
    ),
    "tcp_states": NetworkCommand(
        "TCP state histogram",
        "How many sockets sit in each TCP state. A pile of SYN-SENT means outbound connections are "
        "being blocked; a pile of TIME-WAIT is a busy client rather than a fault.",
        argv=("ss", "-tan"), requires="ss", timeout=20, postprocess="tcp_states",
    ),
    "port_usage": NetworkCommand(
        "What holds a port", "Which process is listening on a specific port.",
        argv=("ss", "-tulnp"), arg_mode="required", arg_kind="port", requires="ss",
        postprocess="only_port",
    ),
    # ---- Protocol health ----
    "tcp_statistics": NetworkCommand(
        "TCP retransmission rate",
        "Segments sent against segments retransmitted, as a percentage. The definitive measure of "
        "whether a connection is lossy, and nothing else exposes it.",
        kind="file", file_path="/proc/net/snmp", postprocess="tcp_snmp",
    ),
    "netstat_errors": NetworkCommand(
        "TCP listen queue drops",
        "Listen queue overflows and drops. Explains a server that refuses connections under load "
        "while appearing healthy.",
        kind="file", file_path="/proc/net/netstat", postprocess="listen_drops",
    ),
    "softnet_stats": NetworkCommand(
        "Kernel receive drops",
        "Packets dropped by the kernel's own receive path rather than by the network. Points at CPU "
        "starvation or an undersized backlog instead of a link problem.",
        kind="file", file_path="/proc/net/softnet_stat", postprocess="top_lines", limit=16,
    ),
    # ---- Firewall and managers ----
    "firewall_status": NetworkCommand(
        "Firewall status (ufw)", "Whether ufw is active and what it allows.",
        argv=("ufw", "status", "verbose"), requires="ufw", needs_root=True,
        postprocess="top_lines", limit=30,
    ),
    "firewalld_status": NetworkCommand(
        "Firewall status (firewalld)", "The active firewalld zone and its rules.",
        argv=("firewall-cmd", "--list-all"), requires="firewall-cmd", needs_root=True,
    ),
    "nft_ruleset": NetworkCommand(
        "nftables ruleset",
        "The raw nftables rules, for a machine running neither ufw nor firewalld.",
        argv=("nft", "list", "ruleset"), requires="nft", needs_root=True,
        postprocess="top_lines", limit=50,
    ),
    "iptables_rules": NetworkCommand(
        "iptables rules",
        "The legacy firewall rules with packet counts, still what many systems actually use.",
        argv=("iptables", "-L", "-n", "-v"), requires="iptables", needs_root=True,
        postprocess="top_lines", limit=50,
    ),
    "nm_status": NetworkCommand(
        "NetworkManager status", "Whether NetworkManager considers the machine connected.",
        argv=("nmcli", "general", "status"), requires="nmcli",
    ),
    "nm_devices": NetworkCommand(
        "NetworkManager devices", "Per-device state and which connection profile is active on it.",
        argv=("nmcli", "-t", "-f", "DEVICE,TYPE,STATE,CONNECTION", "dev", "status"), requires="nmcli",
        postprocess="top_lines", limit=25,
    ),
    "nm_connections": NetworkCommand(
        "NetworkManager profiles",
        "Configured connection profiles by name. Names only - no passwords or keys are ever read.",
        argv=("nmcli", "-t", "-f", "NAME,TYPE,DEVICE", "con", "show"), requires="nmcli",
        postprocess="top_lines", limit=30,
    ),
    "networkd_status": NetworkCommand(
        "systemd-networkd status",
        "The systemd-networkd view, on servers that run no NetworkManager.",
        argv=("networkctl", "status", "--no-pager"), requires="networkctl",
        postprocess="top_lines", limit=40,
    ),
}

_PYTHON_HANDLERS = {
    "connectivity_check": net.connectivity_check,
    "network_overview": net.network_overview,
    "app_connections": net.app_connections,
    "remote_peers": net.remote_peers,
    "interface_throughput": net.interface_throughput,
    "proxy_settings": net.proxy_settings,
    "vpn_status": net.vpn_status,
    "ping_gateway": net.ping_gateway,
    "ping_dns_server": net.ping_dns_server,
    "captive_portal_check": net.captive_portal_check,
}


def command_label(command_id):
    entry = NETWORK_COMMANDS.get(command_id)
    return entry.label if entry else str(command_id)


def tool_schema_properties():
    """Returns {command_id: description}, used to build each provider's tool schema."""
    return {cid: entry.description for cid, entry in NETWORK_COMMANDS.items()}


# ---- Argument validation ----

def validate_arg(raw, arg_kind):
    """Returns (value, None) or (None, error_message).

    The value becomes one element of an argv list and never touches a shell, so this validates for
    usability rather than injection - but an interface that does not exist is worth catching here, so
    the agent gets a list of the real ones back instead of a bare 'Cannot find device' from ip."""
    if raw is None or str(raw).strip() == "":
        return None, "no value given"

    text = str(raw).strip()
    if "\x00" in text:
        return None, "the value contains a null byte"

    if arg_kind == "iface":
        if not net.interface_exists(text):
            available = ", ".join(net.interface_names()) or "none"
            return None, f"'{text}' is not an interface on this machine. Available: {available}"
        return text, None

    if arg_kind == "port":
        if not text.isdigit() or not 1 <= int(text) <= 65535:
            return None, f"'{text}' is not a port number. Pass a number between 1 and 65535."
        return text, None

    # host
    if not _HOST_RE.match(text):
        return None, (
            f"'{text}' is not a valid hostname or IP address. Pass a bare name such as example.com "
            "or an address such as 1.1.1.1, with no scheme, path or port."
        )
    return text, None


# ---- Post-processing ----
#
# Most of these outputs carry a header row the model needs in order to read the columns, so every
# post-processor preserves it. There is no shell, so what a pipeline would do with head, grep or awk
# happens here instead.

def _split_header(output):
    lines = output.splitlines()
    return (lines[0], lines[1:]) if lines else ("", [])


def _postprocess_top_lines(output, entry, arg):
    header, rows = _split_header(output)
    if len(rows) <= entry.limit:
        return output
    kept = "\n".join(rows[: entry.limit])
    return f"{header}\n{kept}\n\n[{len(rows) - entry.limit} further rows not shown]"


def _postprocess_count_lines(output, entry, arg):
    rows = [line for line in output.splitlines() if line.strip()]
    # `ss` prints a header row, which is not a socket.
    count = max(0, len(rows) - 1) if rows and rows[0].lower().startswith(("netid", "state")) else len(rows)
    return f"{count} sockets."


def _postprocess_only_port(output, entry, arg):
    header, rows = _split_header(output)
    needle = f":{arg}"
    matched = [row for row in rows if any(field.endswith(needle) for field in row.split())]
    if not matched:
        return f"Nothing is listening on port {arg}."
    return "\n".join([header] + matched)


def _postprocess_mtu_only(output, entry, arg):
    """Name and MTU per interface, pulled out of `ip -o link show`, which buries them in flags."""
    rows = []
    for line in output.splitlines():
        parts = line.split()
        if len(parts) < 2:
            continue
        name = parts[1].rstrip(":").split("@")[0]
        mtu = ""
        for index, token in enumerate(parts):
            if token == "mtu" and index + 1 < len(parts):
                mtu = parts[index + 1]
                break
        if mtu:
            rows.append(f"{name}: MTU {mtu}")
    if not rows:
        return "No MTU values could be read from the link list."
    return "\n".join(rows) + (
        "\n\nA standard Ethernet MTU is 1500. A lower value on a tunnel is normal; a mismatch along "
        "a path causes large transfers to hang while small ones succeed."
    )


def _postprocess_tcp_states(output, entry, arg):
    """The state column of `ss -tan`, counted. A histogram answers the question the raw table only
    hints at, and it does not grow with the number of connections."""
    _, rows = _split_header(output)
    counts = {}
    for row in rows:
        parts = row.split()
        if parts:
            counts[parts[0]] = counts.get(parts[0], 0) + 1
    if not counts:
        return "No TCP sockets."

    lines = [f"{state}: {count}" for state, count in sorted(counts.items(), key=lambda i: -i[1])]
    return "\n".join(lines) + (
        f"\n\nTotal: {sum(counts.values())} TCP sockets. Many SYN-SENT means outbound connections are "
        "not completing, which points at a firewall or a dead path. Many TIME-WAIT is normal for a "
        "busy client and is not a fault."
    )


def _parse_proc_net_columns(output, section):
    """/proc/net/snmp and /proc/net/netstat pair a header line of names with a values line, one pair
    per section. Returns {name: int} for the requested section."""
    lines = output.splitlines()
    for index in range(0, len(lines) - 1):
        if not lines[index].startswith(f"{section}:"):
            continue
        names = lines[index].split()[1:]
        try:
            values = [int(value) for value in lines[index + 1].split()[1:]]
        except ValueError:
            continue
        if len(names) == len(values):
            return dict(zip(names, values))
    return {}


def _postprocess_tcp_snmp(output, entry, arg):
    stats = _parse_proc_net_columns(output, "Tcp")
    if not stats:
        return "TCP statistics could not be read from /proc/net/snmp."

    out_segs = stats.get("OutSegs", 0)
    retrans = stats.get("RetransSegs", 0)
    rate = (retrans / out_segs * 100) if out_segs else 0.0

    lines = [
        f"Segments sent:          {out_segs}",
        f"Segments retransmitted: {retrans}",
        f"Retransmission rate:    {rate:.2f}%",
        f"Failed connections:     {stats.get('AttemptFails', 0)}",
        f"Connections reset:      {stats.get('EstabResets', 0)}",
        f"Active opens:           {stats.get('ActiveOpens', 0)}",
    ]
    if rate < 0.5:
        reading = "Under about 0.5% is normal and indicates a healthy path."
    elif rate < 2:
        reading = "Between 0.5% and 2% is mild loss, usually noticeable only on large transfers."
    else:
        reading = (
            "Above about 2% is significant loss and will be felt as slowness on every connection."
        )
    return "\n".join(lines) + (
        f"\n\n{reading} These counters are cumulative since boot, so the rate is a long-run average "
        "and a recent problem will be diluted by earlier healthy traffic."
    )


def _postprocess_listen_drops(output, entry, arg):
    stats = _parse_proc_net_columns(output, "TcpExt")
    if not stats:
        return "Extended TCP statistics could not be read from /proc/net/netstat."

    interesting = {
        "ListenOverflows": "connections dropped because the accept queue was full",
        "ListenDrops": "connections dropped while pending",
        "TCPSynRetrans": "SYN packets retransmitted",
        "TCPTimeouts": "connection timeouts",
        "TCPLostRetransmit": "retransmissions themselves lost",
    }
    lines = [f"{stats.get(key, 0)}  {label}" for key, label in interesting.items()]
    return "\n".join(lines) + (
        "\n\nNon-zero listen overflows mean a service could not accept connections fast enough, which "
        "is a load problem on this machine rather than a network one. Counters are cumulative since "
        "boot."
    )


_POSTPROCESSORS = {
    "top_lines": _postprocess_top_lines,
    "count_lines": _postprocess_count_lines,
    "only_port": _postprocess_only_port,
    "mtu_only": _postprocess_mtu_only,
    "tcp_states": _postprocess_tcp_states,
    "tcp_snmp": _postprocess_tcp_snmp,
    "listen_drops": _postprocess_listen_drops,
}

_PERMISSION_MARKERS = ("permission denied", "must be root", "operation not permitted", "are you root")


def execute_network_command(command_id, arg=None):
    """Runs the allow-listed observation for command_id and returns its output as text. Never raises:
    an unknown id, a bad argument, a missing binary, a permission problem or a timeout all return a
    short explanatory string, so the caller always has something to reason about."""
    entry = NETWORK_COMMANDS.get(command_id)
    if entry is None:
        return f"Error: unknown command '{command_id}'. Valid commands: {', '.join(NETWORK_COMMANDS)}."

    resolved_arg = None
    if entry.arg_mode != "none":
        if arg:
            resolved_arg, error = validate_arg(arg, entry.arg_kind)
            if error:
                return f"Error: {error}"
        elif entry.arg_mode == "required":
            hint = {
                "iface": (
                    "an interface name. Run interfaces or link_status first to see the real ones"
                ),
                "host": "a hostname or IP address, such as example.com or 1.1.1.1",
                "port": "a port number, such as 443",
            }[entry.arg_kind]
            return f"{entry.label} needs {hint}, then call this again with that value as the argument."

    if entry.kind == "python":
        try:
            return _PYTHON_HANDLERS[entry.handler](resolved_arg)
        except Exception as e:  # a computed view must not be able to take the turn down
            logger.exception(f"{entry.label} failed")
            return f"Error computing {entry.label.lower()}: {e}"

    if entry.kind == "file":
        try:
            output = Path(entry.file_path).read_text().strip()
        except FileNotFoundError:
            return f"{entry.file_path} does not exist on this system."
        except PermissionError:
            return f"Reading {entry.file_path} requires elevated permissions."
        except OSError as e:
            return f"Error reading {entry.file_path}: {e}"

        if not output:
            return f"{entry.file_path} is empty."
        if entry.postprocess:
            output = _POSTPROCESSORS[entry.postprocess](output, entry, resolved_arg)
        return output[:MAX_OUTPUT_CHARS]

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
        # ping and mtu_probe exit non-zero when the host does not answer, which is the answer rather
        # than a failure - the output already says how many packets were lost.
        if stdout and command_id in ("ping_host", "mtu_probe"):
            return stdout[:MAX_OUTPUT_CHARS]
        if not stdout:
            return f"{entry.label} failed: {stderr or f'exit code {result.returncode}'}"

    if entry.postprocess and stdout:
        stdout = _POSTPROCESSORS[entry.postprocess](stdout, entry, resolved_arg)

    if not stdout:
        return f"{entry.label} returned no output."

    return stdout[:MAX_OUTPUT_CHARS]
