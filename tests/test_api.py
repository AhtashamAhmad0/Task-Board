import json
import os
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ["DB_PATH"] = os.path.join(tempfile.mkdtemp(), "test.db")

import server  # noqa: E402


class ApiTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        server.init_db()
        cls.httpd = server.ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
        cls.port = cls.httpd.server_address[1]
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()

    def call(self, method, path, body=None):
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(
            f"http://127.0.0.1:{self.port}{path}", data=data, method=method,
            headers={"Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(req) as r:
                return r.status, json.loads(r.read())
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read())

    def test_health(self):
        status, body = self.call("GET", "/api/health")
        self.assertEqual((status, body["status"]), (200, "ok"))

    def test_create_update_delete(self):
        status, task = self.call("POST", "/api/tasks", {"title": "Learn Docker", "priority": "high"})
        self.assertEqual(status, 201)
        self.assertEqual(task["status"], "todo")

        task["status"] = "done"
        status, updated = self.call("PUT", f"/api/tasks/{task['id']}", task)
        self.assertEqual((status, updated["status"]), (200, "done"))

        status, _ = self.call("DELETE", f"/api/tasks/{task['id']}")
        self.assertEqual(status, 200)
        status, _ = self.call("DELETE", f"/api/tasks/{task['id']}")
        self.assertEqual(status, 404)

    def test_validation(self):
        self.assertEqual(self.call("POST", "/api/tasks", {"title": ""})[0], 400)
        self.assertEqual(self.call("POST", "/api/tasks", {"title": "x", "status": "bad"})[0], 400)
        self.assertEqual(self.call("POST", "/api/tasks", {"title": "x", "due_date": "nope"})[0], 400)

    def test_stats(self):
        status, body = self.call("GET", "/api/stats")
        self.assertEqual(status, 200)
        self.assertIn("completion", body)


if __name__ == "__main__":
    unittest.main()