#!/usr/bin/env python3
"""
Gehaerteter Dashboard-HTTP-Server mit Whitelist.

`python3 -m http.server` serviert das GANZE Verzeichnis — inkl. config.py
(API-Keys!), State- und Trade-Dateien. Dieser Server liefert NUR die explizit
erlaubten Dateien aus; alles andere -> 403. Kein Directory-Listing.

Usage:  python3 dash_server.py <port> <erlaubte_datei> [<weitere> ...]
        (im zu servierenden Verzeichnis ausgefuehrt; Dateinamen relativ)
"""
import sys
from http.server import SimpleHTTPRequestHandler
from socketserver import ThreadingTCPServer

if len(sys.argv) < 3:
    print("Usage: dash_server.py <port> <file> [file ...]")
    sys.exit(1)

PORT    = int(sys.argv[1])
ALLOWED = set(sys.argv[2:])
DEFAULT = sys.argv[2]            # "/" liefert die erste erlaubte Datei (das HTML)


class Handler(SimpleHTTPRequestHandler):
    def _check(self):
        p = self.path.split("?")[0].split("#")[0].lstrip("/")
        if p == "":
            p = DEFAULT
        if p not in ALLOWED:
            self.send_error(403, "Forbidden")
            return None
        self.path = "/" + p
        return p

    def end_headers(self):
        # echte No-Cache-Header -> Browser holt immer die frische Version
        self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
        self.send_header("Pragma", "no-cache")
        self.send_header("Expires", "0")
        super().end_headers()

    def do_GET(self):
        if self._check() is not None:
            super().do_GET()

    def do_HEAD(self):
        if self._check() is not None:
            super().do_HEAD()

    def list_directory(self, path):     # niemals Verzeichnis-Listing
        self.send_error(403, "Forbidden")
        return None

    def log_message(self, *a):          # kein Spam ins Log
        pass


ThreadingTCPServer.allow_reuse_address = True
print("[DASH] Port " + str(PORT) + " | erlaubt: " + ", ".join(sorted(ALLOWED)))
ThreadingTCPServer(("", PORT), Handler).serve_forever()
