"""CORS on AKS: origin comes from the `edge` ConfigMap (PUBLIC_ORIGIN), never from env files."""

import os
import re
import subprocess
from pathlib import Path

import pytest

from app.config import Settings
from app.main import cors_options

ROOT = Path(__file__).resolve().parent.parent
RENDER = ROOT / "deploy" / "render.sh"
ENVIRONMENTS = ["dev", "prod"]


def render(environment: str) -> subprocess.CompletedProcess:
    env = {k: v for k, v in os.environ.items() if k != "CORS_ALLOWED_ORIGINS"}
    env.update(
        IMAGE="example.azurecr.io/oncontrol3d/imaging@sha256:" + "0" * 64,
        APP_VERSION="test",
    )
    return subprocess.run(
        [str(RENDER), environment], env=env, capture_output=True, text=True, check=False
    )


def test_settings_honor_cors_allowed_origins_from_environment(monkeypatch):
    monkeypatch.setenv("CORS_ALLOWED_ORIGINS", "https://oc3d.westeurope.cloudapp.azure.com")

    options = cors_options(Settings().cors_allowed_origins)

    assert options["allow_origins"] == ["https://oc3d.westeurope.cloudapp.azure.com"]
    assert options["allow_credentials"] is True


@pytest.mark.parametrize("environment", ENVIRONMENTS)
def test_env_files_do_not_hardcode_cors(environment):
    text = (ROOT / "deploy" / "env" / f"{environment}.env").read_text()

    assert "CORS_ALLOWED_ORIGINS" not in text


@pytest.mark.parametrize("environment", ENVIRONMENTS)
def test_render_does_not_require_cors_allowed_origins(environment):
    result = render(environment)

    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("environment", ENVIRONMENTS)
def test_rendered_cors_comes_from_optional_edge_configmap(environment):
    rendered = render(environment).stdout

    block = re.search(
        r"- name: CORS_ALLOWED_ORIGINS\n\s+valueFrom:\n\s+configMapKeyRef:\n"
        r"\s+name: edge\n\s+key: PUBLIC_ORIGIN\n\s+optional: true",
        rendered,
    )
    assert block is not None
