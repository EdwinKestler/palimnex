Implemented and validated the candidate registry: [registry](/home/kestl/github/palimnex/artifacts/ontology/closure/candidate/concept-registry.candidate.json), [notes](/home/kestl/github/palimnex/artifacts/ontology/closure/candidate/NOTES.md), [checker](/home/kestl/github/palimnex/artifacts/ontology/closure/candidate/check_candidate.py), and [receipt](/home/kestl/github/palimnex/artifacts/ontology/closure/receipts/ontology-closure-registry.implementation-receipt.json).

Registry digest: `5f85b2a99d92708125c5457488a539835425dbeb88e03081894323c945f34520`.

Concepts:

- `source_admission` — bindings: `security.py:242–256,282–333`; `cache_v3.py:190–218`. Aliases: repository privacy scan; credential shaped content scan; admitted source snapshot; bounded repository file read.
- `source_locator` — `locators.py:36–78,109–121,124–139`. Aliases: versioned source locator; repository range locator; source binding verification; digest bound source range.
- `retrieval_fusion` — `retrieval.py:64–171,174–188,263–278`. Aliases: reciprocal rank fusion; lexical symbol graph fusion; retrieval channel ranking.
- `context_assembly` — `retrieval.py:50–61`; `experience.py:202–247`. Aliases: context byte budget; source history context assembly; interleaved context items.
- `cache_generation` — `cache_v3.py:638–686,731–741,1311–1388`. Aliases: immutable cache generation; reader generation lease; active generation swap; leased generation garbage collection.
- `durable_ledger` — `durable.py:816–846,1465–1505,2112–2245`. Aliases: durable memory history; sqlite historical event ledger; source verified event recall; hash bound ledger events.
- `retention_eligibility` — `retention.py:63–86,284–313,349–455`. Aliases: retention cleanup eligibility; preservation hold exclusion; durable erasure authorization; temporal dependency closure.
- `ledger_migration` — `migrations.py:66–85,98–136,172–198`. Aliases: ledger schema migration registry; adjacent schema migration; migration step resolution.
- `memory_pack` — `portable.py:518–580,583–675,900–993`. Aliases: encrypted memory export; authenticated portable history; quarantined pack import; portable ledger archive.
- `audit_graph` — `audit.py:66–340,343–374`. Aliases: historical audit projection; audit node edge projection; forgotten event tombstones; signed audit graph export.
- `concept_registry` — `concepts.py:570–657,696–731,802–841`. Aliases: source bound concept validation; normalized alias matching; candidate registry parser; concept source drift check.
- `coverage_receipt` — `coverage.py:352–567,884–946`. Aliases: retrieval coverage receipt; concept answerability status; covered uncovered concepts; stale binding diagnosis.
- `ontology_shadow` — `ontology_shadow.py:141–233,311–458,472–610`. Aliases: ontology channel comparison; non influencing ontology rank; source binding chunk overlap; shadow rank diff.
- `ontology_activation` — `ontology_influence.py:225–233,489–578`; `ontology_promotion.py:500–602`. Aliases: ontology influence activation; promotion evidence gate; registry digest activation; enabled ontology channel.
- `semantic_shadow` — `semantic_local.py:188–249`; `semantic_shadow.py:309–392`; `semantic_eval.py:727–935`. Aliases: semantic channel comparison; in process embedding shadow; provider identity bound evaluation; semantic promotion gates.
- `retrieval_feedback` — `feedback.py:203–270,435–457,629–734`. Aliases: reviewed retrieval judgement; source bound retrieval feedback; feedback correction withdrawal; retrieval feedback report.

All acceptance commands passed: 45/45 bindings current, 61 aliases collision-free, 25 concept tests passing, and receipt contract valid. No cache, ledger, Redis, network, Git-write, or activation action occurred.

Open risks: independent review and owner merge are still required; blind evaluation remains intentionally unrun until freeze; later source edits will stale affected bindings. The unrelated dirty worktree was preserved.