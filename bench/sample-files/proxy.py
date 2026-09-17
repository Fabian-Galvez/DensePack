"""A local pass-through proxy that measures the part no hook can see.

    python proxy.py [port]           run it in the foreground
    python proxy.py --measure        print what it has recorded so far

WHAT IT IS FOR. A Claude Code hook never sees the system prompt or the tool
definitions. bench/archive-100-command/fixed_base.py measured those two
together at 61,898 tokens
riding in every request, 57.5 per cent of what a request still costs after
DensePack has packed everything it can reach. Nobody has measured how that
61,898 splits between the system prompt and the tool definitions, and the
split decides whether imaging the system prompt is worth building at all.

This proxy sits between Claude Code and the API, forwards every request
byte for byte, and writes one line per request recording the size of each
part. It changes NOTHING in the request or the response. It is a measuring
instrument first; any rewriting comes later and only after the numbers say
which rewrite is worth it.

OFF BY DEFAULT. Claude Code reaches this only when ANTHROPIC_BASE_URL points
at it, and that variable is written by `python dpctl.py proxy on`, never
automatically. With the variable set and this process dead, every request goes
to a closed port and the session stops until the proxy runs again or
`python dpctl.py proxy off` removes the variable. That failure is the reason
it ships off.
"""
import json
import os
import socket
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit

try:
    from common import tmp_dir
except ImportError:  # run straight from a checkout
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from common import tmp_dir
from densepack import CHARS_PER_TOKEN

UPSTREAM = os.environ.get("DENSEPACK_UPSTREAM", "https://api.anthropic.com")
DEFAULT_PORT = 41100
LOG = "densepack-proxy-requests.jsonl"

# The divisor is imported from densepack above, not redefined here, so a
# number from this proxy can be set beside one from bench/ and one from a
# receipt. It used to be a second copy of the literal and went stale.

# Headers the proxy must not copy onward. Hop-by-hop headers belong to one
# connection, and Host has to name the upstream rather than this port.
DROP = {"host", "connection", "keep-alive", "proxy-authenticate",
        "proxy-authorization", "te", "trailers", "transfer-encoding",
        "upgrade", "content-length"}


def measure(body):
    """The size of each part of one request body, in characters.

    Returns None when the body is not a Messages API call, so a token count
    or a models list never lands in the log as though it were a turn.
    """
    try:
        data = json.loads(body)
    except (ValueError, TypeError):
        return None
    if not isinstance(data, dict) or "messages" not in data:
        return None

    system = data.get("system")
    if isinstance(system, str):
        system_chars = len(system)
    elif isinstance(system, list):
        system_chars = sum(len(json.dumps(b)) for b in system)
    else:
        system_chars = 0

    tools = data.get("tools") or []
    tool_chars = len(json.dumps(tools)) if tools else 0

    messages = data.get("messages") or []
    message_chars = len(json.dumps(messages))

    # Each tool by name and size. Without this the log says the definitions
    # are large and cannot say WHICH ones, and the answer decides whether
    # anything can be done about them: a built-in tool cannot be deferred and
    # an MCP tool already is.
    per_tool = []
    if isinstance(tools, list):
        for tool in tools:
            if not isinstance(tool, dict):
                continue
            per_tool.append({
                "name": tool.get("name") or tool.get("type") or "?",
                "chars": len(json.dumps(tool)),
                "deferred": bool(tool.get("defer_loading")),
            })
        per_tool.sort(key=lambda t: -t["chars"])

    return {
        "at": round(time.time(), 1),
        "model": data.get("model") or "",
        "system_chars": system_chars,
        "tool_chars": tool_chars,
        "tool_count": len(tools) if isinstance(tools, list) else 0,
        "tools": per_tool,
        "message_chars": message_chars,
        "total_chars": system_chars + tool_chars + message_chars,
    }


