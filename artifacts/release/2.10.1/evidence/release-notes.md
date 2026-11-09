# Palimnex 2.10.1

Palimnex 2.10.1 fixes cache-v3 indexing for large repositories.

- Chunk, graph, and posting writes now split by exact Redis request bytes.
- Indivisible atomic requests have a separate hard ceiling instead of being
  rejected by the ordinary pipeline grouping target.
- Failed indexing retries prune abandoned staging generations before starting
  again.
- Complete generation registry entries no longer duplicate every key already
  recorded by their validated manifest.
- Regression coverage includes aggregate large writes, oversized individual
  records, repeated failures, cleanup ownership, and Redis request limits.

The release does not change retrieval rankings, API v1, ledger schema v1,
encrypted pack v2, cache-v3 identifiers, or ontology behavior. Ontology
influence remains off by default.

After upgrading from 2.10.0, run:

```bash
palimnex index --incremental
palimnex validate --deep
```

The disposable cache is rebuilt because the bundle version changes; no ledger
migration is required.
