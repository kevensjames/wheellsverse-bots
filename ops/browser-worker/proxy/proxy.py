"""Strict egress-allowlist SOCKS5 proxy (sidecar). Default-DENY, remote DNS.

The worker runs on an INTERNAL docker network (no direct internet, no external DNS). Chromium
is pointed at socks5://<this>:8888, so it sends the target HOSTNAME to the proxy (remote DNS) —
no local resolution needed. The proxy permits a CONNECT only to an exact host in ALLOWED_DOMAINS
on port 443; IP-literal targets, non-443 ports, internal/metadata hosts, and everything else → refused.
Even a compromised runner cannot reach a non-allowlisted host.
"""
import os, socket, struct, threading, select

ALLOW = {d.strip().lower() for d in os.environ.get("ALLOWED_DOMAINS", "").split(",") if d.strip()}
BLOCK_PREFIX = ("localhost", "127.", "169.254.", "10.", "192.168.", "172.16.", "0.0.0.0")
PORT = int(os.environ.get("PROXY_PORT", "8888"))


def _forbidden(host: str) -> bool:
    h = host.lower()
    if any(h.startswith(b) for b in BLOCK_PREFIX):
        return True
    return h not in ALLOW              # default-deny: exact allowlisted host only


def _recvn(s, n):
    buf = b""
    while len(buf) < n:
        d = s.recv(n - len(buf))
        if not d:
            raise ConnectionError("short read")
        buf += d
    return buf


def _tunnel(a, b):
    try:
        while True:
            r, _, _ = select.select([a, b], [], [], 120)
            if not r:
                break
            for s in r:
                data = s.recv(65536)
                if not data:
                    return
                (b if s is a else a).sendall(data)
    finally:
        for s in (a, b):
            try: s.close()
            except Exception: pass


def handle(conn):
    conn.settimeout(30)
    try:
        ver, nm = _recvn(conn, 2)
        if ver != 5:
            conn.close(); return
        _recvn(conn, nm)                       # methods (ignored — no auth)
        conn.sendall(b"\x05\x00")              # no-auth accepted
        hdr = _recvn(conn, 4)
        ver, cmd, _, atyp = hdr
        if ver != 5 or cmd != 1:               # only CONNECT
            conn.sendall(b"\x05\x07\x00\x01\x00\x00\x00\x00\x00\x00"); conn.close(); return
        if atyp == 3:                          # domain (what Chromium sends with remote DNS)
            ln = _recvn(conn, 1)[0]
            host = _recvn(conn, ln).decode("ascii", errors="ignore")  # wire hostnames are ASCII/punycode
        else:                                  # IPv4/IPv6 literal → refuse (allowlist is by name)
            _recvn(conn, 16 if atyp == 4 else 4)
            _recvn(conn, 2)
            conn.sendall(b"\x05\x02\x00\x01\x00\x00\x00\x00\x00\x00"); conn.close(); return
        port = struct.unpack("!H", _recvn(conn, 2))[0]
        if port != 443 or _forbidden(host):
            conn.sendall(b"\x05\x02\x00\x01\x00\x00\x00\x00\x00\x00"); conn.close(); return  # denied
        try:
            up = socket.create_connection((host, port), 10)
        except Exception:
            conn.sendall(b"\x05\x04\x00\x01\x00\x00\x00\x00\x00\x00"); conn.close(); return
        conn.sendall(b"\x05\x00\x00\x01\x00\x00\x00\x00\x00\x00")   # success
        _tunnel(conn, up)
    except Exception:
        try: conn.close()
        except Exception: pass


def main():
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(("0.0.0.0", PORT)); srv.listen(64)
    print(f"egress-allowlist SOCKS5 proxy on {PORT}; allow={sorted(ALLOW)}", flush=True)
    while True:
        c, _ = srv.accept()
        threading.Thread(target=handle, args=(c,), daemon=True).start()


if __name__ == "__main__":
    main()
