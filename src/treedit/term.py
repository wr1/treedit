"""The agent terminal: one shell on a pseudo-terminal, shared by every connected page over WebSocket.

Standard library only (POSIX). The shell starts lazily on the first connection; with an agent
preset (e.g. "claude") the command is typed into the shell, so quitting the agent leaves you at
a prompt. Output is kept in a scrollback buffer and replayed when a page (re)connects.
"""

from __future__ import annotations

import base64
import fcntl
import hashlib
import json
import os
import signal
import struct
import subprocess
import termios
import threading

SCROLLBACK = 256 * 1024
WS_GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"


# ---------- WebSocket (RFC 6455, just what a terminal needs) ----------
def ws_accept(key: str) -> str:
    return base64.b64encode(hashlib.sha1((key + WS_GUID).encode()).digest()).decode()


def ws_recv(rfile):
    """(opcode, payload) of the next client frame, reassembling fragments; None when the peer is gone."""
    try:
        return _ws_recv(rfile)
    except (OSError, struct.error):  # reset / closed tab
        return None


def _ws_recv(rfile):
    data, first_op = b"", None
    while True:
        head = rfile.read(2)
        if len(head) < 2:
            return None
        fin, op, masked, n = head[0] & 0x80, head[0] & 0x0F, head[1] & 0x80, head[1] & 0x7F
        if n == 126:
            n = struct.unpack(">H", rfile.read(2))[0]
        elif n == 127:
            n = struct.unpack(">Q", rfile.read(8))[0]
        mask = rfile.read(4) if masked else b"\0\0\0\0"
        raw = rfile.read(n)
        if len(raw) < n:
            return None
        payload = bytes(b ^ mask[i % 4] for i, b in enumerate(raw)) if masked else raw
        if op >= 8:  # control frames may arrive between fragments
            return op, payload
        first_op = op if first_op is None else first_op
        data += payload
        if fin:
            return first_op, data


def ws_frame(op: int, payload: bytes) -> bytes:
    n = len(payload)
    if n < 126:
        head = struct.pack(">BB", 0x80 | op, n)
    elif n < 65536:
        head = struct.pack(">BBH", 0x80 | op, 126, n)
    else:
        head = struct.pack(">BBQ", 0x80 | op, 127, n)
    return head + payload


class Client:
    def __init__(self, sock):
        self.sock, self.lock = sock, threading.Lock()

    def send(self, op: int, payload: bytes) -> bool:
        try:
            with self.lock:
                self.sock.sendall(ws_frame(op, payload))
            return True
        except OSError:
            return False


# ---------- the shared terminal ----------
class Terminal:
    def __init__(
        self,
        cwd: str,
        env: dict,
        agent: str = "",
        root: str | None = None,
        label: str = "",
        reuse: bool | None = None,
    ):
        self.cwd, self.env, self.agent = cwd, env, agent
        self.root = root or cwd  # the opened folder this session belongs to; cwd may be a subfolder
        self.name = label  # a short title, when the command itself is too long for the pane
        self.reuse = (not agent.strip()) if reuse is None else reuse  # a shell a later command may use
        self.pending = bytearray()  # input for a session that has not started yet
        self.lock = threading.Lock()
        self.clients: set = set()
        self.buf = bytearray()
        self.proc = None
        self.master = None
        self.size = (24, 80)
        self.gen = 0  # session number; a finished old session must not report on a new one

    @property
    def alive(self) -> bool:
        return self.proc is not None and self.proc.poll() is None

    @property
    def at_prompt(self) -> bool:
        """True when the shell itself owns the terminal: no command or agent is in the foreground."""
        if not self.alive or self.master is None:
            return False
        try:
            return os.tcgetpgrp(self.master) == self.proc.pid
        except (AttributeError, OSError):
            return False

    def label(self) -> str:
        return self.name or self.agent or os.path.basename(self.env.get("SHELL") or "sh")

    def start(self) -> None:
        with self.lock:
            if self.alive:
                return
            shell = self.env.get("SHELL") or "/bin/sh"
            master, slave = os.openpty()
            self._winsize(master)

            def ctty():  # runs in the child after setsid(): make the pty its controlling terminal
                fcntl.ioctl(0, termios.TIOCSCTTY, 0)

            self.proc = subprocess.Popen(
                [shell, "-i"],
                stdin=slave,
                stdout=slave,
                stderr=slave,
                cwd=self.cwd,
                env=self.env,
                start_new_session=True,
                preexec_fn=ctty,
                close_fds=True,
            )
            os.close(slave)
            self.master = master
            self.gen += 1
            self.buf.clear()
            for c in list(self.clients):
                c.send(1, json.dumps({"t": "reset"}).encode())
            threading.Thread(target=self._pump, args=(master, self.gen), daemon=True).start()
            if self.agent:
                self.write((self.agent + "\r").encode())
            if self.pending:
                data, self.pending = bytes(self.pending), bytearray()
                self.write(data)

    def _winsize(self, fd: int) -> None:
        rows, cols = self.size
        fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack("HHHH", rows, cols, 0, 0))

    def _pump(self, master: int, gen: int) -> None:
        while True:
            try:
                chunk = os.read(master, 65536)
            except OSError:
                chunk = b""
            if not chunk:
                break
            self._broadcast(chunk)
        try:
            os.close(master)
        except OSError:
            pass
        if gen != self.gen:
            return
        self.master = None
        self._broadcast(b"\r\n\x1b[2m[session ended - Restart to start a new one]\x1b[0m\r\n")
        for c in list(self.clients):
            c.send(1, json.dumps({"t": "exit"}).encode())

    def _broadcast(self, chunk: bytes) -> None:
        with self.lock:
            self.buf += chunk
            if len(self.buf) > SCROLLBACK:
                del self.buf[: len(self.buf) - SCROLLBACK]
            clients = list(self.clients)
        for c in clients:
            if not c.send(2, chunk):
                self.clients.discard(c)

    def write(self, data: bytes) -> None:
        if self.master is None:
            if self.proc is None and len(self.pending) < 65536:  # not started yet: keep it for the first prompt
                self.pending += data
            return
        try:
            os.write(self.master, data)
        except OSError:
            pass

    def resize(self, rows: int, cols: int) -> None:
        self.size = (max(2, rows), max(10, cols))
        if self.master is not None:
            try:
                self._winsize(self.master)
            except OSError:
                pass

    def stop(self) -> None:
        if self.alive:
            try:
                os.killpg(self.proc.pid, signal.SIGHUP)
                self.proc.wait(timeout=2)
            except (OSError, subprocess.TimeoutExpired):
                try:
                    os.killpg(self.proc.pid, signal.SIGKILL)
                except OSError:
                    pass

    def restart(self) -> None:
        self.gen += 1
        self.stop()
        self.start()

    def serve(self, sock, rfile) -> None:
        """Run one WebSocket connection: replay scrollback, then relay input and resizes."""
        client = Client(sock)
        with self.lock:
            backlog = bytes(self.buf)
            self.clients.add(client)
        client.send(1, json.dumps({"t": "hello", "label": self.label()}).encode())
        if backlog:
            client.send(2, backlog)
        if not self.alive:
            self.start()
        try:
            while True:
                msg = ws_recv(rfile)
                if msg is None:
                    break
                op, payload = msg
                if op == 8:
                    client.send(8, b"")
                    break
                if op == 9:
                    client.send(10, payload)
                    continue
                if op not in (1, 2):
                    continue
                try:
                    m = json.loads(payload)
                except ValueError:
                    continue
                if m.get("t") == "in":
                    self.write(str(m.get("d", "")).encode("utf-8", "surrogateescape"))
                elif m.get("t") == "resize":
                    self.resize(int(m.get("rows", 24)), int(m.get("cols", 80)))
                elif m.get("t") == "restart":
                    self.restart()
        finally:
            self.clients.discard(client)


