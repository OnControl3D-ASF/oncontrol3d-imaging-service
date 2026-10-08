import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.main import app

VALID_STUDY_ID = "6e2c0ec2-5d99e8ca-4a4f0ab4-80b5d01c-a7a1f4a1"


@pytest.fixture
def storage(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "storage_dir", str(tmp_path))
    return tmp_path


@pytest.fixture
def client(storage):
    return TestClient(app)
