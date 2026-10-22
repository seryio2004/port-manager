"""Run with: python3 -m unittest discover -s tests -v"""

import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch


PATH = Path(__file__).parents[1] / "collector" / "collect.py"
SPEC = importlib.util.spec_from_file_location("port_manager_collector", PATH)
collector = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(collector)


class CollectorTests(unittest.TestCase):
    def test_parser_reads_tcp_udp_and_process(self):
        output = (
            'tcp LISTEN 0 128 127.0.0.1:5432 0.0.0.0:* users:(("postgres",pid=120,fd=5))\n'
            'udp UNCONN 0 0 [::]:5353 [::]:* users:(("avahi-daemon",pid=70,fd=10))\n'
            'tcp ESTAB 0 0 127.0.0.1:9000 127.0.0.1:3111 users:(("python",pid=5,fd=3))\n'
        )
        ports = collector.parse_ss(output)
        self.assertEqual(len(ports), 2)
        self.assertEqual((ports[0]["port"], ports[0]["protocol"], ports[0]["pid"]), (5432, "tcp", 120))
        self.assertEqual((ports[1]["address"], ports[1]["port"], ports[1]["protocol"]), ("::", 5353, "udp"))

    def test_docker_inspect_returns_only_host_bindings(self):
        detail = {"NetworkSettings": {"Ports": {
            "80/tcp": [{"HostIp": "0.0.0.0", "HostPort": "8080"}],
            "443/tcp": None,
            "53/udp": [{"HostIp": "127.0.0.1", "HostPort": "15353"}],
        }}}
        bindings = list(collector.docker_bindings({}, detail))
        self.assertEqual([b["port"] for b in bindings], ["8080", "15353"])
        self.assertEqual([b["target_port"] for b in bindings], [80, 53])

    def test_docker_fallback_ignores_exposed_but_unpublished(self):
        summary = {"Ports": [
            {"PrivatePort": 80, "Type": "tcp"},
            {"PrivatePort": 443, "PublicPort": 8443, "Type": "tcp", "IP": "0.0.0.0"},
        ]}
        bindings = list(collector.docker_bindings(summary, {}))
        self.assertEqual(len(bindings), 1)
        self.assertEqual(bindings[0]["port"], 8443)

    def test_merge_drops_docker_proxy_but_keeps_other_host_processes(self):
        docker = {"address": "0.0.0.0", "port": 8080, "protocol": "tcp", "owner_type": "docker"}
        proxy = {"address": "0.0.0.0", "port": 8080, "protocol": "tcp", "process": "docker-proxy", "owner_type": "host"}
        other = {"address": "127.0.0.1", "port": 8080, "protocol": "tcp", "process": "python", "owner_type": "host"}
        self.assertEqual(collector.merge_ports([docker], [proxy, other]), [docker, other])

    def test_atomic_snapshot_write(self):
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / "snapshot.json"
            collector.write_snapshot({"ready": True, "ports": []}, target)
            self.assertIn('"ready":true', target.read_text(encoding="utf-8"))

    @patch.object(collector, "collect_host", return_value=[])
    @patch.object(collector, "collect_docker", side_effect=RuntimeError("offline"))
    def test_docker_error_is_visible_and_does_not_discard_linux(self, *_):
        snapshot = collector.collect_snapshot()
        self.assertFalse(snapshot["sources"]["docker"])
        self.assertTrue(snapshot["sources"]["linux"])
        self.assertIn("offline", snapshot["errors"][0])


if __name__ == "__main__":
    unittest.main()
