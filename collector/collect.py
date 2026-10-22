"""Host port inventory: Docker's published bindings plus host listening sockets.

The collector deliberately has no HTTP server. It periodically writes an atomic
JSON snapshot to a shared volume consumed by an unprivileged, read-only web app.
"""

import http.client
import json
import os
from pathlib import Path
import re
import socket
import subprocess
import tempfile
import time
from datetime import datetime, timezone
from urllib.parse import quote


DOCKER_SOCKET = "/var/run/docker.sock"
SNAPSHOT_PATH = Path("/data/snapshot.json")
PROCESS_RE = re.compile(r'"([^"\\]+)",pid=(\d+)')


class UnixHTTPConnection(http.client.HTTPConnection):
    def __init__(self, socket_path=DOCKER_SOCKET, timeout=4):
        super().__init__("localhost", timeout=timeout)
        self.socket_path = socket_path

    def connect(self):
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.settimeout(self.timeout)
        self.sock.connect(self.socket_path)


def docker_get(path):
    connection = UnixHTTPConnection()
    try:
        connection.request("GET", path, headers={"Host": "docker"})
        response = connection.getresponse()
        payload = response.read()
        if response.status != 200:
            raise RuntimeError(f"Docker API HTTP {response.status}")
        return json.loads(payload)
    finally:
        connection.close()


def port_scope(address):
    if address in ("127.0.0.1", "::1"):
        return "local"
    if address in ("0.0.0.0", "::", "*"):
        return "all"
    return "specific"


def normalize_address(address):
    address = (address or "0.0.0.0").strip()
    if address.startswith("[") and address.endswith("]"):
        address = address[1:-1]
    return address


def docker_bindings(container, detail):
    """Return only *published host ports*, not merely EXPOSEd container ports."""
    net = detail.get("NetworkSettings") or {}
    ports = net.get("Ports")
    if ports is None:
        # Docker's list endpoint can be used if inspect is temporarily absent.
        for mapping in container.get("Ports", []):
            if not isinstance(mapping, dict) or "PublicPort" not in mapping:
                continue
            yield {
                "address": normalize_address(mapping.get("IP")),
                "port": mapping["PublicPort"],
                "protocol": mapping.get("Type", "tcp"),
                "target_port": mapping.get("PrivatePort"),
            }
        return

    for internal, bindings in ports.items():
        if not bindings:
            continue
        try:
            target, protocol = internal.rsplit("/", 1)
            target = int(target)
        except (ValueError, AttributeError):
            continue
        for binding in bindings:
            if not binding or not binding.get("HostPort"):
                continue
            yield {
                "address": normalize_address(binding.get("HostIp")),
                "port": binding["HostPort"],
                "protocol": protocol,
                "target_port": target,
            }


def collect_docker():
    containers = docker_get("/containers/json?all=1")
    published = []
    services = []
    warnings = []
    for summary in containers:
        container_id = summary.get("Id", "")
        name = (summary.get("Names") or [container_id[:12]])[0].lstrip("/")
        try:
            detail = docker_get("/containers/" + quote(container_id, safe="") + "/json")
        except Exception as exc:
            detail = {}
            warnings.append(f"Inspección incompleta de {name}: {exc}")

        config = detail.get("Config") or {}
        labels = config.get("Labels") or summary.get("Labels") or {}
        state = detail.get("State") or {}
        status = state.get("Status") or summary.get("State") or "unknown"
        network_mode = (detail.get("HostConfig") or {}).get("NetworkMode", "")
        image = config.get("Image") or summary.get("Image") or ""
        project = labels.get("com.docker.compose.project", "")
        service = labels.get("com.docker.compose.service", "")
        mappings = list(docker_bindings(summary, detail)) if status == "running" else []
        services.append({
            "id": container_id[:12], "name": name, "image": image,
            "status": status, "project": project, "compose_service": service,
            "network_mode": network_mode, "published_count": len(mappings),
        })

        for mapping in mappings:
            try:
                port = int(mapping["port"])
            except (TypeError, ValueError):
                continue
            protocol = str(mapping["protocol"]).lower()
            if port < 1 or port > 65535 or protocol not in ("tcp", "udp", "sctp"):
                continue
            published.append({
                "id": f"docker:{container_id[:12]}:{mapping['address']}:{port}:{protocol}:{mapping['target_port']}",
                "port": port, "protocol": protocol, "address": mapping["address"],
                "scope": port_scope(mapping["address"]), "owner_type": "docker",
                "service": name, "target_port": mapping["target_port"],
                "container_id": container_id[:12], "image": image,
                "project": project, "compose_service": service,
                "process": None, "pid": None,
            })

    return published, services, warnings


