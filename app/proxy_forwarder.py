"""Local no-auth proxy -> upstream authenticated HTTP proxy.

Chrome 138+ (CloakBrowser v146) no longer loads Manifest V2 extensions, so the
old onAuthRequired extension cannot supply proxy credentials. Instead the
runner starts this forwarder on 127.0.0.1 and points Chrome at it; the
forwarder injects the Proxy-Authorization header for every connection.
"""
import base64
import socket
import threading
import time
from urllib.parse import urlparse

_MAX_HEADER = 256 * 1024


def _pipe(src, dst):
    try:
        while True:
            data = src.recv(65536)
            if not data:
                break
            dst.sendall(data)
    except OSError:
        pass
    finally:
        for s in (dst, src):
            try:
                s.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass


class LocalProxyForwarder:
    def __init__(self, upstream_host, upstream_port, username, password):
        self.upstream = (upstream_host, int(upstream_port))
        token = base64.b64encode(f"{username}:{password}".encode("utf-8")).decode("ascii")
        self.auth_line = b"Proxy-Authorization: Basic " + token.encode("ascii")
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.bind(("127.0.0.1", 0))
        self.sock.listen(512)
        self.port = self.sock.getsockname()[1]

    @property
    def server(self):
        return f"http://127.0.0.1:{self.port}"

    def start(self):
        threading.Thread(target=self._accept_loop, daemon=True).start()
        return self

    def _accept_loop(self):
        while True:
            try:
                client, _ = self.sock.accept()
            except OSError:
                return
            threading.Thread(target=self._handle, args=(client,), daemon=True).start()

    def _read_head(self, sock):
        data = b""
        while b"\r\n\r\n" not in data:
            chunk = sock.recv(65536)
            if not chunk or len(data) > _MAX_HEADER:
                with open("proxy_debug.log", "a") as f: f.write(f"[_read_head] Chunk empty or >MAX_HEADER. len(data)={len(data)}\n")
                return None, None
            data += chunk
        head, rest = data.split(b"\r\n\r\n", 1)
        return head, rest

    def _open_upstream(self, payload):
        """Send payload upstream and read the response head.
        Returns (sock, head, rest) or raises OSError."""
        up = socket.create_connection(self.upstream, timeout=30)
        up.sendall(payload)
        head, rest = self._read_head(up)
        if head is None:
            up.close()
            with open("proxy_debug.log", "a") as f: f.write(f"[_open_upstream] Failed to read head from upstream\n")
            raise OSError("upstream closed")
        return up, head, rest

    @staticmethod
    def _status(head):
        try:
            return int(head.split(b"\r\n", 1)[0].split()[1])
        except (IndexError, ValueError):
            return 0

    def _handle(self, client):
        upstream = None
        try:
            head, rest = self._read_head(client)
            if head is None:
                with open("proxy_debug.log", "a") as f: f.write(f"[_handle] Failed to read head from client\n")
                return
            lines = head.split(b"\r\n")
            is_connect = lines[0].upper().startswith(b"CONNECT ")
            with open("proxy_debug.log", "a") as f: f.write(f"[_handle] Request: {lines[0].decode('utf-8', 'replace')}\n")
            drop = (b"proxy-authorization:", b"connection:", b"proxy-connection:")
            out = [lines[0], self.auth_line]
            out += [l for l in lines[1:] if not l.lower().startswith(drop)]
            out.append(b"Connection: close" if not is_connect else b"Proxy-Connection: keep-alive")
            payload = b"\r\n".join(out) + b"\r\n\r\n" + rest

            # CONNECT: Chrome sends nothing until it gets 200, so retrying is safe.
            attempts = 6 if is_connect else 3
            resp_head, resp_rest = None, b""
            for i in range(attempts):
                try:
                    upstream, resp_head, resp_rest = self._open_upstream(payload)
                except OSError as e:
                    with open("proxy_debug.log", "a") as f: f.write(f"[_handle] Attempt {i+1} OSError: {e}\n")
                    upstream, resp_head = None, None
                if resp_head is not None:
                    status = self._status(resp_head)
                    with open("proxy_debug.log", "a") as f: f.write(f"[_handle] Attempt {i+1} status: {status}\n")
                    if status != 407:
                        break
                if upstream is not None:
                    try:
                        upstream.close()
                    except OSError:
                        pass
                    upstream = None
                time.sleep(0.4 * (i + 1))

            if upstream is None:
                with open("proxy_debug.log", "a") as f: f.write(f"[_handle] Upstream is None after {attempts} attempts. Sending 502.\n")
                # Never forward 407 to Chrome (it would pop up a login dialog).
                client.sendall(b"HTTP/1.1 502 Bad Gateway\r\nContent-Length: 0\r\nConnection: close\r\n\r\n")
                return

            upstream.settimeout(None)
            if is_connect:
                client.sendall(resp_head + b"\r\n\r\n" + resp_rest)
            else:
                # Force Chrome to open a new connection for its next request,
                # so every request goes through here and gets the auth header.
                r_lines = resp_head.split(b"\r\n")
                r_out = [r_lines[0]] + [l for l in r_lines[1:] if not l.lower().startswith(
                    (b"connection:", b"proxy-connection:", b"keep-alive:", b"proxy-authenticate:"))]
                r_out += [b"Connection: close", b"Proxy-Connection: close"]
                client.sendall(b"\r\n".join(r_out) + b"\r\n\r\n" + resp_rest)
            threading.Thread(target=_pipe, args=(client, upstream), daemon=True).start()
            _pipe(upstream, client)
        except OSError as e:
            with open("proxy_debug.log", "a") as f: f.write(f"[_handle] Outer OSError: {e}\n")
        except Exception as e:
            with open("proxy_debug.log", "a") as f: f.write(f"[_handle] Outer Exception: {e}\n")
        finally:
            for s in (client, upstream):
                if s is not None:
                    try:
                        s.close()
                    except OSError:
                        pass


def start_forwarder(proxy: dict) -> str:
    """proxy = {"server": "http://host:port", "username": ..., "password": ...}.
    Returns the local server URL to hand to Chrome."""
    u = urlparse(proxy["server"])
    fwd = LocalProxyForwarder(u.hostname, u.port or 80, proxy.get("username", ""), proxy.get("password", ""))
    return fwd.start().server
