from __future__ import annotations

import contextlib
import io
import json
import os
import socket
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from palimnex import cache_v3
from palimnex import core
from palimnex.tests.fake_redis import FakeRedis
from palimnex.tests.support import write_project


class ActionableErrorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="pmx-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)

    def test_too_long_socket_path_names_the_limit_and_workaround(self) -> None:
        path = "/" + "a" * core.UNIX_SOCKET_PATH_LIMIT
        client = core.RedisClient(f"redis+unix://{path}?db=0")
        with self.assertRaisesRegex(core.RedisError, "PALIMNEX_URL") as raised:
            client.execute("PING")
        self.assertIn(f"{len(path)} bytes", str(raised.exception))
        self.assertNotIn(path, str(raised.exception))

    def test_missing_socket_points_to_the_launcher(self) -> None:
        client = core.RedisClient(f"redis+unix://{self.root}/absent.sock?db=0")
        with self.assertRaisesRegex(core.RedisError, "palimnex redis start"):
            client.execute("PING")

    def test_stale_socket_file_is_reported_as_not_running(self) -> None:
        path = self.root / "stale.sock"
        listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        listener.bind(str(path))
        listener.close()
        os.chmod(path, 0o600)
        client = core.RedisClient(f"redis+unix://{path}?db=0")
        with self.assertRaisesRegex(core.RedisError, "stale socket file"):
            client.execute("PING")

    def test_cache_and_ledger_commands_require_configuration(self) -> None:
        for command in (["status"], ["ledger-status"]):
            errors = io.StringIO()
            with mock.patch.object(core, "ROOT", self.root), contextlib.redirect_stderr(errors):
                code = core.main(command)
            self.assertEqual(code, 1)
            self.assertIn("palimnex init", json.loads(errors.getvalue())["error"])

    def test_cache_built_by_another_version_names_it_and_the_fix(self) -> None:
        write_project(self.root)
        client = FakeRedis()
        cache_v3.build_index(client, self.root)
        active = client.values[f"{cache_v3.namespace(self.root)}:active-generation"]
        key = active.decode("utf-8") if isinstance(active, bytes) else str(active)
        manifest = json.loads(client.values[key])
        manifest["bundle_version"] = "2.6.0-rc.1"
        client.values[key] = json.dumps(manifest).encode("utf-8")

        status, fresh = cache_v3.status(client, self.root)
        self.assertFalse(fresh)
        self.assertEqual(status["status"], "missing_or_invalid")
        self.assertEqual(status["built_by_version"], "2.6.0-rc.1")
        self.assertIn("index --incremental", status["action"])
        with self.assertRaisesRegex(ValueError, "built by Palimnex 2.6.0-rc.1"):
            cache_v3.search(client, "cobalt orchard", 5, self.root)


if __name__ == "__main__":
    unittest.main()
