"""Unit tests for OpenSSH configuration parser and host entry models.

Verifies specification compliance for ~/.ssh/config:
- Host alias resolution and explicit listing
- Wildcard pattern matching (*, ?) and pattern negation (!)
- OpenSSH first-match-wins rule
- Default Host * directive inheritance
- IdentityFile accumulation and ~ expansion
- ProxyJump and custom options
- Equal sign delimiters and quoted tokens
- Serialization to/from dictionary
"""

import os
from pathlib import Path
import pytest

from hpc_studio.ssh.config_parser import SSHConfigParser, SSHHostEntry, _pattern_matches


class TestSSHPatternMatching:
    """Tests for OpenSSH pattern matching rules."""

    def test_exact_match(self):
        assert _pattern_matches("marenostrum", "marenostrum")
        assert not _pattern_matches("marenostrum", "finisterrae")

    def test_space_separated_patterns(self):
        patterns = "cluster1 cluster2 mn5"
        assert _pattern_matches("cluster1", patterns)
        assert _pattern_matches("cluster2", patterns)
        assert _pattern_matches("mn5", patterns)
        assert not _pattern_matches("other", patterns)

    def test_wildcards(self):
        assert _pattern_matches("node01.cluster", "*.cluster")
        assert _pattern_matches("node99.cluster", "node??.cluster")
        assert not _pattern_matches("node1.cluster", "node??.cluster")
        assert _pattern_matches("anything", "*")

    def test_negation(self):
        patterns = "*.hpc.org !bad.hpc.org"
        assert _pattern_matches("node1.hpc.org", patterns)
        assert not _pattern_matches("bad.hpc.org", patterns)
        assert not _pattern_matches("other.com", patterns)


