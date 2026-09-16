from __future__ import annotations

import contextlib
import io
import json
import tempfile
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest import mock

from palimnex import cache_v3
from palimnex import core
from palimnex.tests.fake_redis import FakeRedis
from palimnex.tests.support import PROJECT_ID, write_project


class CacheFeatureModeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        write_project(self.root)

    def _main_patches(self, stack: ExitStack, mode: str, client: FakeRedis) -> None:
        stack.enter_context(mock.patch.object(core, "ROOT", self.root))
        stack.enter_context(mock.patch.object(core, "redis_url_envs", return_value=[]))
        stack.enter_context(
            mock.patch.object(
                core, "configured_redis_url", return_value="redis://127.0.0.1:6379/0"
            )
        )
        stack.enter_context(mock.patch.object(core, "RedisClient", return_value=client))
        stack.enter_context(mock.patch.object(core, "project_config", return_value={}))
        stack.enter_context(
            mock.patch.object(cache_v3, "configured_cache_mode", return_value=mode)
        )
        stack.enter_context(
            mock.patch.object(cache_v3, "project_id", return_value=PROJECT_ID)
        )
        stack.enter_context(
            mock.patch.object(
                core, "durable_ledger_path", return_value=self.root / "memory.sqlite3"
            )
        )
        stack.enter_context(
            mock.patch.object(core, "project_slug", return_value="memory-fixture")
        )

    def _invoke(self, stack: ExitStack, arguments: list[str]) -> tuple[int, dict[str, object]]:
        output = io.StringIO()
        stack.enter_context(contextlib.redirect_stdout(output))
        code = core.main(arguments)
        return code, json.loads(output.getvalue())

    def test_search_dispatches_only_on_mode_on(self) -> None:
        for mode, expected_backend in (
            ("off", "v2"),
            ("shadow", "v2"),
            ("on", "v3"),
        ):
            with self.subTest(mode=mode), ExitStack() as stack:
                client = FakeRedis()
                self._main_patches(stack, mode, client)
                legacy_search = stack.enter_context(
                    mock.patch.object(
                        core,
                        "search",
                        return_value={"query": "dispatch", "results": []},
                    )
                )
                v3_search = stack.enter_context(
                    mock.patch.object(
                        cache_v3,
                        "search",
                        return_value={"query": "dispatch", "results": []},
                    )
                )

                code, result = self._invoke(stack, ["search", "dispatch", "--limit", "3"])

                self.assertEqual(code, 0)
                self.assertEqual(result["cache_mode"], mode)
                self.assertEqual(result["authoritative_backend"], expected_backend)
                self.assertEqual(legacy_search.call_count, int(expected_backend == "v2"))
                self.assertEqual(v3_search.call_count, int(expected_backend == "v3"))

    def test_status_shadow_observes_v3_but_keeps_v2_authoritative(self) -> None:
        for mode in cache_v3.CACHE_MODES:
            with self.subTest(mode=mode), ExitStack() as stack:
                client = FakeRedis()
                self._main_patches(stack, mode, client)
                legacy_status = stack.enter_context(
                    mock.patch.object(
                        core,
                        "status",
                        return_value=({"status": "fresh", "manifest": {}}, True),
                    )
                )
                v3_status = stack.enter_context(
                    mock.patch.object(
                        cache_v3,
                        "status",
                        return_value=({"status": "fresh", "manifest": {}}, True),
                    )
                )

                code, result = self._invoke(stack, ["status"])

                self.assertEqual(code, 0)
                expected_backend = "v3" if mode == "on" else "v2"
                self.assertEqual(result["authoritative_backend"], expected_backend)
                self.assertEqual(legacy_status.call_count, int(mode != "on"))
                self.assertEqual(v3_status.call_count, int(mode in {"shadow", "on"}))
                self.assertEqual("shadow_v3" in result, mode == "shadow")

    def test_index_keeps_v2_current_in_shadow_and_builds_v3_beside_it(self) -> None:
        for mode in cache_v3.CACHE_MODES:
            with self.subTest(mode=mode), ExitStack() as stack:
                client = FakeRedis()
                self._main_patches(stack, mode, client)
                legacy_index = stack.enter_context(
                    mock.patch.object(core, "build_index", return_value={"generation": "v2"})
                )
                v3_index = stack.enter_context(
                    mock.patch.object(
                        cache_v3, "build_index", return_value={"generation": "v3"}
                    )
                )

                code, result = self._invoke(stack, ["index", "--incremental"])

                self.assertEqual(code, 0)
                self.assertEqual(legacy_index.call_count, int(mode in {"off", "shadow"}))
                self.assertEqual(v3_index.call_count, int(mode in {"shadow", "on"}))
                self.assertEqual(
                    result["backend"],
                    "v2+v3-shadow"
                    if mode == "shadow"
                    else ("v3" if mode == "on" else "v2"),
                )
                if mode == "shadow":
                    self.assertEqual(result["authoritative_v2"]["generation"], "v2")
                    self.assertEqual(result["shadow_v3"]["generation"], "v3")

    def test_shadow_reindex_after_source_edit_makes_both_views_fresh(self) -> None:
        client = FakeRedis()
        legacy_build = core.build_index
        v3_build = cache_v3.build_index
        real_project_config = core.project_config
        with ExitStack() as stack:
            self._main_patches(stack, "shadow", client)
            stack.enter_context(
                mock.patch.object(
                    core,
                    "project_config",
                    side_effect=lambda root=core.ROOT: real_project_config(self.root),
                )
            )
            stack.enter_context(
                mock.patch.object(
                    core,
                    "build_index",
                    side_effect=lambda selected, *, repair_deep=False: legacy_build(
                        selected, self.root, repair_deep=repair_deep
                    ),
                )
            )
            stack.enter_context(
                mock.patch.object(
                    cache_v3,
                    "build_index",
                    side_effect=lambda selected, *, repair_deep=False: v3_build(
                        selected, self.root, repair_deep=repair_deep
                    ),
                )
            )
            first_code, first = self._invoke(stack, ["index", "--incremental"])
            self.assertEqual(first_code, 0)
            self.assertEqual(first["backend"], "v2+v3-shadow")

            source = self.root / "docs/alpha.md"
            source.write_text(
                source.read_text(encoding="utf-8") + "\nsource edit for shadow refresh\n",
                encoding="utf-8",
            )
            self.assertFalse(core.status(client, self.root)[1])
            self.assertFalse(cache_v3.status(client, self.root)[1])

            second_code, second = self._invoke(stack, ["index", "--incremental"])
            self.assertEqual(second_code, 0)
            self.assertEqual(second["backend"], "v2+v3-shadow")

        self.assertTrue(core.status(client, self.root)[1])
        self.assertTrue(cache_v3.status(client, self.root)[1])

    def test_off_and_shadow_admission_failure_write_nothing_to_redis(self) -> None:
        canary = "".join(("gh", "p_", "A7b9" * 6))
        canary_bytes = canary.encode("utf-8")
        (self.root / "docs/admission-fixture.md").write_text(
            "# Synthetic admission fixture\n\n" + canary + "\n",
            encoding="utf-8",
        )
        legacy_build = core.build_index
        v3_build = cache_v3.build_index
        real_project_config = core.project_config
        redis_write_commands = {
            "SET",
            "DEL",
            "EVAL",
            "INCR",
            "DECR",
            "PEXPIRE",
        }

        for mode in ("off", "shadow"):
            with self.subTest(mode=mode), ExitStack() as stack:
                client = FakeRedis()
                self._main_patches(stack, mode, client)
                stack.enter_context(
                    mock.patch.object(
                        core,
                        "project_config",
                        side_effect=lambda root=core.ROOT: real_project_config(
                            self.root
                        ),
                    )
                )
                stack.enter_context(
                    mock.patch.object(
                        core,
                        "build_index",
                        side_effect=lambda selected, *, repair_deep=False: legacy_build(
                            selected, self.root, repair_deep=repair_deep
                        ),
                    )
                )
                stack.enter_context(
                    mock.patch.object(
                        cache_v3,
                        "build_index",
                        side_effect=lambda selected, *, repair_deep=False: v3_build(
                            selected, self.root, repair_deep=repair_deep
                        ),
                    )
                )
                stdout = io.StringIO()
                stderr = io.StringIO()
                with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(
                    stderr
                ):
                    code = core.main(["index", "--incremental"])

                self.assertEqual(code, 1)
                self.assertEqual(stdout.getvalue(), "")
                failure = json.loads(stderr.getvalue())
                self.assertEqual(failure["status"], "error")
                self.assertIn("github-token@", failure["error"])
                self.assertNotIn(canary, stderr.getvalue())
                self.assertFalse(
                    [
                        command
                        for command in client.commands
                        if command[0] in redis_write_commands
                    ],
                    client.commands,
                )
                self.assertEqual(client.values, {})
                self.assertEqual(client.hashes, {})
                self.assertEqual(client.streams, {})
                self.assertNotIn(canary_bytes, client.all_stored_bytes())
                self.assertNotIn(canary_bytes, repr(client.commands).encode("utf-8"))

    def test_configured_mode_defaults_off_and_rejects_unknown_values(self) -> None:
        self.assertEqual(cache_v3.configured_cache_mode(self.root), "off")
        config_path = self.root / ".palimnex.json"
        config = json.loads(config_path.read_text(encoding="utf-8"))
        config["cache_mode"] = "unknown"
        config_path.write_text(json.dumps(config), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "off, shadow, on"):
            cache_v3.configured_cache_mode(self.root)

    def test_v24_config_runs_legacy_commands_without_v3_identity_or_ledger(self) -> None:
        config_path = self.root / ".palimnex.json"
        legacy_config = {
            "project_slug": "v24-compatibility-fixture",
            "redis_url_envs": ["PALIMNEX_URL"],
            "include_patterns": [".palimnex.json", "docs/**/*.md"],
            "exclude_directories": ["palimnex"],
            "exclude_paths": [],
            "include_palimnex": False,
        }
        self.assertNotIn("project_id", legacy_config)
        self.assertNotIn("cache_mode", legacy_config)
        config_path.write_text(
            json.dumps(legacy_config, sort_keys=True, indent=2) + "\n",
            encoding="utf-8",
        )
        (self.root / "docs/alpha.md").write_text(
            "# Legacy source\n\nlegacyorchard remains searchable in v2.\n",
            encoding="utf-8",
        )
        client = FakeRedis()
        legacy_build = core.build_index
        legacy_status = core.status
        legacy_search = core.search
        real_project_config = core.project_config

        def invoke(arguments: list[str]) -> tuple[int, dict[str, object]]:
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                code = core.main(arguments)
            return code, json.loads(output.getvalue())

        with ExitStack() as stack:
            stack.enter_context(mock.patch.object(core, "ROOT", self.root))
            stack.enter_context(mock.patch.object(core, "redis_url_envs", return_value=[]))
            stack.enter_context(
                mock.patch.object(
                    core,
                    "configured_redis_url",
                    return_value="redis://127.0.0.1:6379/0",
                )
            )
            stack.enter_context(mock.patch.object(core, "RedisClient", return_value=client))
            stack.enter_context(
                mock.patch.object(
                    core,
                    "project_config",
                    side_effect=lambda root=core.ROOT: real_project_config(self.root),
                )
            )
            stack.enter_context(
                mock.patch.object(
                    core,
                    "build_index",
                    side_effect=lambda selected, *, repair_deep=False: legacy_build(
                        selected, self.root, repair_deep=repair_deep
                    ),
                )
            )
            stack.enter_context(
                mock.patch.object(
                    core,
                    "status",
                    side_effect=lambda selected, root=core.ROOT: legacy_status(
                        selected, self.root
                    ),
                )
            )
            stack.enter_context(
                mock.patch.object(
                    core,
                    "search",
                    side_effect=lambda selected, query, limit, root=core.ROOT: legacy_search(
                        selected, query, limit, self.root
                    ),
                )
            )
            project_id = stack.enter_context(
                mock.patch.object(
                    cache_v3,
                    "project_id",
                    side_effect=AssertionError("v2 command requested a v3 project id"),
                )
            )
            ledger = stack.enter_context(
                mock.patch(
                    "palimnex.durable.MemoryLedger",
                    side_effect=AssertionError("v2 command constructed the durable ledger"),
                )
            )

            index_code, indexed = invoke(["index", "--incremental"])
            status_code, status = invoke(["status"])
            search_code, searched = invoke(["search", "legacyorchard", "--limit", "5"])

        self.assertEqual(index_code, 0)
        self.assertEqual(indexed["cache_mode"], "off")
        self.assertEqual(indexed["backend"], "v2")
        self.assertEqual(status_code, 0)
        self.assertTrue(status["fresh"])
        self.assertEqual(status["authoritative_backend"], "v2")
        self.assertEqual(search_code, 0)
        self.assertEqual(searched["authoritative_backend"], "v2")
        self.assertEqual(searched["results"][0]["path"], "docs/alpha.md")
        project_id.assert_not_called()
        ledger.assert_not_called()


if __name__ == "__main__":
    unittest.main()
