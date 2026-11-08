# Palimnex 2.10.0 — registro de publicación

Fecha: 2026-11-08 (America/Guatemala). Aprobación del propietario: mensaje del
2026-11-08 16:44 (R17 y R18 confirmados; candidato aprobado para publicarse
como 2.10.0; la influencia ontológica sigue apagada).

Transacción ejecutada en el orden aprobado, sin reescribir historia:

| Paso | Resultado |
| --- | --- |
| 1. PR #24 listo y fusionado | Fusión con commit de merge (como 2.9.0), `56b5fe416f26dcf3c04f21498552e2c6d7e6970c`, padres `56db9e5` (main) y `626f3d2` (rama). Árbol idéntico a `626f3d2`, cuya CI estaba verde en los seis trabajos |
| 2. Commit de merge confirmado | `BUNDLE_VERSION = "2.10.0"` en `origin/main` |
| 3. Etiqueta | `v2.10.0`, anotada («Palimnex 2.10.0», como `v2.9.0`), objeto `0d2679dd0749be01b6c174fed38d89b6cb5d46b9`, apunta a `56b5fe4` |
| 4. `publish.yml` | Ejecución `42531901639` en `main` con versión `2.10.0`: `build` (puerta estándar, mypy, build, twine, humo de la wheel instalada, verificación de versión) y `publish` (PyPI, publicación de confianza) exitosos, 22:46–22:55 UTC |
| 5. Verificación en PyPI | Ver abajo |
| 6. Release de GitHub | «Palimnex 2.10.0», etiqueta `v2.10.0`, marcada como la más reciente, sin archivos adjuntos (como 2.9.0); notas en `release-notes.md` |

## Verificación del paquete publicado

Entorno virtual aislado `/tmp/palimnex-pypi-verify`, sin caché de pip; el
pipx global no se tocó.

| Comprobación | Resultado |
| --- | --- |
| Archivos en PyPI | wheel `palimnex-2.10.0-py3-none-any.whl` sha256 `a3d32a26f141fb6d945bb469f99ca3d2c57bd962df33c7fc534d36a62746b0da` (310 809 bytes); sdist `palimnex-2.10.0.tar.gz` sha256 `7ee68e8ead28d0128e3a6c7ab743fd5334bb8f4f0f91ef4eb1991c842a0e8bb3` (413 443 bytes); `requires_python >=3.11` |
| Descarga | Los digests de los archivos descargados coinciden con los que publica PyPI |
| `pip install "palimnex[crypto]==2.10.0"` | OK; `palimnex --version` = 2.10.0 |
| Humo sin extras | Recursos, CLI y SDK OK |
| Humo con `crypto` | Recursos, CLI, SDK y evaluaciones fuera de línea OK |
| Opción retirada | `retention-migrate --no-snapshot` sale con 2, como se documenta |
| Publicado frente al candidato probado | Los 79 miembros de la wheel coinciden con la wheel candidata compilada desde `ce4fde2`, salvo la línea `Generator` de `WHEEL` (setuptools 84.2.1 en CI frente a 84.0.0 local). El código del paquete es idéntico |

Los checksums del candidato local (`dist-sha256.txt`) difieren de los de PyPI
porque `publish.yml` compila de nuevo desde la etiqueta; el contenido es el
mismo.

## Estado después de publicar

- Influencia ontológica apagada; `.palimnex.json` sin cambios.
- Ledger real del repositorio sin escrituras; Redis en el estado encontrado.
- La documentación de instalación (`README.md`, `docs/INSTALL.md`), que ya
  nombraba 2.10.0 según R17, ahora es cierta.
