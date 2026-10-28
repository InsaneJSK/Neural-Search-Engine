"""Host the on-demand demo: uv run scripts/demo_host.py (Ctrl+C to stop).

Secrets and runtime state stay in ignored .env.demo and .demo/ files.
"""
import ctypes
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import socket
import subprocess
import sys
import time
from urllib.request import Request, urlopen

from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[1]
STATE = ROOT / ".demo"
VERSION = "2026.10.5"
SHA256 = "db4e4c413612a0916f3e1679d3caaf376f94911952d163028fb726fb2e0516a9"


def config():
    path = ROOT / ".env.demo"
    if not path.exists():
        path.write_text("NSE_API_TOKEN=" + secrets.token_urlsafe(32) + "\n"
                        "NSE_DEMO_PORT=8001\n", encoding="utf-8")
    values = dict(dotenv_values(path))
    for key in ("NSE_API_TOKEN",):
        if not values.get(key):
            raise RuntimeError(f"Missing {key} in .env.demo")
    return values


def cloudflared():
    executable = STATE / "bin" / "cloudflared.exe"
    executable.parent.mkdir(parents=True, exist_ok=True)
    if not executable.exists():
        url = f"https://github.com/cloudflare/cloudflared/releases/download/{VERSION}/cloudflared-windows-amd64.exe"
        with urlopen(url, timeout=120) as response:
            payload = response.read()
        if hashlib.sha256(payload).hexdigest() != SHA256:
            raise RuntimeError("cloudflared download checksum mismatch")
        executable.write_bytes(payload)
    if hashlib.sha256(executable.read_bytes()).hexdigest() != SHA256:
        raise RuntimeError("cloudflared checksum mismatch")
    return executable


def main():
    STATE.mkdir(exist_ok=True)
    values = config()
    executable = cloudflared()
    port = int(values.get("NSE_DEMO_PORT", "8001"))
    with socket.socket() as probe:
        try:
            probe.bind(("127.0.0.1", port))
        except OSError:
            raise RuntimeError(f"Port {port} is already in use. Stop the existing demo first.") from None
    env = {**os.environ, **{k: v for k, v in values.items() if v is not None}}
    env["NSE_DEMO_EXPIRES_AT"] = ""  # Override any legacy cutoff inherited from the host.
    children = []
    flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    state_file = STATE / "host.json"
    stop_file = STATE / "stop"
    stop_file.unlink(missing_ok=True)
    logs = []
    try:
        if os.name == "nt":
            ctypes.windll.kernel32.SetThreadExecutionState(0x80000001)
        log = (STATE / "backend.log").open("w", encoding="utf-8")
        logs.append(log)
        backend = subprocess.Popen([sys.executable, "serve.py", "--port", str(port)], cwd=ROOT,
                                   env=env, stdout=log, stderr=log, creationflags=flags)
        children.append(backend)
        for _ in range(180):
            if backend.poll() is not None:
                raise RuntimeError("Backend exited; see .demo/backend.log")
            try:
                request = Request(f"http://127.0.0.1:{port}/health", headers={"Authorization": "Bearer " + values["NSE_API_TOKEN"]})
                with urlopen(request, timeout=2) as response:
                    if response.status == 200:
                        break
            except OSError:
                time.sleep(1)
        else:
            raise RuntimeError("Backend did not become ready; see .demo/backend.log")
        tunnel_log = (STATE / "tunnel.log").open("w", encoding="utf-8")
        logs.append(tunnel_log)
        tunnel = subprocess.Popen([str(executable), "tunnel", "--no-autoupdate", "--url",
                                   f"http://127.0.0.1:{port}", "--http-host-header", f"127.0.0.1:{port}"],
                                  cwd=ROOT, stdout=tunnel_log, stderr=tunnel_log, creationflags=flags)
        children.append(tunnel)
        url = None
        for _ in range(90):
            if tunnel.poll() is not None:
                raise RuntimeError("Tunnel exited; see .demo/tunnel.log")
            match = re.search(r"https://[a-z0-9-]+\.trycloudflare\.com", (STATE / "tunnel.log").read_text(errors="replace"))
            if match:
                url = match.group()
                break
            time.sleep(1)
        if not url:
            raise RuntimeError("No tunnel URL received; see .demo/tunnel.log")
        state_file.write_text(json.dumps({"url": url, "port": port, "expires_at": None,
                                         "host_pid": os.getpid(), "backend_pid": backend.pid, "tunnel_pid": tunnel.pid}, indent=2))
        print(f"Demo host ready: {url}\nRun the Vercel deployment script after each host restart.\nKeep this PC online. Ctrl+C or create .demo/stop to stop.", flush=True)
        while not stop_file.exists():
            if any(child.poll() is not None for child in children):
                raise RuntimeError("A demo process stopped; restart the launcher and redeploy.")
            time.sleep(2)
    finally:
        for child in reversed(children):
            if child.poll() is None:
                child.terminate()
                try:
                    child.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    child.kill()
                    child.wait()
        for log in logs:
            log.close()
        state_file.unlink(missing_ok=True)
        if os.name == "nt":
            ctypes.windll.kernel32.SetThreadExecutionState(0x80000000)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