def split_local_endpoint(endpoint):
    # ss uses IPv4, [IPv6] and occasionally interface-qualified addresses.
    if ":" not in endpoint:
        raise ValueError("No port in local endpoint")
    address, port_string = endpoint.rsplit(":", 1)
    port = int(port_string)
    if not (1 <= port <= 65535):
        raise ValueError("Invalid listening port")
    return normalize_address(address), port


def parse_ss(output):
    found = []
    for line in output.splitlines():
        columns = line.split(None, 6)
        if len(columns) < 5:
            continue
        protocol = columns[0].lower()
        if protocol not in ("tcp", "udp"):
            continue
        if protocol == "tcp" and columns[1].upper() != "LISTEN":
            continue
        try:
            address, port = split_local_endpoint(columns[4])
        except (ValueError, IndexError):
            continue

        process_field = columns[6] if len(columns) > 6 else ""
        matches = PROCESS_RE.findall(process_field)
        name = matches[0][0] if matches else ""
        pid = int(matches[0][1]) if matches else None
        found.append({
            "id": f"host:{address}:{port}:{protocol}:{pid or 0}",
            "port": port, "protocol": protocol, "address": address,
            "scope": port_scope(address), "owner_type": "host",
            "service": name or "Proceso no identificado", "target_port": None,
            "container_id": None, "image": None, "project": None,
            "compose_service": None, "process": name or None, "pid": pid,
        })
    return found


def collect_host():
    result = subprocess.run(
        ["ss", "-H", "-lntup"], capture_output=True, text=True,
        check=True, timeout=8,
    )
    return parse_ss(result.stdout)


def merge_ports(published, host):
    """Hide an exact Docker-proxy duplicate, not independent host services."""
    published_keys = {
        (record["address"], record["port"], record["protocol"])
        for record in published
    }
    combined = list(published)
    for record in host:
        key = (record["address"], record["port"], record["protocol"])
        if key in published_keys and record.get("process") == "docker-proxy":
            continue
        combined.append(record)
    return sorted(
        combined,
        key=lambda item: (item["port"], item["protocol"], item["address"], item["owner_type"]),
    )


def collect_snapshot():
    errors = []
    warnings = []
    published, containers, host = [], [], []
    docker_ok = ss_ok = False
    try:
        published, containers, warnings = collect_docker()
        docker_ok = True
    except Exception as exc:
        errors.append(f"No se pudo consultar Docker: {exc}")
    try:
        host = collect_host()
        ss_ok = True
    except Exception as exc:
        errors.append(f"No se pudo ejecutar ss: {exc}")

    ports = merge_ports(published, host)
    try:
        hostname = Path("/host/etc/hostname").read_text(encoding="utf-8").strip()
    except OSError:
        hostname = socket.gethostname()
    return {
        "ready": True,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "hostname": hostname,
        "sources": {"docker": docker_ok, "linux": ss_ok},
        "ports": ports,
        "containers": sorted(containers, key=lambda item: item["name"].casefold()),
        "counts": {
            "bindings": len(ports),
            "unique_ports": len({(p["protocol"], p["port"]) for p in ports}),
            "docker_bindings": len(published),
            "host_sockets": len(host),
            "containers_running": sum(c["status"] == "running" for c in containers),
            "containers_total": len(containers),
        },
        "errors": errors,
        "warnings": warnings,
    }


def write_snapshot(data, destination=SNAPSHOT_PATH):
    destination.parent.mkdir(parents=True, exist_ok=True)
    handle, temp_path = tempfile.mkstemp(prefix=".snapshot-", dir=destination.parent)
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as output:
            json.dump(data, output, ensure_ascii=False, separators=(",", ":"))
            output.flush()
            os.fsync(output.fileno())
        os.chmod(temp_path, 0o644)
        os.replace(temp_path, destination)
    finally:
        if os.path.exists(temp_path):
            os.unlink(temp_path)


def main():
    try:
        interval = max(2, min(60, int(os.getenv("INTERVAL_SECONDS", "5"))))
    except ValueError:
        interval = 5
    print(f"Port Manager collector running (interval={interval}s)", flush=True)
    while True:
        try:
            snapshot = collect_snapshot()
            write_snapshot(snapshot)
            if snapshot["errors"]:
                print(" | ".join(snapshot["errors"]), flush=True)
        except Exception as exc:
            print(f"Collector error: {exc}", flush=True)
        time.sleep(interval)


if __name__ == "__main__":
    main()