def record(row):
    try:
        with (tmp_dir() / LOG).open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(row) + "\n")
    except OSError:
        pass


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *_args):
        """Silent. This runs behind a session and must not print to its
        console."""

    def _relay(self, method):
        import http.client

        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length) if length else b""

        if body:
            row = measure(body)
            if row:
                record(row)

        parts = urlsplit(UPSTREAM)
        cls = (http.client.HTTPSConnection if parts.scheme == "https"
               else http.client.HTTPConnection)
        conn = cls(parts.netloc, timeout=600)
        headers = {k: v for k, v in self.headers.items()
                   if k.lower() not in DROP}
        try:
            conn.request(method, self.path, body=body, headers=headers)
            upstream = conn.getresponse()
        except (OSError, http.client.HTTPException) as exc:
            self.send_response(502)
            self.send_header("Content-Type", "application/json")
            payload = json.dumps({"type": "error", "error": {
                "type": "densepack_proxy_error", "message": str(exc)}}).encode()
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
            return

        self.send_response(upstream.status)
        for key, value in upstream.getheaders():
            if key.lower() in DROP:
                continue
            self.send_header(key, value)
        self.send_header("Transfer-Encoding", "chunked")
        self.end_headers()

        # Streamed byte for byte. A Messages stream must reach the client as
        # it arrives, so nothing here buffers the whole body.
        try:
            while True:
                chunk = upstream.read(8192)
                if not chunk:
                    break
                self.wfile.write(b"%X\r\n%s\r\n" % (len(chunk), chunk))
                self.wfile.flush()
            self.wfile.write(b"0\r\n\r\n")
            self.wfile.flush()
        except OSError:
            pass
        finally:
            conn.close()

    def do_POST(self):
        self._relay("POST")

    def do_GET(self):
        self._relay("GET")


def report():
    """What the log holds: the split of the fixed base, per request."""
    path = tmp_dir() / LOG
    if not path.is_file():
        print("no requests recorded yet at %s" % path)
        return 1
    rows = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except ValueError:
            continue
    if not rows:
        print("no requests recorded yet")
        return 1

    n = len(rows)
    system = sum(r["system_chars"] for r in rows) / n
    tools = sum(r["tool_chars"] for r in rows) / n
    messages = sum(r["message_chars"] for r in rows) / n
    base = system + tools
    total = base + messages

    def line(name, chars):
        print("| %s | %s | %s | %.1f per cent |" % (
            name, format(round(chars), ","),
            format(round(chars / CHARS_PER_TOKEN), ","),
            chars / total * 100 if total else 0))

    print("| Part of a request | Characters, mean | Tokens, mean | Share of a request |")
    print("| --- | --- | --- | --- |")
    line("System prompt", system)
    line("Tool definitions", tools)
    line("THE FIXED BASE, no hook can reach it", base)
    line("Messages, what the hooks do reach", messages)
    print("")
    print("%d requests recorded. Tool definitions counted: %d on the last "
          "request." % (n, rows[-1]["tool_count"]))

    # Named per_tool, not tools: `tools` above already holds the mean
    # character count, and reusing the name made report() raise on every run
    # that had a tool list. Found 26 August 2026.
    per_tool = rows[-1].get("tools") or []
    if per_tool:
        print("")
        print("| Tool | Characters | Tokens | Deferred |")
        print("| --- | --- | --- | --- |")
        for tool in per_tool:
            print("| %s | %s | %s | %s |" % (
                tool["name"], format(tool["chars"], ","),
                format(round(tool["chars"] / CHARS_PER_TOKEN), ","),
                "yes" if tool.get("deferred") else "no"))
    if base:
        print("System prompt is %.1f per cent of the fixed base, tool "
              "definitions %.1f per cent."
              % (system / base * 100, tools / base * 100))
    return 0


def main():
    if "--measure" in sys.argv:
        return report()
    port = DEFAULT_PORT
    for arg in sys.argv[1:]:
        if arg.isdigit():
            port = int(arg)
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    server.daemon_threads = True
    print("DensePack proxy on 127.0.0.1:%d, forwarding to %s" % (port, UPSTREAM))
    print("It measures and forwards. It changes nothing in a request.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
