#!/usr/bin/env python3
"""Localhost Start/Stop helper. nginx proxies /pitaya_tdc/control/ here."""

from __future__ import annotations

import json
import os
import signal
import socket
import subprocess
import sys
import threading
import time
import urllib.request
from http.server import BaseHTTPRequestHandler, HTTPServer
from socketserver import ThreadingMixIn

APPDIR = os.path.dirname(os.path.abspath(__file__))
CONTROL = os.path.join(APPDIR, "control.sh")
HOST = "127.0.0.1"
PORT = 12780
SD_LISTEN_FDS_START = 3
PIDFILE = "/tmp/pitaya_tdc.pid"
WANT = "/tmp/pitaya_tdc.want"

_status_lock = threading.Lock()
_status_cache = None
_status_at = 0.0


def read_status():
    global _status_cache, _status_at
    now = time.monotonic()
    if _status_cache is not None and (now - _status_at) < 0.25:
        return _status_cache
    with _status_lock:
        now = time.monotonic()
        if _status_cache is not None and (now - _status_at) < 0.25:
            return _status_cache
        pid = None
        try:
            with open(PIDFILE, "r") as f:
                text = "".join(c for c in f.read() if c.isdigit())
                if text:
                    pid = int(text)
        except Exception:
            pid = None
        alive = False
        if pid and pid > 1:
            try:
                os.kill(pid, 0)
                alive = True
            except OSError:
                alive = False
        health = None
        http_ok = False
        try:
            with urllib.request.urlopen("http://127.0.0.1:8080/api/health", timeout=0.2) as resp:
                health = json.loads(resp.read().decode("utf-8"))
                http_ok = True
        except Exception:
            pass
        ident = str((health or {}).get("id") or "")
        running = bool(http_ok and health and health.get("ok") and ident in ("TDC1", "0x54444331"))
        want = os.path.isfile(WANT)
        if running:
            state = "running"
        elif want:
            state = "starting"
        else:
            state = "stopped"
        out = {
            "state": state,
            "pid": pid if alive else None,
            "http": http_ok,
            "fpga_id": ident or None,
            "want": want,
        }
        if health:
            out["health"] = {"ok": bool(health.get("ok")), "id": health.get("id")}
        _status_cache = out
        _status_at = time.monotonic()
        return out


def invalidate_status():
    global _status_cache, _status_at
    with _status_lock:
        _status_cache = None
        _status_at = 0.0


def read_pid():
    try:
        with open(PIDFILE, "r") as f:
            text = "".join(c for c in f.read() if c.isdigit())
            if text:
                return int(text)
    except Exception:
        return None
    return None


def pid_alive(pid):
    if not pid or pid < 2:
        return False
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


_start_lock = threading.Lock()
_start_proc = None


