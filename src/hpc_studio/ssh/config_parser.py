"""OpenSSH configuration file parser and host entry models.

Provides robust parsing of ~/.ssh/config files, supporting Host matching,
wildcards, directive inheritance, first-match-wins resolution, ProxyJump,
and identity files.
"""

from __future__ import annotations

import fnmatch
import logging
import os
import shlex
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

logger = logging.getLogger(__name__)


@dataclass
class SSHHostEntry:
    """Represents a resolved or configured SSH host destination."""

    host: str
    hostname: str = ""
    user: Optional[str] = None
    port: int = 22
    identity_file: Optional[str] = None
    identity_files: List[str] = field(default_factory=list)
    proxy_jump: Optional[str] = None
    proxy_command: Optional[str] = None
    forward_agent: bool = False
    extra_options: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.hostname:
            self.hostname = self.host

        # Validate port range (1-65535)
        try:
            port_num = int(self.port)
            if not (1 <= port_num <= 65535):
                logger.warning("Port %d out of valid range (1-65535) for %s; resetting to 22.", port_num, self.host)
                self.port = 22
            else:
                self.port = port_num
        except (ValueError, TypeError):
            self.port = 22

        # Validate hostname against control characters and null bytes
        if any(c in str(self.hostname) for c in "\x00\r\n"):
            raise ValueError(f"Invalid control characters in hostname: {self.hostname!r}")

        # Synchronize identity_file (string of primary key) and identity_files (list of all keys)
        if isinstance(self.identity_file, list):
            self.identity_files = list(self.identity_file)
            self.identity_file = self.identity_files[0] if self.identity_files else None
        elif self.identity_file and not self.identity_files:
            self.identity_files = [self.identity_file]
        elif self.identity_files and not self.identity_file:
            self.identity_file = self.identity_files[0]


    @property
    def name(self) -> str:
        """Alias for host."""
        return self.host

    @property
    def options(self) -> Dict[str, Any]:
        """Alias for extra_options."""
        return self.extra_options

    @property
    def display_name(self) -> str:
        """Formatted display title for UI selector."""
        if self.hostname and self.hostname != self.host:
            return f"{self.host} ({self.hostname})"
        return self.host

    @property
    def connection_summary(self) -> str:
        """Single line summary: user@hostname:port."""
        user_str = f"{self.user}@" if self.user else ""
        return f"{user_str}{self.hostname or self.host}:{self.port}"

    def to_dict(self) -> Dict[str, Any]:
        """Convert entry to dictionary representation."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> SSHHostEntry:
        """Construct entry from dictionary data."""
        return cls(
            host=data.get("host", data.get("name", "")),
            hostname=data.get("hostname", data.get("host", "")),
            user=data.get("user"),
            port=int(data.get("port", 22)),
            identity_file=data.get("identity_file"),
            identity_files=list(data.get("identity_files", [data.get("identity_file")] if data.get("identity_file") else [])),
            proxy_jump=data.get("proxy_jump"),
            proxy_command=data.get("proxy_command"),
            forward_agent=bool(data.get("forward_agent", False)),
            extra_options=dict(data.get("extra_options", data.get("options", {}))),
        )


# Backward-compatible alias
SSHHostConfig = SSHHostEntry


def _pattern_matches(alias: str, pattern_str: str) -> bool:
    """Test if a given host alias matches an OpenSSH pattern specification.

    Handles space-separated patterns, wildcards (*, ?), and negation (!).
    OpenSSH rule:
    - If any negated pattern matches, the rule does NOT match.
    - If at least one positive pattern matches, the rule matches.
    """
    try:
        patterns = shlex.split(pattern_str)
    except ValueError:
        patterns = pattern_str.strip().split()
    if not patterns:
        return False

    negated_patterns = [p[1:] for p in patterns if p.startswith("!")]
    positive_patterns = [p for p in patterns if not p.startswith("!")]

    # Check negations first
    for neg_pat in negated_patterns:
        if fnmatch.fnmatchcase(alias, neg_pat):
            return False

    # Check positive patterns
    if not positive_patterns:
        return True

    for pos_pat in positive_patterns:
        if fnmatch.fnmatchcase(alias, pos_pat):
            return True

    return False


class SSHConfigParser:
    """Parser and resolver for OpenSSH client configuration files (~/.ssh/config).

    Follows OpenSSH specification rules:
    - Case-insensitive configuration directive names.
    - Delimiters can be whitespace or '='.
    - First-match-wins rule for single parameters across matching blocks.
    - Accumulation of IdentityFile entries.
    - Merging of default Host * directives.
    - Safe handling of non-existent files.
    """

    def __init__(self, config_path: Optional[Union[str, Path]] = None) -> None:
        self.config_path: Path = (
            Path(config_path).expanduser().resolve()
            if config_path
            else (Path.home() / ".ssh" / "config").resolve()
        )
        self._sections: List[Tuple[str, Dict[str, List[str]]]] = []
        self._explicit_hosts: List[str] = []
        self._loaded: bool = False

        if config_path is not None or self.config_path.exists():
            self.load()

    @property
    def is_loaded(self) -> bool:
        """Whether a configuration has been parsed."""
        return self._loaded

    def load(self, path: Optional[Union[str, Path]] = None) -> List[SSHHostEntry]:
        """Load and parse SSH configuration from disk."""
        target_path = Path(path).expanduser().resolve() if path else self.config_path
        self.config_path = target_path

        if not target_path.exists():
            logger.info("SSH config file does not exist: %s. Using empty configuration.", target_path)
            self._sections = []
            self._explicit_hosts = []
            self._loaded = True
            return []

        try:
            content = target_path.read_text(encoding="utf-8")
            return self.parse_text(content)
        except Exception as exc:
            logger.warning("Error reading SSH config file %s: %s", target_path, exc)
            self._sections = []
            self._explicit_hosts = []
            self._loaded = True
            return []

    def parse_text(self, text: str) -> List[SSHHostEntry]:
        """Parse configuration text content."""
        self._sections = []
        self._explicit_hosts = []

        current_patterns: Optional[str] = None
        current_directives: Dict[str, List[str]] = {}

        lines = text.splitlines()
        for raw_line in lines:
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue

            normalized = line
            if "=" in line:
                parts = line.split("=", 1)
                first_word = parts[0].strip()
                if " " not in first_word and "\t" not in first_word:
                    normalized = f"{first_word} {parts[1].strip()}"

            try:
                tokens = shlex.split(normalized, comments=True)
            except ValueError:
                tokens = normalized.split()

            if not tokens:
                continue

            key = tokens[0].lower()
            val = " ".join(tokens[1:]) if len(tokens) > 1 else ""

            if key == "host":
                if current_patterns is not None:
                    self._sections.append((current_patterns, current_directives))

                current_patterns = val
                current_directives = {}

                host_tokens = tokens[1:] if len(tokens) > 1 else val.split()
                for part in host_tokens:
                    if not part.startswith("!") and "*" not in part and "?" not in part:
                        if part not in self._explicit_hosts:
                            self._explicit_hosts.append(part)

            elif key == "match":
                if current_patterns is not None:
                    self._sections.append((current_patterns, current_directives))
                current_patterns = f"match_{val}"
                current_directives = {}

            else:
                if current_patterns is None:
                    current_patterns = "*"
                    current_directives = {}

                if key not in current_directives:
                    current_directives[key] = []
                current_directives[key].append(val)

        if current_patterns is not None:
            self._sections.append((current_patterns, current_directives))

        self._loaded = True
        return self.get_all_entries()

    def list_hosts(self) -> List[str]:
        """Return a list of all explicit host aliases defined in the configuration."""
        return list(self._explicit_hosts)

    def get_hosts(self) -> List[str]:
        """Backward compatible alias for list_hosts."""
        return self.list_hosts()

    def has_host(self, alias: str) -> bool:
        """Check if an explicit host alias is configured."""
        return alias in self._explicit_hosts

    def get_host(self, alias: str) -> Optional[SSHHostEntry]:
        """Resolve and return consolidated SSHHostEntry for the given host alias.

        Applies OpenSSH first-match-wins rule for single parameters and
        accumulates identity files. Returns None if no section matches.
        """
        if not self._sections:
            return None

        matched_any = False
        resolved_hostname: Optional[str] = None
        resolved_user: Optional[str] = None
        resolved_port: Optional[int] = None
        resolved_proxy_jump: Optional[str] = None
        resolved_proxy_command: Optional[str] = None
        resolved_forward_agent: Optional[bool] = None
        identity_files: List[str] = []
        extra_options: Dict[str, Any] = {}

        for pattern_str, directives in self._sections:
            if not _pattern_matches(alias, pattern_str):
                continue

            matched_any = True

            if "hostname" in directives and resolved_hostname is None:
                val = directives["hostname"][0]
                resolved_hostname = val.replace("%h", alias)

            if "user" in directives and resolved_user is None:
                resolved_user = directives["user"][0]

            if "port" in directives and resolved_port is None:
                try:
                    p_val = int(directives["port"][0])
                    if 1 <= p_val <= 65535:
                        resolved_port = p_val
                    else:
                        logger.warning("Configured port %d out of valid range, defaulting to 22.", p_val)
                        resolved_port = 22
                except ValueError:
                    resolved_port = 22

            if "proxyjump" in directives and resolved_proxy_jump is None:
                pj_val = directives["proxyjump"][0]
                if pj_val.lower() != "none":
                    resolved_proxy_jump = pj_val

            if "proxycommand" in directives and resolved_proxy_command is None:
                pc_val = directives["proxycommand"][0]
                if pc_val.lower() != "none":
                    # Token substitution with injection protection
                    target_h = resolved_hostname or alias
                    target_p = str(resolved_port if resolved_port is not None else 22)
                    target_u = resolved_user or ""

                    # Sanitize arguments using shlex.quote unconditionally
                    safe_h = shlex.quote(target_h)
                    safe_u = shlex.quote(target_u)

                    pc_expanded = pc_val.replace("%h", safe_h).replace("%p", target_p).replace("%r", safe_u)
                    resolved_proxy_command = pc_expanded

            if "forwardagent" in directives and resolved_forward_agent is None:
                fa_val = directives["forwardagent"][0].lower()
                resolved_forward_agent = fa_val in ("yes", "true", "1")

            if "identityfile" in directives:
                ssh_dir = (Path.home() / ".ssh").resolve()
                for id_path in directives["identityfile"]:
                    clean_id = id_path.strip("\"'")
                    if not clean_id or "\x00" in clean_id:
                        continue
                    if clean_id.startswith("~"):
                        expanded_path = Path(clean_id).expanduser().resolve()
                    elif clean_id.startswith("/"):
                        expanded_path = Path(clean_id).resolve()
                    else:
                        # OpenSSH resolves relative IdentityFile relative to ~/.ssh/
                        candidate = (ssh_dir / clean_id).resolve()
                        try:
                            candidate.relative_to(ssh_dir)
                            expanded_path = candidate
                        except ValueError:
                            logger.warning("Rejecting relative IdentityFile path traversal outside ~/.ssh: %s", clean_id)
                            continue

                    expanded = str(expanded_path)
                    if expanded not in identity_files:
                        identity_files.append(expanded)


            for k, vals in directives.items():
                if k not in (
                    "hostname",
                    "user",
                    "port",
                    "proxyjump",
                    "proxycommand",
                    "forwardagent",
                    "identityfile",
                ):
                    if k not in extra_options and vals:
                        extra_options[k] = vals[0]

        if not matched_any:
            return None

        final_hostname = resolved_hostname or alias
        final_port = resolved_port if resolved_port is not None else 22
        final_forward_agent = resolved_forward_agent if resolved_forward_agent is not None else False
        primary_identity = identity_files[0] if identity_files else None

        return SSHHostEntry(
            host=alias,
            hostname=final_hostname,
            user=resolved_user,
            port=final_port,
            identity_file=primary_identity,
            identity_files=identity_files,
            proxy_jump=resolved_proxy_jump,
            proxy_command=resolved_proxy_command,
            forward_agent=final_forward_agent,
            extra_options=extra_options,
        )

    def get_host_configs(self) -> Dict[str, SSHHostEntry]:
        """Return dictionary of {host_name: SSHHostEntry}."""
        res: Dict[str, SSHHostEntry] = {}
        for h in self.list_hosts():
            entry = self.get_host(h)
            if entry is not None:
                res[h] = entry
        return res

    def get_all_entries(self) -> List[SSHHostEntry]:
        """Return resolved entries for all explicitly configured hosts."""
        entries: List[SSHHostEntry] = []
        for alias in self.list_hosts():
            entry = self.get_host(alias)
            if entry is not None:
                entries.append(entry)
        return entries
