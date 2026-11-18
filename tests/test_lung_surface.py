import struct

import numpy as np
import pytest
import SimpleITK as sitk

import app.main as main
from tests.conftest import VALID_STUDY_ID
from tests.phantom import AIR_HU, build_chest_phantom, dice, to_image

SURFACE_URL = f"/studies/{VALID_STUDY_ID}/derived/lung-surface"


def test_surface_segmentation_excludes_closed_exterior_air_pocket():
    from app.lung_surface import surface_lung_mask

    hu, lungs, nodule = build_chest_phantom()
    # A separate table enclosure, large enough to survive the old area filter.
    hu = np.pad(hu, ((0, 0), (0, 40), (0, 0)), constant_values=AIR_HU)
    hu[:, 100:135, 10:85] = 40
    hu[:, 103:132, 13:82] = AIR_HU
    mask = surface_lung_mask(to_image(hu))
    assert not mask[:, 96:, :].any()
    assert dice(mask[:, :96], lungs) > 0.9
    assert mask[:, :96][nodule].all()


def test_mesh_is_closed_and_preserves_physical_geometry():
    from app.lung_surface import mask_surface_mesh

    a = np.zeros((8, 9, 10), dtype=np.uint8)
    a[2:6, 3:7, 4:8] = 1
    image = sitk.GetImageFromArray(a)
    image.SetSpacing((0.8, 1.2, 3.4))
    image.SetOrigin((10, 20, 30))
    image.SetDirection((0, -1, 0, 1, 0, 0, 0, 0, 1))
    vertices, faces = mask_surface_mesh(a.astype(bool), image)
    assert np.isfinite(vertices).all()
    assert np.allclose(vertices.min(axis=0), (10 - 6.5 * 1.2, 20 + 3.5 * 0.8,
                                             30 + 1.5 * 3.4))
    assert np.allclose(vertices.max(axis=0), (10 - 2.5 * 1.2, 20 + 7.5 * 0.8,
                                             30 + 5.5 * 3.4))
    edges = np.sort(np.concatenate([faces[:, [0, 1]], faces[:, [1, 2]],
                                    faces[:, [2, 0]]]), axis=1)
    assert (np.unique(edges, axis=0, return_counts=True)[1] == 2).all()


def test_empty_surface_fails_clearly():
    from app.lung_surface import mask_surface_mesh

    image = sitk.Image(8, 8, 8, sitk.sitkUInt8)
    with pytest.raises(ValueError, match="pulmonar"):
        mask_surface_mesh(np.zeros((8, 8, 8), dtype=bool), image)


def test_endpoint_requires_raw_dicom_even_with_old_mask(client, storage):
    derived = storage / "derived" / VALID_STUDY_ID
    derived.mkdir(parents=True)
    (derived / "lung_mask.mha").write_bytes(b"old cache")
    response = client.get(SURFACE_URL)
    assert response.status_code == 409
    assert "segment-lungs" in response.json()["detail"]
    assert (derived / "lung_mask.mha").read_bytes() == b"old cache"


def test_endpoint_creates_binary_stl_and_reuses_cache(client, storage, monkeypatch):
    raw = storage / "raw" / VALID_STUDY_ID / "dicom"
    raw.mkdir(parents=True)
    calls = []

    def read_series(path):
        calls.append(path)
        return to_image(build_chest_phantom()[0]), {}

    monkeypatch.setattr(main, "read_largest_dicom_series", read_series)
    first = client.get(SURFACE_URL)
    second = client.get(SURFACE_URL)
    assert first.status_code == second.status_code == 200
    assert first.headers["content-type"] == "model/stl"
    assert "lung_surface.stl" in first.headers["content-disposition"]
    assert len(calls) == 1
    assert first.content == second.content
    count = struct.unpack_from("<I", first.content, 80)[0]
    assert count > 0
    assert len(first.content) == 84 + count * 50


def test_surface_endpoint_rejects_invalid_study_id(client):
    assert client.get("/studies/not-an-id/derived/lung-surface").status_code == 422
