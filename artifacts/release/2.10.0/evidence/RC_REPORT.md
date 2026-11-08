# Palimnex 2.10.0 — informe del candidato a versión

Fecha: 2026-11-08. Rama `release/2.10.0`, pull request #24 (borrador).
Coordinador: Claude; carriles de implementación: Codex (gpt-5.6-sol, high);
revisiones independientes de solo lectura: Grok 4.6 (xhigh).

**Estado: publicado el 2026-11-08.** El propietario aprobó el candidato y
confirmó R17 y R18; la transacción (fusión `56b5fe4`, etiqueta `v2.10.0`,
PyPI, verificación y release de GitHub) está en `PUBLICATION.md`. La
influencia ontológica sigue apagada.

## Commits del candidato

| Commit | Contenido |
| --- | --- |
| `0b12e36` | Prepara 2.10.0: registro de conceptos aprobado, versión, documentación, retirada de `retention-migrate --no-snapshot`, re-pin R18 |
| `5edc164` | Pruebas independientes de la plataforma (digests dorados en macOS; binario envuelto en Ubuntu) |
| `3364735` | Evidencia de una compilación limpia anterior (sustituida por la de este commit) |
| `ce4fde2` | El binario de la prueba del envoltorio de Redis se elige por sondeo (`sleep`, luego `sh`) |
| `626f3d2` | Evidencia final del candidato y este informe; solo `artifacts/` |
| `56b5fe4` | Fusión del PR #24 en `main`; etiquetado `v2.10.0` |

Los commits posteriores a `0b12e36` solo cambian `palimnex/tests/` y
`artifacts/`. Ningún módulo del paquete ni archivo vinculado por el registro
cambió.

## Cierre de la adopción de la ontología NVIDIA

| Elemento | Resultado |
| --- | --- |
| Registro aprobado | `ontology/concept-registry.v1.json`: 16 conceptos derivados del código, alias conservadores (sin «memory», «search», «graph», «registry» sueltos), vinculados solo al checkout de Palimnex |
| `registry_digest` | `c19cc2de60b4c5a4d6b2e27f391df6bdf5f7d2351ca7d31c2c9dd0a00ca9df92` (archivo sha256 `6911f42213c97f7d31c4a067bde3398936568e9afcb42cb9e5b6e74578667366`) |
| Vinculaciones en el árbol final | 16 conceptos verificados, 0 obsoletos (`verify_source_bindings`) |
| Conjunto de evaluación | Ciego hasta congelar el candidato; usado solo después (`artifacts/ontology/closure/integration/registry-freeze.json`) |
| Evidencia de promoción | `promotable`, `evidence_digest` `e45e98b3070901bf5f34261a39def005099e4a313ee29d3cf5ff4b5fce674e97`; `implementation_digest` y `registry_digest` coinciden con el árbol final; `activation_authorized: false`, `authority: evidence_only` |
| Activación | Apagada: `.palimnex.json` no tiene clave `ontology_influence` y no se modificó |
| Aprobación del registro | Aprobado por el propietario al fusionar el PR #24 (`56b5fe4`, 2026-11-08) |

## Revisiones independientes y cómo se cerró cada límite

| Revisión | Estado | Límites y cierre |
| --- | --- | --- |
| Registro (`artifacts/ontology/closure/reviews/ontology-closure-registry.review-receipt.json`) | accepted_with_limits | El revisor no ejecutó la CLI (prohibido) → cubierto por la puerta local y la CI. Conjunto ciego no abierto → por contrato; la promoción lo evaluó tras congelar. Árbol con cambios paralelos en `retention.py`/`core.py` → vinculaciones re-fijadas y verificadas en el árbol final (0 obsoletas). `cache_consulted: false` → por diseño (`.palimnex/` prohibido). Fallo de Redis en fix-2 → no afectó la evaluación |
| Integración del cierre (`…/ontology-closure-integration.review-receipt.json`) | accepted_with_limits | `design_identity` copiado de la tarjeta, el documento recibió después el texto de estado → esperado. Suite completa no re-ejecutada por el revisor → `gate.log` (550 pruebas) y la CI. FakeRedis en la promoción → por diseño. Árbol con ediciones de la versión → cerradas en `0b12e36` y comprobadas aquí |
| Preparación de la versión, ronda 1 | rejected | BLOCKERs por texto de instalación 2.10.0 no publicado → decisión R17. MAJORs en COMPATIBILITY/UPGRADING → corregidos |
| Preparación de la versión, ronda 2 (`artifacts/release/2.10.0/reviews/release-prep.round-2.json`) | accepted_with_limits | NOTE marcador del CHANGELOG → sustituido por la entrada del registro. NOTE resumen desactualizado sobre `--no-snapshot` → adenda en `release-prep-summary.md`. NOTE números de línea en la lista de ocurrencias conservadas → aceptado; las ocurrencias siguen siendo históricas |
| Arreglos de CI (`artifacts/release/2.10.0/reviews/ci-fixes.json`) | accepted_with_limits | Solo NOTEs: cada prueba conserva su garantía (`checkout_id` se sigue afirmando antes de normalizarlo; el envoltorio sigue haciendo `exec` del binario real) y los commits no tocan código del paquete, archivos vinculados ni módulos de `influence_implementation_digest`. Límites aceptados: un `SkipTest` si ningún binario corre bajo el nombre copiado (antes, fallo duro); el sondeo de `sh` daría fallo, no omisión, en un `/bin/sh` que se re-ejecuta; la aserción global de `checkout_id` en la prueba de influencia da peor diagnóstico. El revisor no ejecutó pruebas; la CI sí |