def do_start():
    """Kick control.sh start in the background so the HTTP request returns."""
    global _start_proc
    st = read_status()
    if st.get("state") == "running":
        return st
    try:
        open(WANT, "a").close()
    except OSError as exc:
        return {"state": "error", "error": str(exc)}
    invalidate_status()
    subprocess.call(
        ["pkill", "-f", "/opt/redpitaya/www/apps/pitaya_tdc/restore_fpga.sh"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    with _start_lock:
        if _start_proc is not None and _start_proc.poll() is None:
            st = read_status()
            st["state"] = "starting"
            return st
        log = open("/tmp/pitaya_tdc.log", "a")
        _start_proc = subprocess.Popen(
            ["/bin/sh", CONTROL, "start"],
            cwd=APPDIR,
            stdout=log,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        log.close()
    return {"state": "starting", "want": True}


def do_stop():
    """Kill the poll server immediately. Restore v0.94 in the background."""
    global _start_proc
    had_want = os.path.isfile(WANT)
    pid = read_pid()
    had_pid = pid_alive(pid)
    had_http = False
    try:
        with urllib.request.urlopen("http://127.0.0.1:8080/api/health", timeout=0.2) as resp:
            health = json.loads(resp.read().decode("utf-8"))
            ident = str(health.get("id") or "")
            had_http = bool(health.get("ok") and ident in ("TDC1", "0x54444331"))
    except Exception:
        pass
    try:
        os.remove(WANT)
    except OSError:
        pass
    if pid_alive(pid):
        try:
            os.kill(pid, signal.SIGTERM)
        except OSError:
            pass
        for _ in range(10):
            if not pid_alive(pid):
                break
            time.sleep(0.05)
        if pid_alive(pid):
            try:
                os.kill(pid, signal.SIGKILL)
            except OSError:
                pass
    try:
        os.remove(PIDFILE)
    except OSError:
        pass
    subprocess.call(
        ["pkill", "-f", "/opt/redpitaya/www/apps/pitaya_tdc/tdc_server.py"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    with _start_lock:
        proc = _start_proc
        _start_proc = None
    if proc is not None and proc.poll() is None:
        try:
            os.killpg(proc.pid, signal.SIGTERM)
        except OSError:
            try:
                proc.terminate()
            except OSError:
                pass
    if not had_http:
        invalidate_status()
        return read_status()
    log = open("/tmp/pitaya_tdc_restore.log", "a")
    subprocess.Popen(
        ["/bin/sh", os.path.join(APPDIR, "restore_fpga.sh")],
        stdout=log,
        stderr=subprocess.STDOUT,
        start_new_session=True,
    )
    log.close()
    invalidate_status()
    return read_status()


def inherited_listen_socket():
    try:
        n = int(os.environ.get("LISTEN_FDS", "0"))
    except ValueError:
        return None
    if n < 1:
        return None
    sock = socket.fromfd(SD_LISTEN_FDS_START, socket.AF_INET, socket.SOCK_STREAM)
    sock.setblocking(True)
    return sock


class ControlHTTPServer(ThreadingMixIn, HTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, server_address, handler):
        inherited = inherited_listen_socket()
        HTTPServer.__init__(self, server_address, handler, bind_and_activate=False)
        if inherited is not None:
            try:
                self.socket.close()
            except OSError:
                pass
            self.socket = inherited
            try:
                self.server_address = self.socket.getsockname()
            except OSError:
                self.server_address = server_address
            self.server_activate()
        else:
            self.server_bind()
            self.server_activate()


class Handler(BaseHTTPRequestHandler):
    server_version = "PitayaTdcControl/1.0"
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):
        sys.stderr.write("tdc_control: " + (fmt % args) + "\n")

    def _send(self, code, payload):
        raw = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Connection", "close")
        self.end_headers()
        try:
            self.wfile.write(raw)
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass

    def _run(self, cmd):
        try:
            proc = subprocess.run(
                ["/bin/sh", CONTROL, cmd],
                cwd=APPDIR,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                universal_newlines=True,
                timeout=90,
            )
        except subprocess.TimeoutExpired:
            self._send(504, {"state": "error", "error": "%s timed out" % cmd})
            return
        except OSError as exc:
            self._send(500, {"state": "error", "error": str(exc)})
            return
        invalidate_status()
        body = (proc.stdout or "").strip() or (proc.stderr or "").strip()
        try:
            payload = json.loads(body) if body else {"state": "error", "error": "empty response"}
        except ValueError:
            payload = {"state": "error", "error": body or ("control.sh exit %d" % proc.returncode)}
        code = 200
        if proc.returncode != 0 or payload.get("state") == "error":
            code = 500 if cmd != "status" else 200
        self._send(code, payload)

    def _route(self, method):
        path = (self.path.split("?", 1)[0] or "/").rstrip("/") or "/"
        if method == "GET" and path in ("/", "/status"):
            self._send(200, read_status())
            return
        if method == "POST" and path == "/start":
            self._send(200, do_start())
            return
        if method == "POST" and path == "/stop":
            self._send(200, do_stop())
            return
        self._send(404, {"state": "error", "error": "not found"})

    def do_GET(self):
        self._route("GET")

    def do_POST(self):
        length = int(self.headers.get("Content-Length") or "0")
        if length:
            self.rfile.read(length)
        self._route("POST")

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Allow", "GET, POST, OPTIONS")
        self.send_header("Connection", "close")
        self.end_headers()


def main():
    httpd = ControlHTTPServer((HOST, PORT), Handler)
    addr = httpd.server_address
    print("tdc_control http://%s:%s/status" % (addr[0], addr[1]), flush=True)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("stopping", flush=True)
    finally:
        httpd.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
