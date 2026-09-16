from __future__ import annotations

import hashlib
import json
import os
import tempfile
import threading
import unittest
from collections import Counter
from pathlib import Path
from unittest import mock

from palimnex import cache_v3, security
from palimnex import core as legacy
from palimnex.tests.fake_redis import FakeRedis
from palimnex.tests.support import write_project


class CacheV3Tests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        write_project(self.root)
        self.client = FakeRedis()

    def _write_and_pin_evaluation(self, document: dict[str, object]) -> None:
        fixture = self.root / "palimnex/evaluation/v25.json"
        raw = (json.dumps(document, sort_keys=True, indent=2) + "\n").encode("utf-8")
        fixture.write_bytes(raw)
        config_path = self.root / ".palimnex.json"
        config = json.loads(config_path.read_text(encoding="utf-8"))
        config["evaluation_fixture_sha256"] = hashlib.sha256(raw).hexdigest()
        config_path.write_text(
            json.dumps(config, sort_keys=True, indent=2) + "\n", encoding="utf-8"
        )
        cache_v3.build_index(self.client, self.root)

    def test_source_pointer_cache_rehydrates_exact_current_source(self) -> None:
        old_active = f"{legacy.namespace(self.root)}:active-generation"
        old_extra = f"{legacy.namespace(self.root)}:generation:preserve:chunk:one"
        self.client.values[old_active] = b"legacy-manifest-marker"
        self.client.values[old_extra] = b"legacy-source-record"

        built = cache_v3.build_index(self.client, self.root)
        self.assertGreater(built["manifest"]["chunk_count"], 0)
        self.assertTrue(built["legacy_namespace_preserved"])
        self.assertEqual(self.client.values[old_extra], b"legacy-source-record")

        phrase = b"cobalt orchard recovery rule"
        v3_prefix = cache_v3.namespace(self.root) + ":chunk:"
        for key, raw in self.client.values.items():
            if not key.startswith(v3_prefix):
                continue
            payload = json.loads(raw)
            self.assertNotIn("text", payload)
            self.assertNotIn("tokens", payload)
            self.assertNotIn(phrase, raw.lower())
        self.assertNotIn(phrase, self.client.all_stored_bytes().lower())

        result = cache_v3.search(self.client, "cobalt orchard recovery", 5, self.root)
        self.assertEqual(result["results"][0]["path"], "docs/alpha.md")
        self.assertIn("cobalt orchard recovery rule", result["results"][0]["text"].lower())
        valid, passed = cache_v3.validate(self.client, self.root, deep=True)
        self.assertTrue(passed, valid)
        (self.root / "docs/alpha.md").write_text(
            "# Changed\n\nsource no longer matches the active generation\n", encoding="utf-8"
        )
        with self.assertRaisesRegex(ValueError, "cache is stale"):
            cache_v3.search(self.client, "cobalt orchard recovery", 5, self.root)

    def test_status_is_compact_unless_verbose(self) -> None:
        cache_v3.build_index(self.client, self.root)
        compact, fresh = cache_v3.status(self.client, self.root)
        self.assertTrue(fresh)
        self.assertNotIn("files", compact["manifest"])
        self.assertNotIn("chunk_keys", compact["manifest"])
        verbose, fresh = cache_v3.status(self.client, self.root, verbose=True)
        self.assertTrue(fresh)
        self.assertIn("files", verbose["manifest"])
        self.assertIn("chunk_keys", verbose["manifest"])

    def test_policy_digest_change_invalidates_reuse(self) -> None:
        first_policy = cache_v3.index_policy_digest(self.root)
        cache_v3.build_index(self.client, self.root)
        with mock.patch.object(cache_v3, "TOKENIZER_ID", "test-changed-tokenizer:v999"):
            second_policy = cache_v3.index_policy_digest(self.root)
            self.assertNotEqual(first_policy, second_policy)
            status, fresh = cache_v3.status(self.client, self.root)
            self.assertFalse(fresh)
            self.assertEqual(status["status"], "missing_or_invalid")
            rebuilt = cache_v3.build_index(self.client, self.root)
            self.assertEqual(rebuilt["manifest"]["index_policy_digest"], second_policy)
            self.assertEqual(rebuilt["metrics"]["chunks"]["reused"], 0)

    def _active_chunk_records_for(self, relative: str) -> list[dict[str, object]]:
        manifest = cache_v3._load_manifest(
            self.client,
            cache_v3._active_manifest_key(self.client, self.root),
            self.root,
        )
        self.assertIsNotNone(manifest)
        records = []
        for key in manifest["file_chunks"][relative]:
            payload = json.loads(self.client.values[key])
            self.assertEqual(payload["path"], relative)
            records.append(payload)
        return records

    def test_reused_chunk_file_hash_refreshes_after_edit(self) -> None:
        alpha = self.root / "docs/alpha.md"
        stable = "\n".join(
            f"stable cobalt orchard recovery line {index:03d}." for index in range(1, 81)
        )
        alpha.write_text(stable + "\nmutable tail one\n", encoding="utf-8")
        cache_v3.build_index(self.client, self.root)
        first_digest = hashlib.sha256(alpha.read_bytes()).hexdigest()
        first_chunks = self._active_chunk_records_for("docs/alpha.md")
        self.assertGreater(len(first_chunks), 1)
        unchanged_id = min(first_chunks, key=lambda item: item["start_line"])["id"]
        self.assertTrue(
            all(item["file_hash"] == first_digest for item in first_chunks)
        )

        alpha.write_text(stable + "\nmutable tail two\n", encoding="utf-8")
        second_digest = hashlib.sha256(alpha.read_bytes()).hexdigest()
        self.assertNotEqual(first_digest, second_digest)
        rebuilt = cache_v3.build_index(self.client, self.root)
        self.assertGreater(rebuilt["metrics"]["chunks"]["generated"], 0)
        status, passed = cache_v3.validate(self.client, self.root, deep=True)
        self.assertTrue(passed, status)
        refreshed = self._active_chunk_records_for("docs/alpha.md")
        self.assertTrue(all(item["file_hash"] == second_digest for item in refreshed))
        self.assertIn(unchanged_id, {item["id"] for item in refreshed})
        unchanged = next(item for item in refreshed if item["id"] == unchanged_id)
        self.assertEqual(unchanged["file_hash"], second_digest)

    def test_repair_deep_refreshes_stale_file_hash_on_reused_chunks(self) -> None:
        alpha = self.root / "docs/alpha.md"
        stable = "\n".join(
            f"stable cobalt orchard recovery line {index:03d}." for index in range(1, 81)
        )
        alpha.write_text(stable + "\nmutable tail one\n", encoding="utf-8")
        cache_v3.build_index(self.client, self.root)
        first_digest = hashlib.sha256(alpha.read_bytes()).hexdigest()
        alpha.write_text(stable + "\nmutable tail two\n", encoding="utf-8")
        second_digest = hashlib.sha256(alpha.read_bytes()).hexdigest()
        cache_v3.build_index(self.client, self.root)
        prefix = cache_v3.namespace(self.root) + ":chunk:"
        stale_keys = 0
        for key, raw in list(self.client.values.items()):
            if not key.startswith(prefix):
                continue
            payload = json.loads(raw)
            if payload.get("path") != "docs/alpha.md":
                continue
            payload["file_hash"] = first_digest
            self.client.values[key] = json.dumps(
                payload, sort_keys=True, separators=(",", ":")
            ).encode("utf-8")
            stale_keys += 1
        self.assertGreater(stale_keys, 0)
        status, passed = cache_v3.validate(self.client, self.root, deep=True)
        self.assertFalse(passed, status)
        repaired = cache_v3.build_index(self.client, self.root, repair_deep=True)
        self.assertGreater(repaired["metrics"]["chunks"]["generated"], 0)
        status, passed = cache_v3.validate(self.client, self.root, deep=True)
        self.assertTrue(passed, status)
        self.assertTrue(
            all(
                item["file_hash"] == second_digest
                for item in self._active_chunk_records_for("docs/alpha.md")
            )
        )

    def test_scanner_v2_identity_and_digest_are_bound_to_cache_validity(self) -> None:
        self.assertEqual(security.SCANNER_VERSION, "content-privacy:v2")
        scanner_digest = security.policy_digest()
        self.assertRegex(scanner_digest, r"^[0-9a-f]{64}$")
        cache_v3.build_index(self.client, self.root)
        manifest = cache_v3._load_manifest(
            self.client,
            cache_v3._active_manifest_key(self.client, self.root),
            self.root,
        )
        self.assertIsNotNone(manifest)
        self.assertEqual(
            manifest["scanner_policy_digest"], scanner_digest
        )

        with mock.patch.object(
            security, "SCANNER_VERSION", "content-privacy:v2-test-change"
        ):
            self.assertNotEqual(security.policy_digest(), scanner_digest)
            status, fresh = cache_v3.status(self.client, self.root)
            self.assertFalse(fresh)
            self.assertEqual(status["status"], "missing_or_invalid")

    @unittest.skipUnless(hasattr(os, "O_NOFOLLOW"), "platform has no O_NOFOLLOW")
    def test_source_snapshot_refuses_symlink_even_if_discovery_is_raced(self) -> None:
        target = self.root / "real.md"
        target.write_text("safe content\n", encoding="utf-8")
        link = self.root / "raced.md"
        link.symlink_to(target)
        with mock.patch.object(legacy, "included_files", return_value=[link]):
            with self.assertRaisesRegex(ValueError, "cannot safely open"):
                cache_v3.source_snapshot(self.root)

    @unittest.skipUnless(hasattr(os, "O_NOFOLLOW"), "platform has no O_NOFOLLOW")
    def test_source_snapshot_refuses_symlinked_parent_directory(self) -> None:
        real = self.root / "real-parent"
        real.mkdir()
        (real / "document.md").write_text("safe content\n", encoding="utf-8")
        alias = self.root / "linked-parent"
        alias.symlink_to(real, target_is_directory=True)
        raced = alias / "document.md"
        with mock.patch.object(legacy, "included_files", return_value=[raced]):
            with self.assertRaisesRegex(ValueError, "cannot safely open"):
                cache_v3.source_snapshot(self.root)

    def test_expired_writer_cannot_mutate_or_activate(self) -> None:
        target = f"{cache_v3.namespace(self.root)}:must-remain-absent"
        retained = f"{cache_v3.namespace(self.root)}:must-remain-present"
        self.client.values[retained] = b"preserved"
        with cache_v3._writer_lock(self.client, self.root) as owner:
            self.client.execute("DEL", f"{cache_v3.namespace(self.root)}:index-lock")
            with self.assertRaisesRegex(ValueError, "ownership was lost"):
                cache_v3._fenced_set(self.client, self.root, owner, target, "forbidden")
            with self.assertRaisesRegex(ValueError, "ownership was lost"):
                cache_v3._activate(self.client, self.root, owner, target)
            with self.assertRaisesRegex(ValueError, "ownership was lost"):
                cache_v3._fenced_delete(self.client, self.root, owner, [retained])
        self.assertIsNone(self.client.execute("GET", target))
        self.assertEqual(self.client.execute("GET", retained), b"preserved")
        self.assertIsNone(
            self.client.execute("GET", f"{cache_v3.namespace(self.root)}:active-generation")
        )

    def test_reader_lease_prevents_generation_gc_then_release_allows_it(self) -> None:
        with mock.patch.object(cache_v3, "GENERATION_RETENTION", 1), mock.patch.object(
            cache_v3, "GENERATION_GRACE_MS", 0
        ):
            cache_v3.build_index(self.client, self.root)
            active_key = f"{cache_v3.namespace(self.root)}:active-generation"
            old_manifest = self.client.execute("GET", active_key).decode()
            with cache_v3.generation_reader(self.client, self.root) as manifest:
                lease_key = manifest["_reader_lease_key"]
                self.assertEqual(int(self.client.execute("GET", lease_key)), 1)
                alpha = self.root / "docs/alpha.md"
                alpha.write_text(alpha.read_text() + "second generation\n", encoding="utf-8")
                cache_v3.build_index(self.client, self.root)
                self.assertIsNotNone(self.client.execute("GET", old_manifest))
                self.assertEqual(int(self.client.execute("GET", lease_key)), 1)
            self.assertIsNone(self.client.execute("GET", lease_key))
            alpha = self.root / "docs/alpha.md"
            alpha.write_text(alpha.read_text() + "third generation\n", encoding="utf-8")
            cache_v3.build_index(self.client, self.root)
            self.assertIsNone(self.client.execute("GET", old_manifest))

    def test_evaluation_computes_exact_recall_mrr_forbidden_and_critical(self) -> None:
        cache_v3.build_index(self.client, self.root)
        result = cache_v3.evaluate(self.client, 5, self.root)
        self.assertEqual(result["cases"], 20)
        self.assertEqual(result["recall_at_limit"], 1.0)
        self.assertEqual(result["mrr"], 1.0)
        self.assertTrue(result["critical_passed"])
        self.assertEqual(result["status"], "passed")

        fixture = self.root / "palimnex/evaluation/v25.json"
        document = json.loads(fixture.read_text(encoding="utf-8"))
        document["cases"][0]["expected_paths"] = ["docs/never.md"]
        document["cases"][0]["critical"] = False
        self._write_and_pin_evaluation(document)
        result = cache_v3.evaluate(self.client, 5, self.root)
        self.assertAlmostEqual(result["recall_at_limit"], 0.95)
        self.assertAlmostEqual(result["mrr"], 0.95)
        self.assertTrue(result["critical_passed"])
        self.assertEqual(result["status"], "passed")

        for case in document["cases"]:
            case["forbidden_paths"] = ["docs/forbidden-only.md"]
        document["cases"][1]["forbidden_paths"] = ["docs/beta.md"]
        document["cases"][1]["critical"] = True
        beta = self.root / "docs/beta.md"
        beta.write_text(
            beta.read_text(encoding="utf-8")
            + "\nThe cobalt orchard recovery rule is also mentioned here.\n",
            encoding="utf-8",
        )
        self._write_and_pin_evaluation(document)
        result = cache_v3.evaluate(self.client, 5, self.root)
        self.assertFalse(result["critical_passed"])
        self.assertEqual(result["outcomes"][1]["forbidden_hits"], ["docs/beta.md"])
        self.assertEqual(result["status"], "failed")

    def test_noncritical_forbidden_hit_fails_the_aggregate_evaluation(self) -> None:
        cache_v3.build_index(self.client, self.root)
        fixture = self.root / "palimnex/evaluation/v25.json"
        document = json.loads(fixture.read_text(encoding="utf-8"))
        target = document["cases"][1]
        self.assertFalse(target["critical"])
        for case in document["cases"]:
            case["forbidden_paths"] = ["docs/never.md"]
        target["forbidden_paths"] = ["docs/beta.md"]
        beta = self.root / "docs/beta.md"
        beta.write_text(
            beta.read_text(encoding="utf-8")
            + "\nThe cobalt orchard recovery rule is also mentioned here.\n",
            encoding="utf-8",
        )
        self._write_and_pin_evaluation(document)

        result = cache_v3.evaluate(self.client, 5, self.root)

        self.assertEqual(result["recall_at_limit"], 1.0)
        self.assertTrue(result["critical_passed"])
        self.assertFalse(result["forbidden_clear"])
        self.assertEqual(result["outcomes"][1]["forbidden_hits"], ["docs/beta.md"])
        self.assertEqual(result["status"], "failed")

    def test_evaluation_refuses_frozen_fixture_digest_drift(self) -> None:
        cache_v3.build_index(self.client, self.root)
        fixture = self.root / "palimnex/evaluation/v25.json"
        document = json.loads(fixture.read_text(encoding="utf-8"))
        document["description"] += " Mutated after its digest was pinned."
        fixture.write_text(json.dumps(document), encoding="utf-8")

        with self.assertRaisesRegex(ValueError, "digest differs"):
            cache_v3.evaluate(self.client, 5, self.root)

    def test_clear_removes_only_registered_v3_keys_and_preserves_v2(self) -> None:
        old_key = f"{legacy.namespace(self.root)}:sentinel"
        self.client.values[old_key] = b"preserve-v2"
        cache_v3.build_index(self.client, self.root)
        result = cache_v3.clear(self.client, self.root)
        self.assertTrue(result["verified_registered_keys_empty"])
        self.assertFalse(result["legacy_namespace_touched"])
        self.assertEqual(self.client.values[old_key], b"preserve-v2")
        self.assertFalse(any(key.startswith(cache_v3.namespace(self.root) + ":") for key in self.client.values))
        self.assertFalse(any(key.startswith(cache_v3.namespace(self.root) + ":") for key in self.client.hashes))

    def test_clear_reader_admission_barrier_never_deletes_a_leased_generation(self) -> None:
        cache_v3.build_index(self.client, self.root)
        prefix = cache_v3.namespace(self.root)
        active_key = f"{prefix}:active-generation"
        active_manifest = self.client.execute("GET", active_key)
        self.assertIsNotNone(active_manifest)
        retained_values = {
            key: value
            for key, value in self.client.values.items()
            if key.startswith(prefix + ":generation:")
        }
        retained_hashes = {
            key: dict(value)
            for key, value in self.client.hashes.items()
            if key.startswith(prefix + ":generation:")
        }

        # A reader admitted before pointer detachment owns a lease. Clear must
        # restore the pointer and leave every generation byte intact.
        with cache_v3.generation_reader(self.client, self.root) as manifest:
            self.assertIsNotNone(manifest)
            with self.assertRaisesRegex(ValueError, "active readers"):
                cache_v3.clear(self.client, self.root)
            self.assertEqual(self.client.execute("GET", active_key), active_manifest)
            self.assertEqual(
                {
                    key: value
                    for key, value in self.client.values.items()
                    if key.startswith(prefix + ":generation:")
                },
                retained_values,
            )
            self.assertEqual(
                {
                    key: value
                    for key, value in self.client.hashes.items()
                    if key.startswith(prefix + ":generation:")
                },
                retained_hashes,
            )

        # Pause clear immediately after it atomically detaches the admission
        # pointer. A racing reader must observe no generation and acquire no
        # lease; only then may clear delete the registered generation.
        detached = threading.Event()
        resume_clear = threading.Event()
        outcome: list[object] = []
        real_fenced_delete = cache_v3._fenced_delete

        def pausing_delete(client, root, owner, keys):
            deleted = real_fenced_delete(client, root, owner, keys)
            if keys == [active_key]:
                detached.set()
                if not resume_clear.wait(5):
                    raise AssertionError("test did not release paused clear")
            return deleted

        def run_clear() -> None:
            try:
                outcome.append(cache_v3.clear(self.client, self.root))
            except BaseException as exc:  # surfaced in the test thread below
                outcome.append(exc)

        with mock.patch.object(cache_v3, "_fenced_delete", side_effect=pausing_delete):
            worker = threading.Thread(target=run_clear, daemon=True)
            worker.start()
            self.assertTrue(detached.wait(5), "clear did not detach the active pointer")
            try:
                with cache_v3.generation_reader(self.client, self.root) as manifest:
                    self.assertIsNone(manifest)
                self.assertFalse(
                    any(key.startswith(f"{prefix}:reader-lease:") for key in self.client.values)
                )
            finally:
                resume_clear.set()
            worker.join(5)

        self.assertFalse(worker.is_alive(), "clear did not finish")
        self.assertEqual(len(outcome), 1)
        if isinstance(outcome[0], BaseException):
            raise outcome[0]
        self.assertEqual(outcome[0]["status"], "cleared")
        self.assertIsNone(self.client.execute("GET", active_key))
        self.assertIsNone(self.client.execute("GET", active_manifest.decode("utf-8")))
        self.assertFalse(
            any(key.startswith(f"{prefix}:reader-lease:") for key in self.client.values)
        )

    def test_search_fetches_no_more_than_the_bounded_chunk_candidates(self) -> None:
        documents = {
            f"docs/item-{index:03d}.md": (
                f"# Item {index}\n\nneedlecommon bounded candidate document {index}.\n"
            )
            for index in range(cache_v3.MAX_CANDIDATES + 8)
        }
        write_project(self.root, documents)
        self.client = FakeRedis()
        cache_v3.build_index(self.client, self.root)
        self.client.commands.clear()
        result = cache_v3.search(self.client, "needlecommon", 5, self.root)
        self.assertEqual(len(result["results"]), 5)
        prefix = cache_v3.namespace(self.root) + ":chunk:"
        fetched_chunks = [
            argument
            for command in self.client.commands
            if command[0] == "MGET"
            for argument in command[1:]
            if FakeRedis._text(argument).startswith(prefix)
        ]
        self.assertEqual(len(fetched_chunks), cache_v3.MAX_CANDIDATES)

    def test_search_refuses_valid_format_posting_poisoning(self) -> None:
        cache_v3.build_index(self.client, self.root)
        clean = cache_v3.search(
            self.client, "cobalt orchard recovery", 5, self.root
        )
        self.assertEqual(clean["results"][0]["path"], "docs/alpha.md")
        manifest = cache_v3._load_manifest(
            self.client,
            cache_v3._active_manifest_key(self.client, self.root),
            self.root,
        )
        self.assertIsNotNone(manifest)
        posting_key = manifest["posting_hash_key"]
        baseline = dict(self.client.hashes[posting_key])
        term_key = cache_v3._term_digest_key(self.root)
        required_term = cache_v3.token_digest("cobalt", self.root, key=term_key)
        absent_term = cache_v3.token_digest(
            "absentpostingcanary", self.root, key=term_key
        )
        other_key = next(
            key
            for key in manifest["chunk_keys"]
            if json.loads(self.client.values[key])["path"] == "docs/beta.md"
        )
        other_chunk = json.loads(self.client.values[other_key])
        other_record = [
            (other_chunk["id"], 1, other_chunk["term_count"])
        ]

        poisoned_required = cache_v3._encode_posting(required_term, other_record)
        self.assertIsNotNone(
            cache_v3._decode_posting(poisoned_required, required_term)
        )
        self.client.hashes[posting_key] = dict(baseline)
        self.client.hashes[posting_key][required_term] = poisoned_required
        with self.assertRaisesRegex(ValueError, "differs from source"):
            cache_v3.search(self.client, "cobalt", 5, self.root)

        poisoned_absent = cache_v3._encode_posting(absent_term, other_record)
        self.assertIsNotNone(cache_v3._decode_posting(poisoned_absent, absent_term))
        self.client.hashes[posting_key] = dict(baseline)
        self.client.hashes[posting_key][absent_term] = poisoned_absent
        with self.assertRaisesRegex(ValueError, "differs from source"):
            cache_v3.search(self.client, "absentpostingcanary", 5, self.root)

        self.client.hashes[posting_key] = dict(baseline)
        self.client.hashes[posting_key].pop(required_term)
        with self.assertRaisesRegex(ValueError, "posting is missing"):
            cache_v3.search(self.client, "cobalt", 5, self.root)

        self.client.hashes[posting_key] = baseline
        restored = cache_v3.search(
            self.client, "cobalt orchard recovery", 5, self.root
        )
        self.assertEqual(restored["results"][0]["path"], "docs/alpha.md")

    def test_v3_cache_payload_is_measured_against_v2_and_contains_no_source_text(self) -> None:
        repeated = (
            "cobalt orchard deterministic recovery cursor hashlock timeout watcher\n" * 1_000
        )
        write_project(self.root, {"docs/large.md": repeated})
        old_client = FakeRedis()
        new_client = FakeRedis()
        legacy.build_index(old_client, self.root)
        cache_v3.build_index(new_client, self.root)

        def namespace_bytes(client: FakeRedis, prefix: str) -> int:
            strings = sum(
                len(key.encode("utf-8")) + len(value)
                for key, value in client.values.items()
                if key.startswith(prefix)
            )
            hashes = sum(
                len(key.encode("utf-8"))
                + sum(len(field.encode("ascii")) + len(value) for field, value in fields.items())
                for key, fields in client.hashes.items()
                if key.startswith(prefix)
            )
            return strings + hashes

        old_bytes = namespace_bytes(old_client, legacy.namespace(self.root))
        new_bytes = namespace_bytes(new_client, cache_v3.namespace(self.root))
        self.assertGreater(old_bytes, 0)
        self.assertGreater(new_bytes, 0)
        self.assertLessEqual(
            new_bytes / old_bytes,
            0.60,
            {"v2_bytes": old_bytes, "v3_bytes": new_bytes},
        )
        self.assertIn(repeated.splitlines()[0].encode(), old_client.all_stored_bytes())
        self.assertNotIn(repeated.splitlines()[0].encode(), new_client.all_stored_bytes())

    def test_graph_v2_compression_and_decode_corruption_fail_closed(self) -> None:
        cache_v3.build_index(self.client, self.root)
        manifest_key = cache_v3._active_manifest_key(self.client, self.root)
        manifest = cache_v3._load_manifest(self.client, manifest_key, self.root)
        self.assertIsNotNone(manifest)
        graph_key = manifest["file_graphs"]["docs/alpha.md"]
        original = self.client.values[graph_key]
        magic, logical_size, digest = cache_v3.GRAPH_HEADER.unpack_from(original)
        compressed = original[cache_v3.GRAPH_HEADER.size :]
        digest_tamper = bytearray(original)
        digest_tamper[cache_v3.GRAPH_HEADER.size - 1] ^= 1
        variants = {
            "truncated-zlib": original[:-1],
            "invalid-zlib": cache_v3.GRAPH_HEADER.pack(
                magic, logical_size, digest
            ) + b"not-a-zlib-stream",
            "logical-size-mismatch": cache_v3.GRAPH_HEADER.pack(
                magic, logical_size + 1, digest
            ) + compressed,
            "digest-mismatch": bytes(digest_tamper),
            "trailing-compressed-data": original + b"trailing",
        }

        for name, corrupted in variants.items():
            with self.subTest(name=name):
                self.client.values[graph_key] = corrupted
                self.assertIsNone(cache_v3._decode_graph_payload(corrupted))
                with self.assertRaisesRegex(ValueError, "malformed graph"):
                    cache_v3.validate(self.client, self.root, deep=True)
                with self.assertRaisesRegex(ValueError, "malformed graph"):
                    cache_v3.search(
                        self.client, "cobalt orchard recovery", 5, self.root
                    )
                self.client.values[graph_key] = original

        valid, passed = cache_v3.validate(self.client, self.root, deep=True)
        self.assertTrue(passed, valid)

    def test_known_path_graph_identity_survives_deep_validation_and_reindex(self) -> None:
        decision_path = self.root / "docs/decision.md"
        target_path = self.root / "docs/target.md"
        decision_path.write_text(
            "# Decision\n\n[Root target](docs/target.md)\n"
            "[Relative target](target.md)\n",
            encoding="utf-8",
        )
        target_path.write_text("# Target\n", encoding="utf-8")

        cache_v3.build_index(self.client, self.root)
        first_manifest = cache_v3._load_manifest(
            self.client,
            cache_v3._active_manifest_key(self.client, self.root),
            self.root,
        )
        self.assertIsNotNone(first_manifest)
        first_key = first_manifest["file_graphs"]["docs/decision.md"]
        first_payload = cache_v3._decode_graph_payload(self.client.values[first_key])
        self.assertIsNotNone(first_payload)
        link_targets = [
            edge["target"]
            for edge in first_payload["graph"]["edges"]
            if edge["kind"] == "links_to"
        ]
        self.assertEqual(
            link_targets,
            ["document:docs/target.md", "document:docs/target.md"],
        )
        state, fresh = cache_v3.validate(self.client, self.root, deep=True)
        self.assertTrue(fresh, state)

        unchanged = cache_v3.build_index(self.client, self.root)
        unchanged_manifest = cache_v3._load_manifest(
            self.client,
            cache_v3._active_manifest_key(self.client, self.root),
            self.root,
        )
        self.assertEqual(
            unchanged_manifest["file_graphs"]["docs/decision.md"], first_key
        )
        self.assertEqual(unchanged["metrics"]["graphs"]["generated"], 0)

        decision_path.write_text(
            "# Decision\n\n[Relative target after edit](target.md)\n",
            encoding="utf-8",
        )
        changed = cache_v3.build_index(self.client, self.root)
        changed_manifest = cache_v3._load_manifest(
            self.client,
            cache_v3._active_manifest_key(self.client, self.root),
            self.root,
        )
        changed_key = changed_manifest["file_graphs"]["docs/decision.md"]
        self.assertNotEqual(changed_key, first_key)
        self.assertGreaterEqual(changed["metrics"]["graphs"]["generated"], 1)
        changed_payload = cache_v3._decode_graph_payload(
            self.client.values[changed_key]
        )
        self.assertEqual(
            [
                edge["target"]
                for edge in changed_payload["graph"]["edges"]
                if edge["kind"] == "links_to"
            ],
            ["document:docs/target.md"],
        )
        state, fresh = cache_v3.validate(self.client, self.root, deep=True)
        self.assertTrue(fresh, state)

    def test_migration_size_counts_all_retained_generations_and_shared_keys_once(self) -> None:
        legacy.build_index(self.client, self.root)
        clock = 0

        def deterministic_clock() -> int:
            nonlocal clock
            clock += 1_000_000
            return clock

        self.client.commands.clear()
        with mock.patch.object(
            cache_v3.time, "perf_counter_ns", side_effect=deterministic_clock
        ), mock.patch.object(
            cache_v3, "MIGRATION_SIZE_RATIO_MAX", 10.0
        ), mock.patch.object(
            cache_v3, "MIGRATION_P95_RATIO_MAX", 2.0
        ):
            result = cache_v3.migration_shadow(self.client, self.root)

        registry = cache_v3._registry(self.client, self.root, required=True)
        complete = [
            generation
            for generation in registry["generations"]
            if generation["state"] == "complete"
        ]
        self.assertEqual(len(complete), cache_v3.GENERATION_RETENTION)
        self.assertEqual(result["retained_generations_measured"], len(complete))
        prefix = cache_v3.namespace(self.root)
        expected = {f"{prefix}:active-generation", f"{prefix}:registry"}
        referenced = Counter()
        for generation in complete:
            expected.add(generation["manifest_key"])
            for field in ("chunk_keys", "graph_keys", "posting_keys"):
                expected.update(generation[field])
                referenced.update(generation[field])
        self.assertTrue(
            any(count > 1 for count in referenced.values()),
            "controlled retained generations should share immutable records",
        )
        owned = cache_v3._v3_owned_keys(self.client, self.root)
        self.assertEqual(owned, sorted(expected))

        measured_keys = [
            FakeRedis._text(command[2])
            for command in self.client.commands
            if command[0] == "MEMORY"
            and FakeRedis._text(command[2]).startswith(prefix + ":")
        ]
        self.assertEqual(Counter(measured_keys), Counter({key: 1 for key in owned}))

        self.client.commands.clear()
        independently_measured = cache_v3._redis_memory_bytes(self.client, owned)
        self.assertEqual(
            independently_measured, result["size_gate"]["v3_total_retained_bytes"]
        )
        self.assertEqual(
            Counter(
                FakeRedis._text(command[2])
                for command in self.client.commands
                if command[0] == "MEMORY"
            ),
            Counter({key: 1 for key in owned}),
        )

    def test_legacy_comparison_requires_expected_paths_on_both_backends(self) -> None:
        cases = [
            {
                "id": "controlled-00",
                "mode": "search",
                "query": "cobalt orchard recovery",
                "expected_paths": ["docs/alpha.md"],
                "forbidden_paths": ["docs/beta.md"],
                "limit": 5,
                "critical": True,
            }
        ]
        self.assertEqual(
            cache_v3._legacy_comparison_status(
                [
                    {
                        "id": "controlled-00",
                        "legacy_paths": ["docs/alpha.md", "docs/other.md"],
                        "v3_paths": ["docs/alpha.md"],
                    }
                ],
                cases,
            ),
            "passed",
        )
        self.assertEqual(
            cache_v3._legacy_comparison_status(
                [
                    {
                        "id": "controlled-00",
                        "legacy_paths": ["docs/beta.md"],
                        "v3_paths": ["docs/other.md"],
                    }
                ],
                cases,
            ),
            "failed",
        )
        self.assertEqual(
            cache_v3._legacy_comparison_status(
                [
                    {
                        "id": "controlled-00",
                        "legacy_paths": [],
                        "v3_paths": ["docs/alpha.md"],
                    }
                ],
                cases,
            ),
            "failed",
        )
        self.assertEqual(cache_v3._legacy_comparison_status([], cases), "failed")

    def test_evaluate_and_p95_use_shipped_search(self) -> None:
        search_calls: list[str] = []
        original_search = cache_v3.search
        original_legacy_search = legacy.search

        def capture_search(client, query, limit, root=None, **kwargs):
            search_calls.append(query)
            return original_search(client, query, limit, root, **kwargs)

        def capture_legacy_search(client, query, limit, root=None):
            return original_legacy_search(client, query, limit, root)

        with mock.patch.object(
            cache_v3, "search", side_effect=capture_search
        ), mock.patch.object(
            legacy, "search", side_effect=capture_legacy_search
        ), mock.patch.object(
            cache_v3, "MIGRATION_SIZE_RATIO_MAX", 10.0
        ), mock.patch.object(
            cache_v3, "MIGRATION_P95_RATIO_MAX", 2.0
        ):
            cache_v3.build_index(self.client, self.root)
            evaluated = cache_v3.evaluate(self.client, 5, self.root)
            self.assertEqual(evaluated["status"], "passed")
            evaluate_calls = list(search_calls)
            self.assertGreaterEqual(len(evaluate_calls), 20)
            search_calls.clear()
            legacy.build_index(self.client, self.root)
            result = cache_v3.migration_shadow(self.client, self.root)

        self.assertEqual(result["status"], "passed")
        self.assertEqual(
            result["latency_gate"]["boundary"],
            "shipped search() on both backends over the same deep-validated corpus",
        )
        self.assertGreater(len(search_calls), 0)
        self.assertIsNone(getattr(cache_v3, "_v3_hot_search", None))

    def test_repo_like_migration_hard_fails_size_or_p95_threshold(self) -> None:
        documents = {
            f"docs/modules/component-{index:03d}.md": (
                f"# Component {index}\n\n"
                f"Decision: retain cursor-{index:03d} with bounded recovery.\n\n"
                f"[Runbook](../runbook-{index % 7}.md#restore)\n\n"
                "| field | value |\n| --- | --- |\n"
                f"| component | {index:03d} |\n"
            )
            for index in range(48)
        }
        write_project(self.root, documents)
        legacy.build_index(self.client, self.root)

        def run_with_thresholds(size_maximum: float, latency_maximum: float):
            clock = 0

            def deterministic_clock() -> int:
                nonlocal clock
                clock += 1_000_000
                return clock

            with mock.patch.object(
                cache_v3.time, "perf_counter_ns", side_effect=deterministic_clock
            ), mock.patch.object(
                cache_v3, "MIGRATION_SIZE_RATIO_MAX", size_maximum
            ), mock.patch.object(
                cache_v3, "MIGRATION_P95_RATIO_MAX", latency_maximum
            ):
                return cache_v3.migration_shadow(self.client, self.root)

        size_failure = run_with_thresholds(0.0, 2.0)
        self.assertEqual(size_failure["status"], "failed")
        self.assertEqual(size_failure["evaluation"]["status"], "passed")
        self.assertFalse(size_failure["size_gate"]["passed"])
        self.assertTrue(size_failure["latency_gate"]["passed"])

        latency_failure = run_with_thresholds(10.0, 0.5)
        self.assertEqual(latency_failure["status"], "failed")
        self.assertEqual(latency_failure["evaluation"]["status"], "passed")
        self.assertTrue(latency_failure["size_gate"]["passed"])
        self.assertFalse(latency_failure["latency_gate"]["passed"])

    def test_migration_shadow_uses_redis_memory_and_hard_gates_promotion(self) -> None:
        legacy.build_index(self.client, self.root)
        legacy_keys = cache_v3._legacy_active_keys(self.client, self.root)
        legacy_digest = cache_v3._string_snapshot_digest(
            self.client, legacy_keys
        )
        clock = 0

        def deterministic_clock() -> int:
            nonlocal clock
            clock += 1_000_000
            return clock

        with mock.patch.object(
            cache_v3.time, "perf_counter_ns", side_effect=deterministic_clock
        ), mock.patch.object(
            cache_v3, "MIGRATION_SIZE_RATIO_MAX", 10.0
        ), mock.patch.object(
            cache_v3, "MIGRATION_P95_RATIO_MAX", 2.0
        ):
            accepted = cache_v3.migration_shadow(self.client, self.root)

        self.assertEqual(accepted["status"], "passed")
        self.assertTrue(accepted["equal_corpus"])
        self.assertTrue(accepted["size_gate"]["passed"])
        self.assertTrue(accepted["latency_gate"]["passed"])
        self.assertEqual(accepted["latency_gate"]["ratio"], 1.0)
        self.assertEqual(
            cache_v3._string_snapshot_digest(self.client, legacy_keys),
            legacy_digest,
        )
        self.assertTrue(
            any(command[:2] == ("MEMORY", "USAGE") for command in self.client.commands)
        )

        clock = 0
        with mock.patch.object(
            cache_v3.time, "perf_counter_ns", side_effect=deterministic_clock
        ), mock.patch.object(
            cache_v3, "MIGRATION_SIZE_RATIO_MAX", 0.000001
        ), mock.patch.object(
            cache_v3, "MIGRATION_P95_RATIO_MAX", 2.0
        ):
            rejected = cache_v3.migration_shadow(self.client, self.root)

        self.assertEqual(rejected["status"], "failed")
        self.assertTrue(rejected["equal_corpus"])
        self.assertFalse(rejected["size_gate"]["passed"])
        self.assertTrue(rejected["latency_gate"]["passed"])
        self.assertEqual(
            cache_v3._string_snapshot_digest(self.client, legacy_keys),
            legacy_digest,
        )


if __name__ == "__main__":
    unittest.main()
