# Security policy

Palimnex processes repository source, durable historical memory, encrypted
packs, source locators, and retention controls. Treat reports involving
privacy admission, cross-project isolation, path traversal, symlink handling,
Redis transport, ledger integrity, cryptographic custody, import quarantine,
retention, erasure, or authority boundaries as security-sensitive.

## Supported versions

Security fixes target the latest stable release line. Palimnex 2.10.x is the
currently supported line. Upgrade before reporting a problem that occurs only
on an older version. Historical format compatibility does not imply security
maintenance for an older executable.

## Report privately

Do not open a public issue containing an exploit, credential, key, private
repository content, ledger payload, memory pack, Redis URL, source excerpt, or
other sensitive evidence.

Use GitHub's **Report a vulnerability** private-reporting form for this
repository when it is available. If it is unavailable, contact the repository
owner through the GitHub profile and request a private reporting channel before
sending technical details. Never send live secrets; use redacted diagnostics
and synthetic reproduction data.

Include, when safe:

- affected Palimnex and Python versions;
- installation mode and operating system;
- the smallest synthetic reproduction;
- expected and observed authority, privacy, or integrity behavior;
- whether Redis, the ledger, packs, retention state, or imported history is
  involved; and
- whether the issue is already public or actively exploited.

## Response boundary

A report is evidence, not authorization to access another project, run a live
migration or erasure, rotate keys, delete cache namespaces, modify external
systems, or disclose private data. Maintainers reproduce against isolated
state and coordinate disclosure and release timing with the reporter.

Palimnex's local-erasure receipts do not claim forensic deletion from storage
media, backups, replicas, or unmanaged exports. Reports should distinguish a
contract violation in managed stores from expectations outside that boundary.
