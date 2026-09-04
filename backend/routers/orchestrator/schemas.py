from pydantic import BaseModel, Field


class OrchestratorRequest(BaseModel):
    provider: str
    model_id: str
    message: str = Field(min_length=1)
    # None starts a brand new session; the orchestrator creates and returns one via the
    # `session_created` event. Set to continue logging turns under an existing session.
    session_id: int | None = None
    # True when this is the same message a turn that already failed was sent with - the client's
    # retry button. The turn runs identically either way; the flag only says that the failed
    # attempt's unanswered user row is being replaced rather than added to, so a message retried
    # three times appears once in the transcript instead of four times.
    is_retry: bool = False


class CommandRun(BaseModel):
    command: str
    label: str
    path: str | None = None
    output: str


class TopConsumer(BaseModel):
    label: str
    size_gb: float | None = None


class Fact(BaseModel):
    label: str
    value: str


class Capacity(BaseModel):
    free_gb: float | None = None
    total_gb: float | None = None
    percent_used: float | None = None
    severity: str | None = None


class DiskReport(BaseModel):
    summary: str
    explanation: str | None = None
    capacity: Capacity | None = None
    facts: list[Fact] = []
    top_consumers: list[TopConsumer] = []
    suggestion: str | None = None
    # True when the model did not return a usable <disk_report> and the summary is prose recovered
    # from whatever it did say. The client keeps the trace expanded for these, since the commands
    # that ran are then more trustworthy than the answer.
    salvaged: bool = False


class AppEntry(BaseModel):
    """One application, not one process. A browser's renderer, GPU and crashpad processes are summed
    into a single entry, which is what makes "which apps are running" answerable."""

    name: str
    cpu_percent: float | None = None
    memory_mb: float | None = None
    processes: int | None = None
    uptime: str | None = None
    # foreground | background | unknown. "unknown" is required, not optional, whenever window data
    # was unavailable - claiming "background" on a Wayland session would be inventing an observation.
    state: str | None = None
    detail: str | None = None


class ProcessEntry(BaseModel):
    pid: int | None = None
    name: str
    cpu_percent: float | None = None
    memory_mb: float | None = None
    state: str | None = None


class LoadSummary(BaseModel):
    cpu_percent: float | None = None
    memory_percent: float | None = None
    load_1m: float | None = None
    cores: int | None = None
    severity: str | None = None


class ProcessReport(BaseModel):
    summary: str
    explanation: str | None = None
    # full | degraded. Mirrors what the tool reported about this session's window data, so the client
    # can state the limitation instead of quietly rendering a weaker answer as a confident one.
    confidence: str | None = None
    apps: list[AppEntry] = []
    processes: list[ProcessEntry] = []
    load: LoadSummary | None = None
    facts: list[Fact] = []
    standout: str | None = None
    suggestion: str | None = None
    salvaged: bool = False


class ConnectivityLadder(BaseModel):
    """Where connectivity broke, as a position in a chain rather than a quantity.

    Each layer is ok, fail or unknown. The pair that carries the diagnosis is dns and internet: the
    internet reachable by address while dns fails is a resolver problem, and both failing is an
    upstream one. Collapsing them into a single "online" boolean would discard the only distinction
    the user needs."""

    link: str | None = None
    address: str | None = None
    gateway: str | None = None
    dns: str | None = None
    internet: str | None = None
    failed_at: str | None = None
    # online | degraded | offline. Never stronger than the layers support - the parser enforces that,
    # since rounding a partial failure up to "online" is the claim a model is most tempted to make.
    severity: str | None = None


class NetworkInterface(BaseModel):
    name: str
    kind: str | None = None  # wifi | ethernet | loopback | tunnel | bridge | bond | virtual | unknown
    state: str | None = None  # up | down | no-carrier
    ipv4: str | None = None
    ipv6: str | None = None
    signal_dbm: float | None = None
    detail: str | None = None


class ConnectionEntry(BaseModel):
    """One application, not one socket - the network counterpart to AppEntry. A browser holding sixty
    connections is a single entry, which is what makes "what is using my network" answerable."""

    name: str
    connections: int | None = None
    listening: int | None = None
    detail: str | None = None


class ListeningPort(BaseModel):
    port: int | None = None
    protocol: str | None = None  # tcp | udp
    address: str | None = None
    process: str | None = None
    # local | all-interfaces | unknown. The security-relevant half of the row: the same port number
    # on 127.0.0.1 and on 0.0.0.0 are completely different exposures.
    exposure: str | None = None


class NetworkReport(BaseModel):
    summary: str
    explanation: str | None = None
    # full | degraded. Mirrors what the tool reported about socket attribution, so the client can
    # state the limitation instead of quietly rendering a weaker answer as a confident one.
    confidence: str | None = None
    connectivity: ConnectivityLadder | None = None
    interfaces: list[NetworkInterface] = []
    connections: list[ConnectionEntry] = []
    listening: list[ListeningPort] = []
    facts: list[Fact] = []
    standout: str | None = None
    suggestion: str | None = None
    salvaged: bool = False


class AgentResult(BaseModel):
    """One agent's slice of a turn several agents answered - its own `final` event, minus the event
    type. Exactly one of the three reports, `content` (the base agent) or `error` is set."""

    mode: str
    thinking: str | None = None
    content: str | None = None
    disk_report: DiskReport | None = None
    process_report: ProcessReport | None = None
    network_report: NetworkReport | None = None
    commands_run: list[CommandRun] = []
    # Set when this agent failed while others succeeded. One agent failing does not fail the turn, so
    # the answer has to be able to say which part of the question went unanswered.
    error: str | None = None


class OrchestratorResponse(BaseModel):
    provider: str
    model_id: str
    session_id: int | None = None
    # "disk" | "process" | "network" | "general", or "multi" when several agents answered - in which
    # case the reports are in `agents` rather than in the fields below.
    mode: str
    # Every agent that ran, in order. A single-agent turn carries its one mode here too, so a client
    # can read this field alone rather than special-casing the two shapes.
    modes: list[str] = []
    # The paragraph composed over several agents' findings. Null on a single-agent turn, and also
    # whenever composing it failed - the reports are the answer, and they stand without it.
    summary: str | None = None
    agents: list[AgentResult] = []
    thinking: str | None = None
    content: str | None = None
    raw_xml: str | None = None
    disk_report: DiskReport | None = None
    process_report: ProcessReport | None = None
    network_report: NetworkReport | None = None
    # On a multi turn this is every agent's commands, flattened in the order they ran.
    commands_run: list[CommandRun] = []
