#!/usr/bin/env python3
"""Dev server for the invoice app.  python3 serve.py [port]   (default 8741)"""
import http.server, socketserver, sys, os

PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 8741
os.chdir(os.path.dirname(os.path.abspath(__file__)))


class H(http.server.SimpleHTTPRequestHandler):
    extensions_map = {**http.server.SimpleHTTPRequestHandler.extensions_map,
                      ".gz": "application/gzip"}

    def end_headers(self):
        # The registry blob is content-hashed by its build date, everything
        # else is edited constantly - never let the browser cache the app.
        if self.path.endswith(".gz"):
            self.send_header("Cache-Control", "public, max-age=86400")
        else:
            self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def log_message(self, fmt, *a):
        if "GET" in (a[0] if a else ""):
            sys.stderr.write("  %s\n" % (a[0] if a else ""))


socketserver.TCPServer.allow_reuse_address = True
with socketserver.TCPServer(("", PORT), H) as httpd:
    print(f"Saskaitos  ->  http://localhost:{PORT}/")
    print(f"tests      ->  http://localhost:{PORT}/test.html")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nbye")
