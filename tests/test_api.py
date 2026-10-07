import zipfile

import pytest
import requests

import app.main as main
from tests.conftest import VALID_STUDY_ID
from tests.phantom import build_chest_phantom, to_image

SEGMENT_URL = f"/studies/{VALID_STUDY_ID}/segment-lungs"


@pytest.fixture
def fake_orthanc(monkeypatch):
    """Replaces Orthanc with a stub that serves the synthetic phantom."""
    calls = {"downloads": 0}

    def download(study_id, output_zip):
        calls["downloads"] += 1
        output_zip.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(output_zip, "w") as zf:
            zf.writestr("IM0001", b"stub")
        return output_zip

    def read_series(root_dir):
        hu, _, _ = build_chest_phantom()
        return to_image(hu), {"seriesId": "1.2.3", "numberOfSlices": hu.shape[0]}

    monkeypatch.setattr(main, "download_study_archive", download)
    monkeypatch.setattr(main, "read_largest_dicom_series", read_series)
    return calls


def test_health(client):
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": "oncontrol-imaging-service"}


def test_openapi_documents_every_endpoint(client):
    paths = client.get("/openapi.json").json()["paths"]

    assert "/studies/{orthanc_study_id}/segment-lungs" in paths
    assert "/studies/{orthanc_study_id}/viewer-url" in paths


class TestSegmentLungs:
    def test_segments_and_returns_viewer_links(self, client, fake_orthanc, storage):
        response = client.post(SEGMENT_URL, params={"border_erosion_radius": 0})

        body = response.json()
        assert response.status_code == 200
        assert body["alreadyProcessed"] is False
        assert body["metrics"]["denseRegionCount"] == 1
        expected = f"/studies/{VALID_STUDY_ID}/derived/lung-highlighted"
        assert body["highlightVolumeUrl"].endswith(expected)
        assert "lung_highlighted.mha" in body["volviewUrl"]
        assert (storage / "derived" / VALID_STUDY_ID / "lung_only.mha").exists()

    def test_reuses_cached_volume_without_calling_orthanc(self, client, fake_orthanc):
        client.post(SEGMENT_URL)
        response = client.post(SEGMENT_URL)

        assert response.json()["alreadyProcessed"] is True
        assert fake_orthanc["downloads"] == 1

    def test_force_reprocesses(self, client, fake_orthanc):
        client.post(SEGMENT_URL)
        response = client.post(SEGMENT_URL, params={"force": True})

        assert response.json()["alreadyProcessed"] is False
        assert fake_orthanc["downloads"] == 2

    def test_missing_study_in_orthanc_returns_404(self, client, monkeypatch):
        def missing(*_):
            raise ValueError("No existe el estudio en Orthanc")

        monkeypatch.setattr(main, "download_study_archive", missing)

        response = client.post(SEGMENT_URL)

        assert response.status_code == 404

    def test_unexpected_failure_returns_500(self, client, monkeypatch):
        def broken(*_):
            raise RuntimeError("disk full")

        monkeypatch.setattr(main, "download_study_archive", broken)

        response = client.post(SEGMENT_URL)

        assert response.status_code == 500


class TestDerivedVolumes:
    @pytest.mark.parametrize("kind", ["lung-volume", "lung-mask", "lung-highlighted"])
    def test_returns_404_before_segmentation(self, client, kind):
        response = client.get(f"/studies/{VALID_STUDY_ID}/derived/{kind}")

        assert response.status_code == 404

    @pytest.mark.parametrize("kind", ["lung-volume", "lung-mask", "lung-highlighted"])
    def test_serves_volume_after_segmentation(self, client, fake_orthanc, kind):
        client.post(SEGMENT_URL)

        response = client.get(f"/studies/{VALID_STUDY_ID}/derived/{kind}")

        assert response.status_code == 200
        assert response.headers["content-type"] == "application/octet-stream"
        assert len(response.content) > 0

    def test_viewer_url_after_segmentation(self, client, fake_orthanc):
        client.post(SEGMENT_URL)

        response = client.get(f"/studies/{VALID_STUDY_ID}/viewer-url")

        assert response.status_code == 200
        assert response.json()["alreadyProcessed"] is True


class TestOrthancStudyInfo:
    def test_returns_metadata(self, client, monkeypatch):
        monkeypatch.setattr(main, "get_study_metadata", lambda _id: {"ID": _id})

        response = client.get(f"/orthanc/studies/{VALID_STUDY_ID}")

        assert response.json() == {"ID": VALID_STUDY_ID}

    def test_unknown_study_returns_404(self, client, monkeypatch):
        def missing(_id):
            raise ValueError("No existe")

        monkeypatch.setattr(main, "get_study_metadata", missing)

        assert client.get(f"/orthanc/studies/{VALID_STUDY_ID}").status_code == 404

    def test_orthanc_down_returns_502(self, client, monkeypatch):
        def down(_id):
            raise requests.ConnectionError("refused")

        monkeypatch.setattr(main, "get_study_metadata", down)

        assert client.get(f"/orthanc/studies/{VALID_STUDY_ID}").status_code == 502
