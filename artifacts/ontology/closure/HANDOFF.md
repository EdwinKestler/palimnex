# Cierre de la adopción de la ontología — entrega

Fecha: 2026-11-08. Estado: **cerrada a falta de la aprobación del propietario**
(fusionar el PR #24, rama `release/2.10.0`).

- Registro aprobado: `ontology/concept-registry.v1.json`, 16 conceptos,
  `registry_digest` `c19cc2de60b4c5a4d6b2e27f391df6bdf5f7d2351ca7d31c2c9dd0a00ca9df92`,
  0 vinculaciones obsoletas en el árbol final.
- Evidencia de promoción: `integration/promotion-evidence.json`, `promotable`,
  `evidence_digest` `e45e98b3070901bf5f34261a39def005099e4a313ee29d3cf5ff4b5fce674e97`;
  solo evidencia, no autoriza la activación.
- Revisiones: registro e integración `accepted_with_limits`
  (`reviews/`); cada límite y su cierre están en
  `artifacts/release/2.10.0/evidence/RC_REPORT.md`.
- Activación: apagada; `.palimnex.json` sin cambios. Activar es una decisión
  de configuración aparte que necesita su propia aprobación.
- Diferidos con aprobación aparte: evaluación de la retroalimentación (espera
  registros revisados suficientes), explorador del grafo y el experimento de
  modelo local de metahackathon.
- Mantenimiento: cualquier edición de un archivo vinculado deja obsoleto el
  registro; re-fijar con revisión (reglas R13 y R18).
