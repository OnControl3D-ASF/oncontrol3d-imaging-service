## Qué cambia y por qué

<!-- Resumen del cambio y la motivación. Enlazar la historia de usuario (HU..) o issue. -->

## Tipo de cambio

- [ ] `feat` nueva funcionalidad
- [ ] `fix` corrección
- [ ] `refactor` / `perf` / `chore`
- [ ] `ci` / `build` / infraestructura
- [ ] `docs` / `test`

## Pruebas y calidad

- [ ] `ruff check app tests` y `pytest` en verde, con cobertura
- [ ] Pruebas nuevas o actualizadas para el cambio
- [ ] SonarCloud: quality gate en verde

## Contratos y despliegue

- [ ] **No cambia contratos de API consumidos por el Clinical Service ni por el visor** (rutas, campos, códigos HTTP), o el cambio está coordinado
- [ ] Manifiestos de `deploy/` actualizados si cambian variables, puertos o probes (`Validate Kubernetes manifests` en verde)

## Seguridad

- [ ] No hay secretos ni credenciales en el diff (gitleaks en verde); la configuración nueva se documenta en `.env.example` o en `deploy/env/`
- [ ] Sin hallazgos que bloqueen: Semgrep (ERROR), Trivy dependencias e imagen (CRITICAL / HIGH con parche)
- [ ] Dependencias nuevas o actualizadas revisadas (licencia, mantenimiento, CVEs)
- [ ] Validación de entradas y autorización consideradas (IDOR: ¿el usuario puede acceder a este recurso?)

## Revisión

- [ ] Commits con Conventional Commits y descripción que explica el **porqué**
- [ ] Rama actualizada y conversaciones de revisión resueltas
- [ ] Un *code owner* distinto del autor revisó el cambio (lo exige la protección de `main`)
