import pytest
import requests

from app import orthanc_client
from app.config import settings
from tests.conftest import VALID_STUDY_ID


class FakeResponse:
    def __init__(self, status_code=200, json_body=None, chunks=()):
        self.status_code = status_code
        self._json = json_body
        self._chunks = chunks

    def json(self):
        return self._json

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"HTTP {self.status_code}")

    def iter_content(self, chunk_size):
        return iter(self._chunks)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


@pytest.fixture
def fake_get(monkeypatch):
    calls = []

    def install(response):
        def get(url, **kwargs):
            calls.append((url, kwargs))
            return response

        monkeypatch.setattr(orthanc_client.requests, "get", get)
        return calls

    return install


@pytest.fixture
def orthanc_settings(monkeypatch):
    monkeypatch.setattr(settings, "orthanc_url", "http://pacs:8042")
    monkeypatch.setattr(settings, "orthanc_username", None)
    monkeypatch.setattr(settings, "orthanc_password", None)
    return settings


def test_get_auth_is_none_without_credentials(orthanc_settings):
    assert orthanc_client.get_auth() is None


def test_get_auth_uses_basic_credentials(orthanc_settings, monkeypatch):
    monkeypatch.setattr(settings, "orthanc_username", "orthanc")
    monkeypatch.setattr(settings, "orthanc_password", "secret")

    assert orthanc_client.get_auth() == ("orthanc", "secret")


def test_get_study_metadata_calls_orthanc(orthanc_settings, fake_get):
    calls = fake_get(FakeResponse(json_body={"ID": VALID_STUDY_ID}))

    assert orthanc_client.get_study_metadata(VALID_STUDY_ID) == {"ID": VALID_STUDY_ID}
    assert calls[0][0] == f"http://pacs:8042/studies/{VALID_STUDY_ID}"
    assert calls[0][1]["timeout"] == 30


def test_get_study_metadata_missing_study(orthanc_settings, fake_get):
    fake_get(FakeResponse(status_code=404))

    with pytest.raises(ValueError, match="No existe el estudio"):
        orthanc_client.get_study_metadata(VALID_STUDY_ID)


def test_get_study_metadata_server_error(orthanc_settings, fake_get):
    fake_get(FakeResponse(status_code=500))

    with pytest.raises(requests.HTTPError):
        orthanc_client.get_study_metadata(VALID_STUDY_ID)


def test_download_study_archive_streams_to_disk(orthanc_settings, fake_get, tmp_path):
    calls = fake_get(FakeResponse(chunks=[b"PK", b"", b"data"]))
    target = tmp_path / "raw" / "study.zip"

    result = orthanc_client.download_study_archive(VALID_STUDY_ID, target)

    assert result == target
    assert target.read_bytes() == b"PKdata"
    assert calls[0][0].endswith(f"/studies/{VALID_STUDY_ID}/archive")
    assert calls[0][1]["stream"] is True


def test_download_study_archive_missing_study(orthanc_settings, fake_get, tmp_path):
    fake_get(FakeResponse(status_code=404))

    with pytest.raises(ValueError, match="No existe el estudio"):
        orthanc_client.download_study_archive(VALID_STUDY_ID, tmp_path / "study.zip")