# ---------- the sessions of the pane ----------
class Sessions:
    """The terminals of the agent pane, in the order they were added: each its own shell or agent preset
    on a pseudo-terminal, started in CWD with ENV. The first runs AGENT; more are added from the page."""

    def __init__(self, cwd: str, env: dict, agent: str = ""):
        self.cwd, self.env = cwd, env
        self.lock = threading.Lock()
        self.terms: dict = {}
        self.next = 1
        self.add(agent)

    def add(
        self,
        agent: str = "",
        cwd: str | None = None,
        env_extra: dict | None = None,
        root: str | None = None,
        label: str = "",
        reuse: bool | None = None,
    ) -> str:
        """A new session. CWD defaults to the window's first folder. ROOT is the opened folder it
        belongs to (the default for CWD). ENV_EXTRA overlays the shared env, so a session can carry
        its own TREEDIT_ROOT without changing the ones already running. REUSE marks a session a
        later command may be typed into (a plain shell, or a finished make run)."""
        with self.lock:
            sid = str(self.next)
            self.next += 1
            env = {**self.env, **(env_extra or {})}
            self.terms[sid] = Terminal(cwd or self.cwd, env, agent.strip(), root, label, reuse)
            return sid

    def get(self, sid: str):
        return self.terms.get(sid)

    def shell(self, prefer: str = "") -> tuple[str, Terminal] | None:
        """A shell that can take a command now: PREFER if it qualifies, else the latest one.
        Never started counts (its input is queued for the first prompt); a live one must be at
        its prompt, and an ended one is left alone."""
        with self.lock:
            hits = [(sid, t) for sid, t in self.terms.items() if t.reuse and (t.proc is None or t.at_prompt)]
        if not hits:
            return None
        for sid, t in hits:
            if sid == prefer:
                return sid, t
        return hits[-1]

    def close(self, sid: str) -> bool:
        with self.lock:
            t = self.terms.pop(sid, None)
        if t is None:
            return False
        t.stop()
        for c in list(t.clients):  # tell its pages the pane is gone
            c.send(1, json.dumps({"t": "closed"}).encode())
            c.send(8, b"")
        return True

    def list(self) -> list:
        out = []
        for sid, t in list(self.terms.items()):
            try:
                rel = os.path.relpath(t.cwd, t.root)
            except ValueError:  # different drives on Windows
                rel = ""
            out.append(
                {
                    "id": sid,
                    "label": t.label(),
                    "agent": t.agent,
                    "alive": t.alive,
                    "root": t.root,
                    "dir": "" if rel in ("", ".") else rel,
                }
            )
        return out

    def stop(self) -> None:
        for t in list(self.terms.values()):
            t.stop()
