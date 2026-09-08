#!/usr/bin/env python3
"""Minimal Chrome DevTools Protocol driver (stdlib only, no node/websockets needed).

Usage as a library:
    from cdp import Chrome
    with Chrome(width=390, height=844, dpr=3) as c:
        c.goto("http://localhost:8736/")
        c.eval("offlineLogin(); seed(); showView('floor');")
        c.shot("/tmp/x.png")
"""
import base64, json, os, socket, struct, subprocess, sys, time, urllib.request

CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"


class WS:
    def __init__(self, url):
        assert url.startswith("ws://")
        rest = url[5:]
        hostport, _, path = rest.partition("/")
        host, _, port = hostport.partition(":")
        self.sock = socket.create_connection((host, int(port or 80)), timeout=30)
        key = base64.b64encode(os.urandom(16)).decode()
        req = (
            f"GET /{path} HTTP/1.1\r\nHost: {hostport}\r\nUpgrade: websocket\r\n"
            f"Connection: Upgrade\r\nSec-WebSocket-Key: {key}\r\n"
            "Sec-WebSocket-Version: 13\r\n\r\n"
        )
        self.sock.sendall(req.encode())
        buf = b""
        while b"\r\n\r\n" not in buf:
            buf += self.sock.recv(4096)
        assert b"101" in buf.split(b"\r\n")[0], buf[:200]
        self.buf = buf.split(b"\r\n\r\n", 1)[1]

    def _recv(self, n):
        while len(self.buf) < n:
            chunk = self.sock.recv(65536)
            if not chunk:
                raise ConnectionError("ws closed")
            self.buf += chunk
        out, self.buf = self.buf[:n], self.buf[n:]
        return out

    def send(self, text):
        payload = text.encode()
        mask = os.urandom(4)
        n = len(payload)
        hdr = b"\x81"
        if n < 126:
            hdr += bytes([0x80 | n])
        elif n < 65536:
            hdr += b"\xfe" + struct.pack(">H", n)
        else:
            hdr += b"\xff" + struct.pack(">Q", n)
        masked = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))
        self.sock.sendall(hdr + mask + masked)

    def recv(self):
        while True:
            b0, b1 = self._recv(2)
            op = b0 & 0x0F
            n = b1 & 0x7F
            if n == 126:
                n = struct.unpack(">H", self._recv(2))[0]
            elif n == 127:
                n = struct.unpack(">Q", self._recv(8))[0]
            data = self._recv(n)
            if op == 1:
                return data.decode("utf-8", "replace")
            if op == 8:
                raise ConnectionError("ws close frame")
            # ignore ping/pong/binary

    def close(self):
        try:
            self.sock.close()
        except Exception:
            pass


class Chrome:
    def __init__(self, width=390, height=844, dpr=2, port=9333, profile=None, mobile=True):
        self.w, self.h, self.dpr, self.mobile = width, height, dpr, mobile
        self.port = port
        self.profile = profile or f"/tmp/cdp-profile-{port}"
        self.msg_id = 0
        self.logs = []

    def __enter__(self):
        self.proc = subprocess.Popen(
            [CHROME, "--headless=new", f"--remote-debugging-port={self.port}",
             f"--user-data-dir={self.profile}", "--no-first-run", "--no-default-browser-check",
             "--hide-scrollbars", "--disable-gpu-vsync", "--force-device-scale-factor=1",
             f"--window-size={self.w},{self.h}", "about:blank"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        ws_url = None
        for _ in range(80):
            try:
                data = json.load(urllib.request.urlopen(f"http://127.0.0.1:{self.port}/json/list", timeout=2))
                for t in data:
                    if t.get("type") == "page":
                        ws_url = t["webSocketDebuggerUrl"]
                        break
                if ws_url:
                    break
            except Exception:
                pass
            time.sleep(0.25)
        if not ws_url:
            raise RuntimeError("chrome devtools not reachable")
        self.ws = WS(ws_url)
        self.cmd("Page.enable")
        self.cmd("Runtime.enable")
        self.cmd("Log.enable")
        self.cmd("Network.enable")
        self.cmd("Network.setCacheDisabled", {"cacheDisabled": True})
        self.cmd("Emulation.setDeviceMetricsOverride", {
            "width": self.w, "height": self.h, "deviceScaleFactor": self.dpr, "mobile": self.mobile})
        if self.mobile:
            self.cmd("Emulation.setTouchEmulationEnabled", {"enabled": True, "maxTouchPoints": 5})
            self.cmd("Emulation.setUserAgentOverride", {"userAgent":
                "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 "
                "(KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1"})
        return self

    def __exit__(self, *a):
        try:
            self.ws.close()
        finally:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=5)
            except Exception:
                self.proc.kill()

    def cmd(self, method, params=None, timeout=60):
        self.msg_id += 1
        mid = self.msg_id
        self.ws.send(json.dumps({"id": mid, "method": method, "params": params or {}}))
        deadline = time.time() + timeout
        while time.time() < deadline:
            msg = json.loads(self.ws.recv())
            if msg.get("id") == mid:
                if "error" in msg:
                    raise RuntimeError(f"{method}: {msg['error']}")
                return msg.get("result", {})
            m = msg.get("method", "")
            if m == "Runtime.consoleAPICalled":
                args = " ".join(str(a.get("value", a.get("description", "?"))) for a in msg["params"].get("args", []))
                self.logs.append(f"[{msg['params']['type']}] {args}")
            elif m == "Runtime.exceptionThrown":
                d = msg["params"]["exceptionDetails"]
                self.logs.append("[pageerror] " + (d.get("exception", {}).get("description") or d.get("text", "")))
            elif m == "Log.entryAdded":
                e = msg["params"]["entry"]
                if e.get("level") in ("error", "warning"):
                    self.logs.append(f"[{e['level']}] {e.get('text','')} {e.get('url','')}")
        raise TimeoutError(method)

    def goto(self, url, wait=1.5):
        self.cmd("Page.navigate", {"url": url})
        time.sleep(wait)

    def eval(self, expr, await_promise=False):
        r = self.cmd("Runtime.evaluate", {
            "expression": expr, "returnByValue": True, "awaitPromise": await_promise,
            "userGesture": True})
        if "exceptionDetails" in r:
            d = r["exceptionDetails"]
            return {"__error": d.get("exception", {}).get("description") or d.get("text")}
        return r.get("result", {}).get("value")

    def resize(self, w, h, dpr=None):
        self.w, self.h = w, h
        if dpr:
            self.dpr = dpr
        self.cmd("Emulation.setDeviceMetricsOverride", {
            "width": w, "height": h, "deviceScaleFactor": self.dpr, "mobile": self.mobile})

    def shot(self, path, full=False):
        p = {"format": "png"}
        if full:
            p["captureBeyondViewport"] = True
        r = self.cmd("Page.captureScreenshot", p)
        with open(path, "wb") as f:
            f.write(base64.b64decode(r["data"]))
        return path

    def drain_logs(self):
        out, self.logs = self.logs[:], []
        return out


if __name__ == "__main__":
    url = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8736/"
    out = sys.argv[2] if len(sys.argv) > 2 else "/tmp/shot.png"
    with Chrome() as c:
        c.goto(url, wait=2.5)
        c.shot(out)
        print("logs:", c.drain_logs())
        print("saved", out)
