from __future__ import annotations

import copy
import hashlib
import json
import os
import sqlite3
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from palimnex import API_VERSION, Evidence, Event, Palimnex, RecallOptions
from palimnex.adapters import AdapterRegistry, SQLiteDerivativeAdapter
from palimnex.identity import Ed25519Signer, TrustedIdentity, generate_signing_key, sign_artifact, verify_artifact
from palimnex.integrity import checkpoint_id, verify_history
from palimnex.locators import ResolvedSource, SourceLocator, SourceRange, repository_locator
from palimnex.tests.support import PROJECT_ID, write_project


class SDKTests(unittest.TestCase):
    def test_public_wire_schemas(self):
        import jsonschema
        from referencing import Registry, Resource
        directory = Path(__file__).resolve().parents[1] / "schemas"
        schemas = [json.loads((directory / name).read_text()) for name in (
            "source-locator.v1.schema.json", "signature.v1.schema.json", "event-checkpoint.v1.schema.json")]
        registry = Registry().with_resources((schema["$id"], Resource.from_contents(schema)) for schema in schemas)
        checkpoint = self.client.checkpoint(commitment_key=self.key, signer=self.signer)
        for schema, instance in zip(schemas, (self.locator.to_dict(), checkpoint["signature"], checkpoint)):
            jsonschema.Draft202012Validator.check_schema(schema)
            validator = jsonschema.Draft202012Validator(schema, registry=registry)
            validator.validate(instance)
            with self.assertRaises(jsonschema.ValidationError):
                validator.validate({**instance, "unknown": True})

    def test_adapter_detects_payload_tampering(self):
        connection = sqlite3.connect(":memory:")
        self.addCleanup(connection.close)
        adapter = SQLiteDerivativeAdapter(connection, project_id=PROJECT_ID)
        adapter.initialize()
        adapter.put("row-1", "a" * 32, b"original", version="1")
        registry = AdapterRegistry(PROJECT_ID)
        registry.register(adapter)
        plan = registry.plan("sqlite", ["a" * 32])
        with connection:
            connection.execute("UPDATE palimnex_derivatives SET payload=?", (b"tampered",))
        with self.assertRaisesRegex(ValueError, "digest mismatch"):
            registry.plan("sqlite", ["a" * 32])
        with self.assertRaisesRegex(ValueError, "payload changed"):
            adapter.delete(plan.derivatives[0])
        self.assertFalse(adapter.verify_absent(plan.derivatives[0]))

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        write_project(self.root)
        self.client = Palimnex(self.root, writable=True)
        self.client.initialize()
        self.sid = self.client.start_session("integration checks")["session_id"]
        self.locator = repository_locator(self.root, "docs/alpha.md:1-3")
        self.signer = Ed25519Signer(bytes(range(32)))
        self.identity = TrustedIdentity("test-producer", self.signer.public_key)
        self.trust = {self.identity.key_id: self.identity}
        self.key = bytes(reversed(range(32)))

    def record(self):
        return self.client.record(Event(self.sid, "fact", "cobalt orchard", {"state": "cobalt orchard"},
                                        (Evidence(self.locator),), retention="durable"))

    def test_sdk_public_contract_read_only_and_explicit_root(self):
        self.assertEqual(API_VERSION, 1)
        self.record()
        reader = Palimnex(str(self.root))
        self.assertEqual(reader.recall("cobalt")["results"][0]["payload"]["state"], "cobalt orchard")
        with self.assertRaises(PermissionError):
            reader.record_evidence(self.sid, "unauthorized", self.locator)
        with self.assertRaises(PermissionError):
            reader.initialize()
        with tempfile.TemporaryDirectory() as other:
            with self.assertRaises(ValueError):
                Palimnex(other)
            self.assertEqual(list(Path(other).iterdir()), [])

    def test_sdk_default_sensitivity_does_not_expose_secret(self):
        self.client.record(Event(self.sid, "fact", "cobalt classified", {"state": "cobalt"}, sensitivity="secret"))
        self.assertEqual(self.client.recall("classified")["results"], [])
        self.assertEqual(len(self.client.recall("classified", RecallOptions(max_sensitivity="secret"))["results"]), 1)

    def test_structured_and_legacy_source_evidence_roundtrip_and_drift(self):
        current = self.record()
        self.assertTrue(current["verified"])
        legacy = self.client.record_evidence(self.sid, "legacy cobalt", "docs/alpha.md:1-3")
        self.assertTrue(legacy["verified"])
        (self.root / "docs/alpha.md").write_text("changed\n", encoding="utf-8")
        self.assertEqual(self.client.recall("cobalt")["results"], [])
        self.assertFalse(self.client.reverify(current["event_id"])["verified"])
        with self.assertRaises(ValueError):
            self.record()

    def test_external_source_registration_version_and_digest_checks(self):
        class Resolver:
            api_version = 1
            raw = b"entity value"
            version = "rev-1"
            def resolve(self, source_id, version):
                return ResolvedSource(self.raw, self.version)
        resolver = Resolver()
        locator = SourceLocator("semantica", "entity-123", "rev-1", SourceRange("bytes", 0, 12),
                                hashlib.sha256(resolver.raw).hexdigest())
        with self.assertRaises(ValueError):
            self.client.record_evidence(self.sid, "entity", locator)
        external = Palimnex(self.root, writable=True, source_resolvers={"semantica": resolver})
        result = external.record_evidence(self.sid, "entity", locator)
        self.assertTrue(result["verified"])
        self.assertEqual(len(external.recall("entity")["results"]), 1)
        self.assertEqual(self.client.recall("entity")["results"], [])
        resolver.version = "rev-2"
        self.assertEqual(external.recall("entity")["results"], [])
        resolver.version = "rev-1"
        resolver.raw = b"other value!"
        self.assertFalse(external.reverify(result["event_id"])["verified"])

    def test_locator_bounds_traversal_and_canonical_serialization(self):
        self.assertEqual(SourceLocator.decode(self.locator.encode()), self.locator)
        for value in (SourceRange("lines", 1, 999), SourceRange("bytes", 0, 999)):
            with self.assertRaises(ValueError):
                self.client.record_evidence(self.sid, "invalid", replace(self.locator, range=value))
        for path in ("../outside:1", "/etc/passwd:1"):
            with self.assertRaises(ValueError):
                repository_locator(self.root, path)
        with self.assertRaises(ValueError):
            SourceRange("lines", True, 2)
        with self.assertRaises(ValueError):
            SourceLocator.decode(self.locator.encode() + " ")
        bad = self.locator.to_dict(); bad["extra"] = "field"
        with self.assertRaises(ValueError):
            SourceLocator.from_dict(bad)

    def test_signed_checkpoints_chain_rollback_and_mutation(self):
        first = self.client.checkpoint(commitment_key=self.key, signer=self.signer)
        self.record()
        second = self.client.checkpoint(commitment_key=self.key, signer=self.signer, previous=first, trusted=self.trust)
        tip = checkpoint_id(second)
        self.assertTrue(verify_history([first, second], self.trust, project_id=PROJECT_ID, expected_tip=tip)["verified"])
        self.assertTrue(self.client.verify_checkpoint(second, commitment_key=self.key, trusted=self.trust, expected_tip=tip)["verified"])
        for history in ([first], [second], [second, first], [first, first]):
            with self.assertRaises(ValueError):
                verify_history(history, self.trust, project_id=PROJECT_ID, expected_tip=tip)
        tampered = copy.deepcopy(second); tampered["body"]["event_count"] += 1
        with self.assertRaises(ValueError):
            verify_history([first, tampered], self.trust, project_id=PROJECT_ID, expected_tip=tip)
        with self.assertRaises(ValueError):
            self.client.verify_checkpoint(first, commitment_key=self.key, trusted=self.trust, expected_tip=checkpoint_id(first))
        with self.assertRaises(ValueError):
            self.client.verify_checkpoint(second, commitment_key=b"z" * 32, trusted=self.trust, expected_tip=tip)
        self.assertNotIn("cobalt", json.dumps(second))

    def test_checkpoint_erasure_preserves_chain_without_original_content(self):
        event = self.record()
        self.client.close_session(self.sid, "done")
        first = self.client.checkpoint(commitment_key=self.key, signer=self.signer)
        self.client.migrate_retention(expected_digest=self.client.status()["logical_digest"])
        self.client.activate_policy({"schema": "project-memory:retention-policy:v1", "policy_id": "test",
                                    "version": 1, "mode": "manual", "clock": "tx_at", "rules": [],
                                    "grace_after_close_seconds": 0, "plan_ttl_seconds": 3600},
                                   actor="tester", reason="test policy")
        self.client.authorize_erasure([event["event_id"]], authorized_by="tester", policy_id="test", reason_code="AUTHORIZED_ERASURE")
        plan = self.client.plan_erasure([event["event_id"]])
        result = self.client.apply_erasure(plan, confirm_digest=plan["plan_digest"], key=b"f" * 32, actor="tester", reason="test erase")
        self.assertEqual(result["status"], "applied")
        self.assertTrue(self.client.verify_erasure(plan["plan_digest"])["verified"])
        second = self.client.checkpoint(commitment_key=self.key, signer=self.signer, previous=first, trusted=self.trust)
        self.assertNotEqual(first["body"]["event_root"], second["body"]["event_root"])
        self.assertTrue(verify_history([first, second], self.trust, project_id=PROJECT_ID, expected_tip=checkpoint_id(second))["verified"])
        self.assertEqual(self.client.recall("cobalt")["results"], [])

    def test_signer_identity_is_local_trust_not_claimed_name(self):
        signature = sign_artifact(b"pack", "encrypted-pack", self.signer)
        self.assertEqual(verify_artifact(b"pack", "encrypted-pack", signature, self.trust).name, "test-producer")
        for raw, purpose, trust in ((b"other", "encrypted-pack", self.trust),
                                    (b"pack", "ledger-checkpoint", self.trust),
                                    (b"pack", "encrypted-pack", {})):
            with self.assertRaises(ValueError):
                verify_artifact(raw, purpose, signature, trust)
        damaged = {**signature, "signature": "00" * 64}
        with self.assertRaises(ValueError):
            verify_artifact(b"pack", "encrypted-pack", damaged, self.trust)

    def test_signing_key_file_is_exclusive_private_and_no_follow(self):
        key_path = self.root / ".private/signer.key"
        public = generate_signing_key(key_path)
        self.assertEqual(key_path.stat().st_mode & 0o777, 0o600)
        self.assertEqual(Ed25519Signer.from_file(key_path).public_key.hex(), public["public_key"])
        with self.assertRaises((ValueError, FileExistsError)):
            generate_signing_key(key_path)
        link = self.root / ".private/link.key"; link.symlink_to(key_path)
        with self.assertRaises(ValueError):
            Ed25519Signer.from_file(link)

    def test_signed_pack_required_signature_and_quarantined_import(self):
        self.record(); self.client.close_session(self.sid, "finished")
        output = self.root / ".private/transfer.pmem"
        exported = self.client.export_pack(output, self.key, signer=self.signer)
        with self.assertRaises(ValueError):
            self.client.import_pack(output, self.key)
        with self.assertRaises(ValueError):
            self.client.import_pack(output, self.key, signature=exported["signature"], trusted_signers={})
        report = self.client.import_pack(output, self.key, signature=exported["signature"], trusted_signers=self.trust)
        self.assertEqual(report["status"], "validated_quarantined")
        self.assertFalse(report["authorizes_actions"])
        self.assertTrue(self.client.import_pack(output, self.key, require_signature=False)["authenticated"])
        damaged = bytearray(output.read_bytes()); damaged[-1] ^= 1; output.write_bytes(damaged)
        with self.assertRaises(ValueError):
            self.client.import_pack(output, self.key, signature=exported["signature"], trusted_signers=self.trust)


