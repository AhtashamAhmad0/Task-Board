import json
import mimetypes
import os
import signal
import sqlite3
import sys
import traceback
from contextlib import closing
from datetime import date, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"
DB_PATH = os.getenv("DB_PATH", str(BASE_DIR / "data" / "tasks.db"))
HOST = os.getenv("HOST", "127.0.0.1")
PORT = int(os.getenv("PORT", "8000"))

STATUSES = ("todo", "doing", "done")
PRIORITIES = ("low", "medium", "high")


# ---------- Database ----------
def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)
    with closing(get_conn()) as conn:
        conn.execute(
            """CREATE TABLE IF NOT EXISTS tasks (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                title       TEXT NOT NULL,
                description TEXT NOT NULL DEFAULT '',
                status      TEXT NOT NULL DEFAULT 'todo',
                priority    TEXT NOT NULL DEFAULT 'medium',
                due_date    TEXT,
                created_at  TEXT NOT NULL
            )"""
        )
        conn.commit()


def fetch(sql, params=(), one=False):
    with closing(get_conn()) as conn:
        rows = conn.execute(sql, params).fetchall()
    if one:
        return dict(rows[0]) if rows else None
    return [dict(r) for r in rows]


def execute(sql, params=()):
    """Run a write query. Returns (last inserted id, rows affected)."""
    with closing(get_conn()) as conn:
        cur = conn.execute(sql, params)
        conn.commit()
        return cur.lastrowid, cur.rowcount


# ---------- Validation ----------
def clean(data):
    if not isinstance(data, dict):
        raise ValueError("Body must be a JSON object")

    title = str(data.get("title", "")).strip()
    if not title or len(title) > 100:
        raise ValueError("Title is required (max 100 characters)")

    description = str(data.get("description", "")).strip()
    if len(description) > 500:
        raise ValueError("Description is too long (max 500 characters)")

    status = data.get("status", "todo")
    if status not in STATUSES:
        raise ValueError(f"Status must be one of {STATUSES}")

    priority = data.get("priority", "medium")
    if priority not in PRIORITIES:
        raise ValueError(f"Priority must be one of {PRIORITIES}")

    due = data.get("due_date") or None
    if due:
        try:
            datetime.strptime(due, "%Y-%m-%d")
        except (ValueError, TypeError):
            raise ValueError("due_date must look like 2026-12-31")

    return title, description, status, priority, due


# ---------- HTTP handler ----------
class Handler(BaseHTTPRequestHandler):
    def send_json(self, payload, status=200):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def read_json(self):
        length = int(self.headers.get("Content-Length", 0))
        if length > 100_000:
            raise ValueError("Request body too large")
        raw = self.rfile.read(length) if length else b"{}"
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            raise ValueError("Invalid JSON")

    def serve_static(self, path):
        relative = "index.html" if path in ("", "/") else path.lstrip("/")
        file = (STATIC_DIR / relative).resolve()
        # block path tricks like /../server.py
        if STATIC_DIR not in file.parents or not file.is_file():
            self.send_json({"error": "Not found"}, 404)
            return
        body = file.read_bytes()
        ctype = mimetypes.guess_type(file.name)[0] or "application/octet-stream"
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def route(self, method):
        url = urlparse(self.path)
        parts = [p for p in url.path.split("/") if p]
        try:
            if parts[:1] == ["api"]:
                self.api(method, parts[1:], parse_qs(url.query))
            elif method == "GET":
                self.serve_static(url.path)
            else:
                self.send_json({"error": "Not found"}, 404)
        except ValueError as e:
            self.send_json({"error": str(e)}, 400)
        except Exception:
            traceback.print_exc()
            self.send_json({"error": "Internal server error"}, 500)

    def api(self, method, parts, qs):
        # GET /api/health
        if parts == ["health"] and method == "GET":
            return self.send_json({"status": "ok"})

        # GET /api/stats
        if parts == ["stats"] and method == "GET":
            counts = {s: 0 for s in STATUSES}
            for row in fetch("SELECT status, COUNT(*) AS c FROM tasks GROUP BY status"):
                counts[row["status"]] = row["c"]
            total = sum(counts.values())
            overdue = fetch(
                "SELECT COUNT(*) AS c FROM tasks "
                "WHERE due_date IS NOT NULL AND due_date < ? AND status != 'done'",
                (date.today().isoformat(),),
                one=True,
            )["c"]
            return self.send_json({
                "total": total,
                "by_status": counts,
                "overdue": overdue,
                "completion": round(100 * counts["done"] / total) if total else 0,
            })

        # /api/tasks
        if parts == ["tasks"]:
            if method == "GET":
                sql, params = "SELECT * FROM tasks WHERE 1=1", []
                status = qs.get("status", [""])[0]
                if status:
                    sql += " AND status = ?"
                    params.append(status)
                q = qs.get("q", [""])[0].strip()
                if q:
                    sql += " AND (title LIKE ? OR description LIKE ?)"
                    params += [f"%{q}%", f"%{q}%"]
                sql += (" ORDER BY CASE priority WHEN 'high' THEN 0 "
                        "WHEN 'medium' THEN 1 ELSE 2 END, id DESC")
                return self.send_json(fetch(sql, params))

            if method == "POST":
                title, desc, status, priority, due = clean(self.read_json())
                new_id, _ = execute(
                    "INSERT INTO tasks (title, description, status, priority, due_date, created_at) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (title, desc, status, priority, due, datetime.now().isoformat(timespec="seconds")),
                )
                task = fetch("SELECT * FROM tasks WHERE id = ?", (new_id,), one=True)
                return self.send_json(task, 201)

        # /api/tasks/<id>
        if len(parts) == 2 and parts[0] == "tasks" and parts[1].isdigit():
            task_id = int(parts[1])

            if method == "PUT":
                title, desc, status, priority, due = clean(self.read_json())
                _, changed = execute(
                    "UPDATE tasks SET title=?, description=?, status=?, priority=?, due_date=? WHERE id=?",
                    (title, desc, status, priority, due, task_id),
                )
                if not changed:
                    return self.send_json({"error": "Task not found"}, 404)
                return self.send_json(fetch("SELECT * FROM tasks WHERE id = ?", (task_id,), one=True))

            if method == "DELETE":
                _, changed = execute("DELETE FROM tasks WHERE id = ?", (task_id,))
                if not changed:
                    return self.send_json({"error": "Task not found"}, 404)
                return self.send_json({"deleted": task_id})

        self.send_json({"error": "Not found"}, 404)

    def do_GET(self):
        self.route("GET")

    def do_POST(self):
        self.route("POST")

    def do_PUT(self):
        self.route("PUT")

    def do_DELETE(self):
        self.route("DELETE")


# ---------- Entry point ----------
def main():
    init_db()
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    # lets `docker stop` shut the server down immediately
    signal.signal(signal.SIGTERM, lambda signum, frame: sys.exit(0))
    print(f"Task Board running at http://localhost:{PORT}  (database: {DB_PATH})")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping...")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()