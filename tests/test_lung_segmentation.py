import zipfile

import numpy as np
import pytest
import SimpleITK as sitk

from app.lung_segmentation import (
    create_lung_only_volume,
    keep_lung_regions_per_slice,
    read_largest_dicom_series,
    save_images,
    segment_dense_regions,
    segment_lung_mask,
    unzip_archive,
)
from tests.phantom import (
    AIR_HU,
    SHAPE_ZYX,
    SPACING_XYZ,
    build_chest_phantom,
    dice,
    to_image,
)


class TestKeepLungRegionsPerSlice:
    def test_drops_air_connected_to_the_border(self):
        volume = np.zeros((1, 64, 64), dtype=bool)
        volume[0, :, :5] = True  # exterior air touching the edge

        assert not keep_lung_regions_per_slice(volume).any()

    def test_drops_regions_smaller_than_300_pixels(self):
        volume = np.zeros((1, 64, 64), dtype=bool)
        volume[0, 20:30, 20:30] = True  # 100 px

        assert not keep_lung_regions_per_slice(volume).any()

    def test_keeps_only_the_three_largest_regions(self):
        volume = np.zeros((1, 128, 128), dtype=bool)
        volume[0, 5:25, 5:25] = True  # 400 px
        volume[0, 5:27, 40:62] = True  # 484 px
        volume[0, 5:29, 80:104] = True  # 576 px
        volume[0, 60:86, 5:31] = True  # 676 px

        cleaned = keep_lung_regions_per_slice(volume)

        assert not cleaned[0, 5:25, 5:25].any()
        assert cleaned[0, 5:27, 40:62].all()
        assert cleaned[0, 5:29, 80:104].all()
        assert cleaned[0, 60:86, 5:31].all()


class TestSegmentLungMask:
    def test_matches_ground_truth_lungs(self):
        hu, true_lungs, _ = build_chest_phantom(with_nodule=False)

        mask = segment_lung_mask(hu, border_erosion_radius=0)

        assert dice(mask, true_lungs) > 0.9

    def test_excludes_exterior_air_and_soft_tissue(self):
        hu, true_lungs, _ = build_chest_phantom()

        mask = segment_lung_mask(hu, border_erosion_radius=0)

        assert not mask[(hu == AIR_HU) & ~true_lungs].any()
        assert not mask[:, 48, 48].any()  # mediastinum between both lungs

    def test_fills_dense_nodule_inside_the_lung(self):
        hu, _, nodule = build_chest_phantom()

        mask = segment_lung_mask(hu, border_erosion_radius=0)

        assert mask[nodule].all()

    def test_threshold_below_lung_density_finds_nothing(self):
        hu, _, _ = build_chest_phantom()

        mask = segment_lung_mask(hu, threshold_hu=-900)

        assert not mask.any()

    @pytest.mark.parametrize("radius", [1, 2])
    def test_border_erosion_shrinks_the_mask(self, radius):
        hu, _, _ = build_chest_phantom()

        unerodded = segment_lung_mask(hu, border_erosion_radius=0)
        eroded = segment_lung_mask(hu, border_erosion_radius=radius)

        assert 0 < eroded.sum() < unerodded.sum()
        assert not (eroded & ~unerodded).any()


class TestSegmentDenseRegions:
    def test_detects_nodule_inside_lung(self):
        hu, lungs, nodule = build_chest_phantom()

        dense = segment_dense_regions(hu, lungs)

        assert dense[nodule].all()
        assert not dense[~nodule].any()

    def test_ignores_dense_tissue_outside_the_lung(self):
        hu, _, _ = build_chest_phantom(with_nodule=False)
        empty_lungs = np.zeros(SHAPE_ZYX, dtype=bool)

        assert not segment_dense_regions(hu, empty_lungs).any()

    def test_drops_dense_specks_below_min_size(self):
        hu, lungs, _ = build_chest_phantom(with_nodule=False)
        hu[10, 48, 28] = 100  # single dense voxel

        assert not segment_dense_regions(hu, lungs, min_size=20).any()


