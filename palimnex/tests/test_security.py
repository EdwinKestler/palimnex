from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from palimnex import cache_v3, core, security
from palimnex.tests.fake_redis import FakeRedis
from palimnex.tests.support import write_project


class ContentAdmissionTests(unittest.TestCase):
    @staticmethod
    def _nested_canary() -> str:
        return "".join(("Z7mQ2vN9", "kP4rT8xW", "3cH6sL1y", "B5dF"))

    def test_synthetic_secret_canaries_are_detected_without_echoing_values(self) -> None:
        canaries = {
            "private-key-pem": "-----BEGIN " + "PRIVATE KEY-----",
            "aws-access-key": "AK" + "IA" + "A" * 16,
            "github-token": "gh" + "p_" + "A1b2C3d4E5f6G7h8I9j0K1L2",
            "openai-token": "s" + "k-proj-" + "A1b2C3d4E5f6G7h8I9j0K1L2",
            "jwt": "eyJ" + "A" * 10 + "." + "B" * 10 + "." + "C" * 10,
            "bitcoin-wif": "K" + "1" * 51,
            "private-key-assignment": "private_key=" + "ab" * 32,
            "mnemonic-assignment": "wallet_seed=" + " ".join(["alpha"] * 12),
            "high-entropy-credential-assignment": (
                "service_token=" + "A1b2C3d4E5f6G7h8I9j0K1L2M3N4"
            ),
        }
        for expected, canary in canaries.items():
            with self.subTest(rule=expected):
                findings = security.scan_text(canary)
                self.assertIn(expected, {item.rule for item in findings})
                diagnostic = repr(findings)
                self.assertNotIn(canary, diagnostic)

        variants = (
            ("private-key-pem-variant", "-----BEGIN " + "ENCRYPTED PRIVATE KEY-----"),
            ("aws-access-key", "AS" + "IA" + "B" * 16),
        )
        for expected, canary in variants:
            with self.subTest(rule=expected):
                findings = security.scan_text(canary)
                self.assertIn(expected, {item.rule for item in findings})
                self.assertNotIn(canary, repr(findings))

        for prefix in ("5", "K", "L", "9", "c"):
            with self.subTest(wif_prefix=prefix):
                canary = prefix + "1" * 51
                findings = security.scan_text(canary)
                self.assertIn("bitcoin-wif", {item.rule for item in findings})
                self.assertNotIn(canary, repr(findings))

    def test_allowlist_is_exact_byte_digest_and_invalid_utf8_is_rejected(self) -> None:
        canary = ("AK" + "IA" + "Z" * 16).encode()
        digest = hashlib.sha256(canary).hexdigest()
        self.assertTrue(security.scan_bytes(canary))
        self.assertEqual(security.scan_bytes(canary, allowed_sha256=[digest]), [])
        with self.assertRaises(UnicodeDecodeError):
            security.scan_bytes(b"\xff")

    def test_sensitive_name_matching_does_not_reject_ordinary_identifiers(self) -> None:
        ordinary = "\n".join(
            (
                'token-adapter = { path = "crates/token-adapter" }',
                'TOKENIZER_ID = "unicode-alnum-underscore-lower:v1"',
                'passwordless_mode = "challenge-response-identifier"',
                'seedling_count = "twenty-four-plants-in-the-nursery"',
            )
        )
        self.assertEqual(security.scan_text(ordinary), [])

    def test_index_rejects_before_secret_bytes_can_reach_cache(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            canary = "gh" + "p_" + "A1b2C3d4E5f6G7h8I9j0K1L2"
            write_project(root, {"docs/rejected.md": "credential: " + canary + "\n"})
            client = FakeRedis()
            with self.assertRaisesRegex(ValueError, "content privacy scan rejected") as raised:
                cache_v3.build_index(client, root)
            self.assertNotIn(canary, str(raised.exception))
            self.assertNotIn(canary.encode(), client.all_stored_bytes())

    def test_nested_canonical_json_sensitive_keys_are_rejected_without_echo(self) -> None:
        canary = self._nested_canary()
        for sensitive_key in ("service_token", "api_key"):
            with self.subTest(sensitive_key=sensitive_key):
                raw = json.dumps(
                    {"outer": {"items": [{sensitive_key: canary}]}},
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode("utf-8")
                findings = security.scan_bytes(raw)
                self.assertTrue(findings)
                self.assertTrue(any("credential" in item.rule for item in findings))
                self.assertNotIn(canary, repr(findings))

    def test_nested_json_index_refusal_has_zero_redis_writes_or_canary_echo(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_project(
                root,
                {"docs/alpha.md": "# Safe source\n\nNo credentials are stored here.\n"},
            )
            config_path = root / ".palimnex.json"
            config = json.loads(config_path.read_text(encoding="utf-8"))
            config["include_patterns"].append("docs/**/*.json")
            config_path.write_text(
                json.dumps(config, sort_keys=True, indent=2) + "\n",
                encoding="utf-8",
            )
            canary = self._nested_canary()
            canary_bytes = canary.encode("utf-8")
            source = root / "docs/settings.json"
            source.write_text(
                json.dumps(
                    {"services": [{"credentials": {"service_token": canary}}]},
                    sort_keys=True,
                    separators=(",", ":"),
                ),
                encoding="utf-8",
            )
            self.assertIn(source, core.included_files(root))
            client = FakeRedis()
            with self.assertRaisesRegex(
                ValueError, "content privacy scan rejected"
            ) as raised:
                cache_v3.build_index(client, root)

            self.assertNotIn(canary, str(raised.exception))
            write_commands = {"SET", "DEL", "EVAL", "INCR", "DECR", "PEXPIRE"}
            self.assertFalse(
                [command for command in client.commands if command[0] in write_commands],
                client.commands,
            )
            self.assertNotIn(canary_bytes, client.all_stored_bytes())
            self.assertNotIn(canary_bytes, repr(client.commands).encode("utf-8"))

    def test_deep_json_fails_closed_without_echo_or_redis_writes(self) -> None:
        canary = self._nested_canary()
        sensitive_name = "service_" + "token"
        inner = json.dumps(
            {sensitive_name: [canary]},
            sort_keys=True,
            separators=(",", ":"),
        )
        raw = ("[" * 20_000 + inner + "]" * 20_000).encode("utf-8")
        self.assertLess(len(raw), security.MAX_SCAN_BYTES)

        findings = security.scan_bytes(raw)

        self.assertEqual(
            [(item.rule, item.line) for item in findings],
            [("json-structure-too-deep", 1)],
        )
        self.assertNotIn(canary, repr(findings))

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_project(root, {"docs/alpha.md": "# Safe source\n"})
            config_path = root / ".palimnex.json"
            config = json.loads(config_path.read_text(encoding="utf-8"))
            config["include_patterns"].append("docs/**/*.json")
            config_path.write_text(
                json.dumps(config, sort_keys=True, indent=2) + "\n",
                encoding="utf-8",
            )
            (root / "docs/nested.json").write_bytes(raw)
            client = FakeRedis()

            with self.assertRaisesRegex(
                ValueError, "json-structure-too-deep"
            ) as raised:
                cache_v3.build_index(client, root)

            self.assertNotIn(canary, str(raised.exception))
            self.assertEqual(client.values, {})
            self.assertEqual(client.hashes, {})
            self.assertEqual(client.streams, {})
            self.assertNotIn(canary.encode("utf-8"), client.all_stored_bytes())
            self.assertNotIn(
                canary.encode("utf-8"), repr(client.commands).encode("utf-8")
            )

    def test_duplicate_sensitive_json_array_is_not_hidden_by_placeholder(self) -> None:
        sensitive_name = "wallet_" + "seed"
        words = ["alpha"] * 12
        raw = (
            "{"
            + json.dumps(sensitive_name)
            + ":"
            + json.dumps(words)
            + ","
            + json.dumps(sensitive_name)
            + ":"
            + json.dumps("placeholder")
            + "}"
        ).encode("utf-8")

        findings = security.scan_bytes(raw)

        self.assertIn("mnemonic-assignment", {item.rule for item in findings})
        self.assertNotIn(" ".join(words), repr(findings))

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_project(root, {"docs/alpha.md": "# Safe source\n"})
            config_path = root / ".palimnex.json"
            config = json.loads(config_path.read_text(encoding="utf-8"))
            config["include_patterns"].append("docs/**/*.json")
            config_path.write_text(
                json.dumps(config, sort_keys=True, indent=2) + "\n",
                encoding="utf-8",
            )
            (root / "docs/duplicate.json").write_bytes(raw)
            client = FakeRedis()

            with self.assertRaisesRegex(
                ValueError, "mnemonic-assignment"
            ) as raised:
                cache_v3.build_index(client, root)

            self.assertNotIn(" ".join(words), str(raised.exception))
            self.assertEqual(client.values, {})
            self.assertEqual(client.hashes, {})
            self.assertEqual(client.streams, {})
            self.assertNotIn(raw, client.all_stored_bytes())
            self.assertNotIn(raw, repr(client.commands).encode("utf-8"))


if __name__ == "__main__":
    unittest.main()
