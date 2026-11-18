# Hallazgos de seguridad — Imaging Service

Fecha: 2026-11-17 · Rama: `feat/devsecops` · Herramientas: Trivy 0.76, Semgrep 1.182 (`p/python`),
gitleaks 8.30 (reglas por defecto + `.gitleaks.toml`).

## Política de bloqueo en CI

| Workflow | Herramienta | Bloquea | Solo reporta |
|---|---|---|---|
| `container.yml` | Trivy (imagen) | **Cualquier CRITICAL**; HIGH con parche; Dockerfile HIGH/CRITICAL | `trivy-image.json` |
| `sca.yml` (nuevo) | Trivy (`requirements*.txt`) | **Cualquier CRITICAL**; HIGH con parche | `trivy.json` |
| `sast.yml` | Semgrep `p/python` | Severidad **ERROR** | WARNING/INFO en `semgrep.json` |
| `secrets.yml` | gitleaks | Secretos en el árbol actual | Historial en `gitleaks-history.json` |

## Hallazgos

| # | Hallazgo | Severidad | Antes | Corrección | Después |
|---|---|---|---|---|---|
| 1 | CORS con `allow_origins=["*"]` **y** `allow_credentials=True`: Starlette refleja el `Origin` de cualquier sitio y habilita peticiones con credenciales desde cualquier dominio (Semgrep `wildcard-cors`) | MEDIUM | `GET /health` con `Origin: https://evil.example` → `ACAO: https://evil.example`, `credentials: true` | Orígenes configurables con `CORS_ALLOWED_ORIGINS`; credenciales solo con orígenes explícitos; métodos limitados a GET/POST/OPTIONS | `ACAO: *` sin credenciales (verificado). En ambientes desplegados: fijar el origen de VolView/Orthanc |
| 2 | Sin análisis de dependencias (SCA) en CI | MEDIUM (brecha de proceso) | Sin `sca.yml` | `sca.yml` con Trivy sobre `requirements*.txt` | 0 CRITICAL / 0 HIGH |
| 3 | El gate de imagen solo bloqueaba HIGH/CRITICAL con parche | MEDIUM (política) | `--ignore-unfixed` | Gate adicional para cualquier CRITICAL | 0 CRITICAL en la imagen |
| 4 | Ajustes de Pydantic con secretos y defaults hardcodeados no los detectan las reglas por defecto de gitleaks | LOW (brecha de detección) | — | Regla `python-settings-secret-default` | 0 en el árbol y en el historial; las credenciales de Orthanc son `None` por defecto |

Del Bloque 1 (imagen): 230 → 216 vulnerabilidades, **14 → 0 con parche disponible**, 0 CRITICAL, usuario no root.

## Configuración en ambientes desplegados

| Variable | Valor |
|---|---|
| `CORS_ALLOWED_ORIGINS` | Origen(es) de VolView/Orthanc que descargan los `.mha`, separados por coma. Ej.: `https://orthanc.dominio` |
| `ORTHANC_USERNAME` / `ORTHANC_PASSWORD` | Desde Key Vault / Kubernetes Secret, nunca en el repo |