class TestCreateLungOnlyVolume:
    @pytest.fixture
    def result(self):
        hu, _, _ = build_chest_phantom()
        return create_lung_only_volume(to_image(hu), border_erosion_radius=0)

    def test_outside_the_lungs_becomes_background_air(self, result):
        lung_image, mask_image, _, _ = result
        lung = sitk.GetArrayFromImage(lung_image)
        mask = sitk.GetArrayFromImage(mask_image).astype(bool)

        assert (lung[~mask] == AIR_HU).all()

    def test_highlights_dense_regions(self, result):
        _, _, highlight_image, _ = result
        _, _, nodule = build_chest_phantom()

        assert (sitk.GetArrayFromImage(highlight_image)[nodule] == 1500).all()

    def test_preserves_spatial_metadata(self, result):
        for image in result[:3]:
            assert image.GetSpacing() == pytest.approx(SPACING_XYZ)
            assert image.GetOrigin() == pytest.approx((-38.4, -38.4, 0.0))

    def test_reports_volumes_in_millilitres(self, result):
        _, mask_image, _, metrics = result
        voxel_ml = SPACING_XYZ[0] * SPACING_XYZ[1] * SPACING_XYZ[2] / 1000.0
        voxels = int(sitk.GetArrayFromImage(mask_image).sum())

        assert metrics["lungVoxelCount"] == voxels
        assert metrics["lungVolumeMl"] == pytest.approx(voxels * voxel_ml, abs=0.01)
        assert metrics["denseRegionCount"] == 1
        assert metrics["inputShapeZYX"] == list(SHAPE_ZYX)


class TestSaveImages:
    def test_writes_shrunk_compressed_volumes(self, tmp_path):
        hu, _, _ = build_chest_phantom()
        lung, mask, highlight, _ = create_lung_only_volume(to_image(hu))

        paths = save_images(lung, mask, tmp_path, highlight_image=highlight, viewer_shrink=2)

        saved = sitk.ReadImage(str(paths["lungVolumePath"]))
        assert saved.GetSize() == (48, 48, 10)
        assert paths["lungMaskPath"].exists()
        assert paths["highlightVolumePath"].exists()

    def test_skips_highlight_when_not_provided(self, tmp_path):
        hu, _, _ = build_chest_phantom()
        lung, mask, _, _ = create_lung_only_volume(to_image(hu))

        paths = save_images(lung, mask, tmp_path, viewer_shrink=1)

        assert sitk.ReadImage(str(paths["lungVolumePath"])).GetSize() == (96, 96, 20)
        assert not paths["highlightVolumePath"].exists()


def _write_dicom_series(folder, series_uid, slices):
    folder.mkdir(parents=True, exist_ok=True)
    writer = sitk.ImageFileWriter()
    writer.KeepOriginalImageUIDOn()
    for k in range(slices):
        slice_image = sitk.Image(16, 16, sitk.sitkInt16)
        slice_image.SetMetaData("0020|000e", series_uid)
        slice_image.SetMetaData("0020|0032", f"0\\0\\{k * 2.5}")
        slice_image.SetMetaData("0020|0013", str(k + 1))
        slice_image.SetMetaData("0008|0060", "CT")
        writer.SetFileName(str(folder / f"slice_{k:03d}.dcm"))
        writer.Execute(slice_image)


class TestReadLargestDicomSeries:
    def test_picks_the_series_with_most_slices(self, tmp_path):
        _write_dicom_series(tmp_path / "scout", "1.2.826.0.1.1", slices=3)
        _write_dicom_series(tmp_path / "ct", "1.2.826.0.1.2", slices=8)

        image, metadata = read_largest_dicom_series(tmp_path)

        assert metadata["seriesId"] == "1.2.826.0.1.2"
        assert metadata["numberOfSlices"] == 8
        assert image.GetSize() == (16, 16, 8)

    def test_raises_when_no_dicom_is_found(self, tmp_path):
        (tmp_path / "notes.txt").write_text("not a dicom")

        with pytest.raises(ValueError, match="No se encontró ninguna serie DICOM"):
            read_largest_dicom_series(tmp_path)


def test_unzip_archive_extracts_into_output_dir(tmp_path):
    archive = tmp_path / "study.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("SERIES/IM0001", b"dicom-bytes")

    out = unzip_archive(archive, tmp_path / "dicom")

    assert (out / "SERIES" / "IM0001").read_bytes() == b"dicom-bytes"