class TestSSHConfigParser:
    """Tests for SSHConfigParser functionality."""

    def test_empty_config_and_missing_file(self, tmp_path):
        missing = tmp_path / "non_existent_config"
        parser = SSHConfigParser(missing)
        assert parser.list_hosts() == []
        assert not parser.has_host("anyhost")

        # Resolving unknown host in empty/missing config returns None
        entry = parser.get_host("unknown_node")
        assert entry is None

    def test_basic_host_entry(self):
        content = """
        Host mycluster
            HostName 192.168.1.100
            User hpcadmin
            Port 2222
            ForwardAgent yes
        """
        parser = SSHConfigParser()
        parser.parse_text(content)

        assert parser.list_hosts() == ["mycluster"]
        assert parser.has_host("mycluster")

        entry = parser.get_host("mycluster")
        assert entry.host == "mycluster"
        assert entry.hostname == "192.168.1.100"
        assert entry.user == "hpcadmin"
        assert entry.port == 2222
        assert entry.forward_agent is True
        assert entry.display_name == "mycluster (192.168.1.100)"
        assert entry.connection_summary == "hpcadmin@192.168.1.100:2222"

    def test_multiple_aliases_on_single_host_line(self):
        content = """
        Host mn5 marenostrum5 bsc-cluster
            HostName mn5.bsc.es
            User researcher
            Port 22
        """
        parser = SSHConfigParser()
        parser.parse_text(content)

        assert parser.list_hosts() == ["mn5", "marenostrum5", "bsc-cluster"]

        for alias in ("mn5", "marenostrum5", "bsc-cluster"):
            entry = parser.get_host(alias)
            assert entry.hostname == "mn5.bsc.es"
            assert entry.user == "researcher"
            assert entry.port == 22

    def test_wildcards_and_default_inheritance(self):
        content = """
        Host login1.lab.org
            HostName 10.10.1.1
            Port 2222

        Host login*.lab.org
            User labuser
            Port 2200

        Host *
            User defaultuser
            Port 22
            ForwardAgent yes
            ServerAliveInterval 60
        """
        parser = SSHConfigParser()
        parser.parse_text(content)

        # list_hosts must NOT include '*' or patterns containing '*'
        assert parser.list_hosts() == ["login1.lab.org"]

        # login1.lab.org matches login1.lab.org, login*.lab.org, and *
        # First match wins for port -> 2222 from login1.lab.org block
        # First match wins for user -> labuser from login*.lab.org block
        entry1 = parser.get_host("login1.lab.org")
        assert entry1.hostname == "10.10.1.1"
        assert entry1.port == 2222
        assert entry1.user == "labuser"
        assert entry1.forward_agent is True
        assert entry1.extra_options.get("serveraliveinterval") == "60"

        # login2.lab.org matches login*.lab.org and *
        entry2 = parser.get_host("login2.lab.org")
        assert entry2.hostname == "login2.lab.org"
        assert entry2.port == 2200
        assert entry2.user == "labuser"
        assert entry2.forward_agent is True

        # generic host only matches *
        entry3 = parser.get_host("external-server")
        assert entry3.hostname == "external-server"
        assert entry3.port == 22
        assert entry3.user == "defaultuser"
        assert entry3.forward_agent is True

    def test_first_match_wins_rule(self):
        content = """
        Host duplicate
            User first_user
            Port 1001

        Host duplicate
            User second_user
            Port 2002

        Host *
            User third_user
            Port 3003
        """
        parser = SSHConfigParser()
        parser.parse_text(content)

        entry = parser.get_host("duplicate")
        assert entry.user == "first_user"
        assert entry.port == 1001

    def test_identity_file_accumulation_and_expansion(self):
        content = """
        Host cluster
            IdentityFile ~/.ssh/id_ed25519
            IdentityFile ~/.ssh/id_rsa

        Host *
            IdentityFile ~/.ssh/id_fallback
        """
        parser = SSHConfigParser()
        parser.parse_text(content)

        entry = parser.get_host("cluster")
        home = str(Path.home())
        expected = [
            os.path.join(home, ".ssh", "id_ed25519"),
            os.path.join(home, ".ssh", "id_rsa"),
            os.path.join(home, ".ssh", "id_fallback"),
        ]
        assert entry.identity_files == expected
        assert entry.identity_file == expected[0]

    def test_proxy_jump_and_proxy_command(self):
        content = """
        Host internal-node
            HostName 10.0.0.50
            User slurmadmin
            ProxyJump bastion.hpc.org:222
        """
        parser = SSHConfigParser()
        parser.parse_text(content)

        entry = parser.get_host("internal-node")
        assert entry.proxy_jump == "bastion.hpc.org:222"
        assert entry.proxy_command is None

    def test_equals_delimiter_and_quotes(self):
        content = """
        Host = testbox
            HostName = "192.168.10.5"
            User = "custom user"
            Port = 2220
        """
        parser = SSHConfigParser()
        parser.parse_text(content)

        assert parser.list_hosts() == ["testbox"]
        entry = parser.get_host("testbox")
        assert entry.hostname == "192.168.10.5"
        assert entry.user == "custom user"
        assert entry.port == 2220

    def test_get_all_entries(self):
        content = """
        Host hpc1
            HostName 10.1.1.1
            User u1
        Host hpc2
            HostName 10.1.1.2
            User u2
        Host *
            Port 2222
        """
        parser = SSHConfigParser()
        parser.parse_text(content)

        entries = parser.get_all_entries()
        assert len(entries) == 2
        assert entries[0].host == "hpc1"
        assert entries[0].port == 2222
        assert entries[1].host == "hpc2"
        assert entries[1].port == 2222

    def test_host_entry_serialization(self):
        entry = SSHHostEntry(
            host="calc01",
            hostname="calc01.cluster.local",
            user="quantum",
            port=2222,
            identity_file=["/home/user/.ssh/id_ed25519"],
            proxy_jump="jump.cluster.local",
            forward_agent=True,
            extra_options={"ServerAliveInterval": "30"},
        )
        data = entry.to_dict()
        assert data["host"] == "calc01"
        assert data["port"] == 2222
        assert data["forward_agent"] is True

        reconstructed = SSHHostEntry.from_dict(data)
        assert reconstructed.host == entry.host
        assert reconstructed.hostname == entry.hostname
        assert reconstructed.user == entry.user
        assert reconstructed.port == entry.port
        assert reconstructed.identity_file == entry.identity_file
        assert reconstructed.proxy_jump == entry.proxy_jump
        assert reconstructed.forward_agent == entry.forward_agent
        assert reconstructed.extra_options == entry.extra_options
