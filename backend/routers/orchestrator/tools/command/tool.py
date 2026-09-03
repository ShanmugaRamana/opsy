"""Execution for commands the agent asked permission to run.

This is the escape hatch for questions the disk allow-list cannot answer - "which is the smallest
file", "list everything under /var" - where the agent knows the command but has no entry for it.
Nothing here runs without an explicit approval recorded in routers.orchestrator.permissions.

Two properties do the safety work:

- **No shell, ever.** The model supplies an argv list and it is passed straight to subprocess with
  shell=False, so pipes, redirects, globs and command substitution are not interpreted. A pipeline
  like `find ... | sort -n | head` has to become argv plus post-processing in Python, which is why
  the shell-adjacent binaries below are refused rather than tolerated.
- **Read-only.** The disk agent's own prompt already promises the user "you never modify, delete or
  reconfigure anything"; this list is that promise made enforceable.
"""
import logging
import os
import shutil
import subprocess

logger = logging.getLogger("tools.command")

MAX_OUTPUT_CHARS = 3000
DEFAULT_TIMEOUT = 60
MAX_TIMEOUT = 120

# Binaries that change the system, escalate, reach the network, or would let an argv become a shell
# line again. Refused even with approval, because the approval card promises a read-only look.
DENIED_BINARIES = {
    # writing and deleting
    "rm", "rmdir", "unlink", "shred", "srm", "mv", "cp", "install", "dd", "truncate", "tee", "ln",
    # filesystem and partition changes
    "mkfs", "mkswap", "fdisk", "sfdisk", "cfdisk", "gdisk", "sgdisk", "parted", "wipefs",
    "resize2fs", "tune2fs", "e2fsck", "fsck", "badblocks", "hdparm", "nvme-format",
    "mount", "umount", "swapon", "swapoff", "losetup", "cryptsetup",
    "lvcreate", "lvremove", "vgcreate", "vgremove", "pvcreate", "pvremove", "mdadm",
    # ownership and permissions
    "chmod", "chown", "chgrp", "chattr", "setfacl", "setfattr",
    # packages
    "apt", "apt-get", "aptitude", "dpkg", "yum", "dnf", "rpm", "pacman", "zypper", "emerge",
    "snap", "flatpak", "pip", "pip3", "npm", "yarn", "gem", "cargo", "go",
    # services and power
    "systemctl", "service", "initctl", "rc-service", "shutdown", "reboot", "halt", "poweroff",
    "init", "telinit", "kill", "killall", "pkill", "skill",
    # escalation and shells - a shell would put pipes and redirects back in play
    "sudo", "su", "doas", "pkexec", "sh", "bash", "zsh", "dash", "ksh", "csh", "tcsh", "fish",
    "env", "nohup", "setsid", "xargs", "exec", "eval", "python", "python3", "perl", "ruby", "node",
    "awk", "gawk", "mawk", "sed", "ed", "vi", "vim", "nano", "emacs",
    # network
    "curl", "wget", "nc", "ncat", "netcat", "ssh", "scp", "sftp", "rsync", "ftp", "telnet",
    "iptables", "nft", "ip", "ifconfig",
    # scheduling and accounts
    "crontab", "at", "batch", "useradd", "userdel", "usermod", "groupadd", "passwd", "chpasswd",
    "visudo", "chsh", "chfn",
    # misc tooling that writes
    "git", "make", "cmake", "docker", "podman", "kubectl", "systemd-run", "tar", "unzip", "zip",
}

# Options that turn an otherwise read-only binary into a writing one. `find -delete` and
# `find -exec` are the ones that matter in practice.
DENIED_OPTIONS = {
    "-delete", "-exec", "-execdir", "-ok", "-okdir",
    "-fls", "-fprint", "-fprint0", "-fprintf",
    "--delete", "--output", "--write",
}

# There is no shell, so these do nothing useful - subprocess passes argv straight to the binary, and
# a literal "|" is just a string `find` or `ls` does not understand. Refusing them here, before the
# user is even asked, turns a wasted approval round trip and a confusing find/ls syntax error into an
# immediate, actionable message the model can react to in the same turn.
SHELL_OPERATOR_TOKENS = {"|", "||", "&", "&&", ";", ";;", "<", "<<", ">", ">>", "`"}


def validate_argv(argv):
    """Returns (resolved_argv, None) or (None, error_message).

    Runs before the user is ever prompted, so Opsy does not ask permission for something it would
    refuse to run anyway."""
    if not isinstance(argv, (list, tuple)) or not argv:
        return None, "no command was given"

    tokens = [str(token) for token in argv]
    if any("\x00" in token for token in tokens):
        return None, "the command contains a null byte"
    if any(not token.strip() for token in tokens[:1]):
        return None, "the command is empty"

    for token in tokens:
        if token in SHELL_OPERATOR_TOKENS or "$(" in token or "`" in token or "\n" in token:
            return None, (
                f"'{token}' is a shell operator, but there is no shell here - argv runs directly, so "
                "pipes, redirects and command substitution do nothing. Request the raw output of one "
                "command and work with it directly, or set count_lines to true for a count instead of "
                "piping into wc"
            )

    binary = os.path.basename(tokens[0])
    if binary in DENIED_BINARIES:
        return None, (
            f"'{binary}' can change the system, escalate privileges or open a shell. Opsy only runs "
            "read-only observation commands."
        )

    for token in tokens[1:]:
        if token.lower() in DENIED_OPTIONS:
            return None, f"the option '{token}' can modify the system, so it cannot be run"

    resolved = shutil.which(tokens[0])
    if resolved is None:
        return None, f"'{tokens[0]}' is not installed on this system"

    return [resolved] + tokens[1:], None


def execute_command(argv, timeout=DEFAULT_TIMEOUT, count_lines=False):
    """Runs an already-approved argv. Never raises: every failure becomes a short explanatory string,
    so the agent always has something honest to report.

    `count_lines` is how "how many files" questions get answered without a shell: piping into
    `wc -l` is refused by validate_argv, since there is nothing here to interpret the pipe, so this
    is the counting primitive in its place. The count is taken from the complete output before
    truncation, not from whatever fits in MAX_OUTPUT_CHARS, so a large result still gets an exact
    number rather than an undercount."""
    resolved, error = validate_argv(argv)
    if error:
        return f"That command cannot be run: {error}."

    timeout = max(1, min(int(timeout or DEFAULT_TIMEOUT), MAX_TIMEOUT))
    printable = " ".join(str(token) for token in argv)

    try:
        result = subprocess.run(resolved, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return f"The command timed out after {timeout}s."
    except OSError as e:
        logger.warning(f"approved command failed ({printable}): {e}")
        return f"Error running the command: {e}"

    stdout = (result.stdout or "").strip()
    stderr = (result.stderr or "").strip()

    if result.returncode != 0 and not stdout:
        return f"The command exited with code {result.returncode}: {stderr or 'no output'}"

    if count_lines:
        count = sum(1 for line in stdout.splitlines() if line.strip())
        return f"{count} matching lines."

    if not stdout:
        return "The command produced no output."

    # A partial read is still a real answer, but the agent must not present it as complete.
    if len(stdout) > MAX_OUTPUT_CHARS:
        return f"{stdout[:MAX_OUTPUT_CHARS]}\n\n[output truncated at {MAX_OUTPUT_CHARS} characters]"
    return stdout
