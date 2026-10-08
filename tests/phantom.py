"""Synthetic chest CT phantom used to test the segmentation without real patient data."""

import numpy as np
import SimpleITK as sitk

AIR_HU = -1000
LUNG_HU = -850
TISSUE_HU = 40
NODULE_HU = 60

SHAPE_ZYX = (20, 96, 96)
SPACING_XYZ = (0.8, 0.8, 2.5)


def _disk(shape_yx, center_yx, radius):
    yy, xx = np.ogrid[: shape_yx[0], : shape_yx[1]]
    return (yy - center_yx[0]) ** 2 + (xx - center_yx[1]) ** 2 <= radius**2


def build_chest_phantom(with_nodule: bool = True) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Returns (hu_volume, true_lung_mask, true_nodule_mask), all shaped [z, y, x]."""
    z, h, w = SHAPE_ZYX
    hu = np.full(SHAPE_ZYX, AIR_HU, dtype=np.int16)
    lungs = np.zeros(SHAPE_ZYX, dtype=bool)
    nodule = np.zeros(SHAPE_ZYX, dtype=bool)

    body = _disk((h, w), (48, 48), 40)
    left_lung = _disk((h, w), (48, 28), 13)
    right_lung = _disk((h, w), (48, 68), 13)
    nodule_disk = _disk((h, w), (48, 28), 3)

    for k in range(z):
        hu[k][body] = TISSUE_HU
        hu[k][left_lung | right_lung] = LUNG_HU
        lungs[k] = left_lung | right_lung
        if with_nodule and 7 <= k <= 12:
            hu[k][nodule_disk] = NODULE_HU
            nodule[k] = nodule_disk

    return hu, lungs, nodule


def to_image(hu: np.ndarray) -> sitk.Image:
    image = sitk.GetImageFromArray(hu)
    image.SetSpacing(SPACING_XYZ)
    image.SetOrigin((-38.4, -38.4, 0.0))
    return image


def dice(a: np.ndarray, b: np.ndarray) -> float:
    return 2.0 * np.logical_and(a, b).sum() / (a.sum() + b.sum())