## Decisiones del coordinador (confirmadas por el propietario el 2026-11-08)

- **R17** (`evidence/R17-release-docs-sequencing.md`): la documentación ya
  nombra 2.10.0 como publicada, igual que en 2.9.0; fusión, etiqueta,
  publicación, verificación y release se ejecutaron como una sola
  transacción controlada.
- **R18** (`evidence/R18-fixture-repin.md`): tres fixtures congelados del
  registro re-fijados solo en `version` y `registry_digest`; los digests de
  rango no cambiaron. Toda edición futura de `README.md` o `docs/DESIGN.md`
  exige repetirlo, y toda edición de un archivo vinculado deja obsoleto el
  registro publicado.

## Verificación

| Comprobación | Resultado |
| --- | --- |
| CI del PR #24 en `ce4fde2` | Verde: Python 3.11, 3.12, 3.13 y 3.14 en Ubuntu, 3.11 en macOS y `upgrade-rehearsal` (550 pruebas por plataforma). Los fallos previos (coreutils multicall en Ubuntu; `/private/tmp` en macOS, preexistente en `main` desde 2026-11-07) quedaron corregidos solo en pruebas |
| Puerta local (`0b12e36`) | 550 pruebas OK (1 omisión esperada), mypy estricto limpio, validación profunda, `palimnex evaluate` sin fallos críticos |
| Compilación limpia | `tools/build_clean.sh` desde `git archive` del commit, `SOURCE_DATE_EPOCH` del commit |
| Checksums (`evidence/dist-sha256.txt`, compilados desde `ce4fde2`) | wheel `39dc3a5d178844edee711d3bd264302d80dfb167b01df2f213cd4ee6b8b12118`; sdist `72597809ded5f88bd7ad148a16ddd49fe7a945aa99b13004e3dfb4ec71feb201`. Los binarios están en `artifacts/release/2.10.0/dist/` (ignorado por Git); el flujo `publish.yml` (ejecución manual con la versión) compila de nuevo desde `refs/tags/v2.10.0` y exige `BUNDLE_VERSION` igual a la versión |
| Reproducibilidad | Wheel idéntica byte a byte al recompilar; el sdist difiere solo en metadatos del archivo comprimido, con contenido idéntico |
| Contenido de la wheel | 0 miembros en `palimnex/tests` |
| `twine check --strict` | wheel y sdist PASSED (twine 7.0.0 en un venv aislado; pipx global sin tocar) |
| Wheel instalada | `palimnex --version` = 2.10.0; prueba de humo del paquete (recursos, CLI, SDK) OK |
| Ensayo de actualización v2.9.0 → 2.10.0 | `passed`; caché fresca; ledger intacto; sin estado vivo ni red (`evidence/upgrade-rehearsal.json`) |
| Adopción en otros repositorios | waveshares3 `dd5bd71`, ereditas `b8dcec7`, edgelinkd `34c626f` (rebrand-n2link): todos los pasos OK salvo `doctor` (2, avisos del entorno de instantánea) y `evaluate` (1, sin `evaluation_fixture`), ambos documentados. rgbhackathon omitido (opcional; sin commits). Copias temporales con Redis y ledger aislados (`evidence/adoption-summary.md`) |

## Restricciones respetadas

Sin escrituras en ledgers reales; `.palimnex.json` sin cambios; no se leyeron
`.env*`, `.palimnex/`, `secrets/` ni `benchmark/`; la instalación global
pipx 2.9.0 sigue intacta; Redis queda como se encontró (en marcha); el
experimento de modelo local de metahackathon no se tocó.

## Residuales aceptados

- El registro publicado y los fixtures R18 quedan obsoletos con cualquier
  edición de un archivo vinculado; `explain-search` lo informa
  (`stale_concept_ids`). Re-fijar exige revisión.
- Evaluar la retroalimentación espera a tener suficientes registros revisados;
  el explorador de grafo y el experimento de modelo local siguen diferidos y
  con aprobación aparte.
- Una publicación formal `2.10.0rc1` requeriría cambiar el flujo de
  publicación (solo acepta X.Y.Z); no se hizo.

## Resultado de los pasos del propietario

1. PR #24 aprobado y fusionado el 2026-11-08 (`56b5fe4`): el registro queda
   aprobado.
2. Etiqueta `v2.10.0` sobre `56b5fe4`, `publish.yml` exitoso, paquete
   verificado en PyPI y release de GitHub creada (`PUBLICATION.md`).
3. Activar la influencia ontológica sigue siendo una decisión de
   configuración independiente (`ontology_influence.mode`), no incluida.
