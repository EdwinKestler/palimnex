"""Ed25519 artifact identity with operator-owned trust roots and signer injection."""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Protocol, runtime_checkable

from .durable import canonical_json

SIGNATURE_SCHEMA = "palimnex:signature:v1"
PURPOSES = {"encrypted-pack", "ledger-checkpoint", "adapter-receipt"}


@runtime_checkable
class Signer(Protocol):
    """KMS/HSM adapters implement Ed25519 signing without exporting a private key."""
    api_version: int

    @property
    def public_key(self) -> bytes: ...

    def sign(self, message: bytes) -> bytes: ...


@dataclass(frozen=True)
class TrustedIdentity:
    name: str
    public_key: bytes

    def __post_init__(self) -> None:
        if not isinstance(self.name, str) or not re.fullmatch(r"[a-z0-9][a-z0-9._:-]{0,127}", self.name):
            raise ValueError("identity must be a pseudonymous machine identifier")
        if not isinstance(self.public_key, bytes) or len(self.public_key) != 32:
            raise ValueError("Ed25519 public key must have 32 bytes")

    @property
    def key_id(self) -> str:
        return hashlib.sha256(self.public_key).hexdigest()


class Ed25519Signer:
    api_version = 1

    def __init__(self, private_key: bytes):
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
        self._key = Ed25519PrivateKey.from_private_bytes(private_key)

    @classmethod
    def from_file(cls, path: Path) -> Ed25519Signer:
        from .portable import load_pack_key
        return cls(load_pack_key(path))

    @property
    def public_key(self) -> bytes:
        from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
        return self._key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)

    def sign(self, message: bytes) -> bytes:
        return self._key.sign(message)


def generate_signing_key(path: Path) -> dict[str, str]:
    from .portable import _write_new_private_file
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from cryptography.hazmat.primitives.serialization import Encoding, PrivateFormat, NoEncryption
    key = Ed25519PrivateKey.generate()
    raw = key.private_bytes(Encoding.Raw, PrivateFormat.Raw, NoEncryption())
    signer = Ed25519Signer(raw)
    output = _write_new_private_file(path, raw, "Ed25519 signing key")
    return {"path": str(output), "algorithm": "Ed25519", "public_key": signer.public_key.hex(),
            "key_id": hashlib.sha256(signer.public_key).hexdigest()}


def sign_artifact(raw: bytes, purpose: str, signer: Signer) -> dict[str, Any]:
    if purpose not in PURPOSES or signer.api_version != 1:
        raise ValueError("unsupported signature purpose or signer version")
    identity = TrustedIdentity("signer", signer.public_key)
    body = {"schema": SIGNATURE_SCHEMA, "algorithm": "Ed25519", "purpose": purpose,
            "key_id": identity.key_id, "sha256": hashlib.sha256(raw).hexdigest()}
    result = {**body, "signature": signer.sign(canonical_json(body)).hex()}
    verify_artifact(raw, purpose, result, {identity.key_id: identity})
    return result


def verify_artifact(raw: bytes, purpose: str, signature: Mapping[str, Any],
                    trusted: Mapping[str, TrustedIdentity]) -> TrustedIdentity:
    from cryptography.exceptions import InvalidSignature
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
    fields = {"schema", "algorithm", "purpose", "key_id", "sha256", "signature"}
    if not isinstance(signature, dict) or set(signature) != fields or purpose not in PURPOSES:
        raise ValueError("invalid signature fields or purpose")
    if signature["schema"] != SIGNATURE_SCHEMA or signature["algorithm"] != "Ed25519" or signature["purpose"] != purpose:
        raise ValueError("signature domain mismatch")
    for name, length in (("key_id", 64), ("sha256", 64), ("signature", 128)):
        if not isinstance(signature[name], str) or not re.fullmatch(f"[0-9a-f]{{{length}}}", signature[name]):
            raise ValueError("invalid signature encoding")
    identity = trusted.get(signature["key_id"])
    if identity is None or identity.key_id != signature["key_id"]:
        raise ValueError("signer is not trusted")
    if signature["sha256"] != hashlib.sha256(raw).hexdigest():
        raise ValueError("signed artifact digest mismatch")
    body = {k: v for k, v in signature.items() if k != "signature"}
    try:
        Ed25519PublicKey.from_public_bytes(identity.public_key).verify(
            bytes.fromhex(signature["signature"]), canonical_json(body))
    except InvalidSignature:
        raise ValueError("invalid Ed25519 signature") from None
    return identity
