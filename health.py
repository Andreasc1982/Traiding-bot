#!/usr/bin/env python3
"""
Zentrales Health-/Event-Logging + Singleton-Lock fuer ALLE Bots/Agents.

Ziel: autarkes Live-Laufen. Jeder relevante Vorfall (Start, Crash, Hang,
Duplikat-Block, WS-Ausfall, State-Restore, Halt/Resume) landet append-only in
EINER Datei -> ueber Wochen filter- und auswertbar (siehe health_report.py),
damit wir wiederkehrende Fehlermuster sehen und abstellen koennen.

Verwendung:
    import health
    lock = health.acquire_singleton("super_bot")   # None -> laeuft schon
    if lock is None:
        health.log("super_bot", "DUPLICATE_BLOCKED", "andere Instanz aktiv")
        raise SystemExit(0)
    health.log("super_bot", "START", "balance=64802")

Design-Prinzipien (aus unseren Bugs gelernt):
 - Logging darf NIE den Bot crashen (alles in try/except, schluckt eigene Fehler).
 - flock-basiert: mehrere Prozesse schreiben race-frei; Lock auto-released bei
   Prozess-Tod (auch kill -9 / os._exit) -> keine verwaisten Locks.
 - Infrastruktur-Fehler (z.B. /tmp nicht schreibbar) blockieren den Bot NICHT.
"""
import os
import fcntl
from datetime import datetime

BASE = "/home/trading2025/trading_bot"
HEALTH_CSV = os.path.join(BASE, "agents", "health_log.csv")

_locks = {}   # name -> offenes File-Handle (am Leben halten = Lock haelt bis Prozessende)


def log(source, event, detail=""):
    """Ein Event append-only ins zentrale Health-Log. Schluckt jeden eigenen Fehler."""
    try:
        os.makedirs(os.path.dirname(HEALTH_CSV), exist_ok=True)
        new = not os.path.exists(HEALTH_CSV)
        line = ",".join([
            datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            str(source), str(event),
            str(detail).replace(",", ";").replace("\n", " ")[:200],
        ])
        with open(HEALTH_CSV, "a") as f:
            fcntl.flock(f, fcntl.LOCK_EX)         # race-frei zwischen Prozessen
            if new:
                f.write("time,source,event,detail\n")
            f.write(line + "\n")
            fcntl.flock(f, fcntl.LOCK_UN)
    except Exception:
        pass   # Logging darf den Bot niemals zum Absturz bringen


def acquire_singleton(name):
    """Exklusiver prozessweiter Lock ueber /tmp/<name>.lock.
    Rueckgabe:
        None        -> schon eine andere Instanz aktiv (Aufrufer soll beenden)
        File-Handle -> Lock erhalten (Handle wird intern gehalten)
        True        -> Lock-Infrastruktur kaputt -> NICHT blockieren, normal laufen
    Auto-Release bei jedem Prozess-Ende (flock-Eigenschaft)."""
    path = "/tmp/" + name + ".lock"
    try:
        fp = open(path, "w")
    except Exception:
        return True   # /tmp nicht nutzbar -> lieber laufen als faelschlich blockieren
    try:
        fcntl.flock(fp, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except (IOError, OSError):
        try:
            fp.close()
        except Exception:
            pass
        return None   # bereits gelockt -> andere Instanz laeuft
    try:
        fp.write(str(os.getpid()) + "\n")
        fp.flush()
    except Exception:
        pass
    _locks[name] = fp     # Handle halten -> Lock bleibt bestehen bis Prozessende
    return fp