class AdapterTests(unittest.TestCase):
    def setUp(self):
        self.connection = sqlite3.connect(":memory:")
        self.addCleanup(self.connection.close)
        self.adapter = SQLiteDerivativeAdapter(self.connection, project_id=PROJECT_ID)
        self.adapter.initialize()
        self.registry = AdapterRegistry(PROJECT_ID)
        self.registry.register(self.adapter)
        self.eid = "ab" * 16
        self.adapter.put("entity-1", self.eid, b"derived evidence", version="r1")

    def test_erasure_requires_current_authority_and_verifies_projection(self):
        plan = self.registry.plan("sqlite", [self.eid])
        with self.assertRaises(PermissionError):
            self.registry.apply(plan, confirm_digest=plan.digest, authorize=lambda _: False)
        self.assertFalse(self.adapter.verify_absent(plan.derivatives[0]))
        receipts = self.registry.apply(plan, confirm_digest=plan.digest, authorize=lambda _: True)
        self.assertTrue(receipts[0].verified_absent)
        self.assertEqual(self.registry.apply(plan, confirm_digest=plan.digest, authorize=lambda _: True)[0].object_id, "entity-1")

    def test_scope_changed_generation_expiry_and_duplicate_adapter(self):
        with self.assertRaises(ValueError):
            self.registry.register(self.adapter)
        other = SQLiteDerivativeAdapter(self.connection, project_id="other-project")
        with self.assertRaises(ValueError):
            self.registry.register(other)
        other.put("entity-1", self.eid, b"other project", version="r1")
        plan = self.registry.plan("sqlite", [self.eid])
        expired = replace(plan, expires_at=0)
        with self.assertRaises(ValueError):
            self.registry.apply(expired, confirm_digest=expired.digest, authorize=lambda _: True)
        self.adapter.put("entity-2", self.eid, b"new derivative", version="r2")
        with self.assertRaises(ValueError):
            self.registry.apply(plan, confirm_digest=plan.digest, authorize=lambda _: True)
        plan = self.registry.plan("sqlite", [self.eid])
        self.registry.apply(plan, confirm_digest=plan.digest, authorize=lambda _: True)
        self.assertEqual(len(other.enumerate_derivatives([self.eid])), 1)

    def test_partial_failure_retries_without_claiming_success(self):
        plan = self.registry.plan("sqlite", [self.eid])
        with patch.object(self.adapter, "invalidate_projection", side_effect=RuntimeError("offline")):
            with self.assertRaises(RuntimeError):
                self.registry.apply(plan, confirm_digest=plan.digest, authorize=lambda _: True)
        self.assertFalse(self.adapter.verify_absent(plan.derivatives[0]))
        replacement = self.registry.plan("sqlite", [self.eid])
        self.assertEqual(replacement.derivatives, plan.derivatives)
        self.assertTrue(self.registry.apply(plan, confirm_digest=plan.digest, authorize=lambda _: True)[0].verified_absent)

    def test_plan_cannot_delete_an_existing_object_outside_event_scope(self):
        plan = self.registry.plan("sqlite", [self.eid])
        foreign = replace(plan, event_ids=("cd" * 16,))
        with self.assertRaisesRegex(ValueError, "outside the enumerated scope"):
            self.registry.apply(foreign, confirm_digest=foreign.digest, authorize=lambda _: True)
        self.assertFalse(self.adapter.verify_absent(plan.derivatives[0]))

    def test_bad_receipt_and_stale_reference_refused(self):
        plan = self.registry.plan("sqlite", [self.eid])
        with self.connection:
            self.connection.execute("UPDATE palimnex_derivatives SET version='r2'")
        with self.assertRaises(ValueError):
            self.adapter.delete(plan.derivatives[0])
        with self.assertRaises(ValueError):
            self.registry.plan("sqlite", [self.eid])
        with self.connection:
            self.connection.execute("UPDATE palimnex_derivative_projection SET version='r2'")
        plan = self.registry.plan("sqlite", [self.eid])
        with patch.object(self.adapter, "produce_receipt", return_value=None):
            with self.assertRaises(ValueError):
                self.registry.apply(plan, confirm_digest=plan.digest, authorize=lambda _: True)


if __name__ == "__main__":
    unittest.main()
