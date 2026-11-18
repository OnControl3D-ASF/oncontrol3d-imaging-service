"""Referential solid surfaces from CT masks, not diagnostic anatomy or HU data."""

import os
import struct
import tempfile
from pathlib import Path

import numpy as np
import SimpleITK as sitk
from scipy import ndimage as ndi
from skimage import measure, morphology

from app.lung_segmentation import keep_lung_regions_per_slice


def surface_lung_mask(image: sitk.Image) -> np.ndarray:
    """Exclude enclosed exterior/table air before selecting internal lung air.

    The largest soft-tissue envelope in each slice approximates the torso.
    Keeping the two major 3D components discards smaller isolated bowel air.
    This remains a threshold-based, unvalidated visualization mask.
    """
    hu = sitk.GetArrayFromImage(image)
    internal_air = np.zeros(hu.shape, dtype=bool)
    for z, axial in enumerate(hu):
        tissue = ndi.binary_opening(axial >= -400, structure=morphology.disk(2))
        labels, count = ndi.label(tissue)
        if not count:
            continue
        sizes = np.bincount(labels.ravel())
        sizes[0] = 0
        body = ndi.binary_fill_holes(labels == sizes.argmax())
        internal_air[z] = (axial < -400) & body

    mask = keep_lung_regions_per_slice(internal_air)
    mask = morphology.closing(mask, morphology.ball(1))
    for z in range(mask.shape[0]):
        mask[z] = ndi.binary_fill_holes(mask[z])
    labels, count = ndi.label(mask)
    if not count:
        return mask
    sizes = np.bincount(labels.ravel())
    sizes[0] = 0
    major = np.argsort(sizes)[-2:]
    major = major[sizes[major] >= max(3000, sizes.max() * 0.1)]
    return np.isin(labels, major)


def mask_surface_mesh(mask: np.ndarray, image: sitk.Image) -> tuple[np.ndarray, np.ndarray]:
    """Closed isosurface in physical LPS millimetres, preserving all CT slices."""
    occupied = np.where(mask)
    if not occupied[0].size:
        raise ValueError("No se encontró una región pulmonar para crear el modelo sólido.")
    lower = np.array([axis.min() for axis in occupied])
    upper = np.array([axis.max() for axis in occupied]) + 1
    crop = mask[tuple(slice(int(a), int(b)) for a, b in zip(lower, upper, strict=True))]
    # Padding closes the mesh even when the segmented volume reaches an image edge.
    vertices, faces, _, _ = measure.marching_cubes(
        np.pad(crop.astype(np.uint8), 1), level=0.5, allow_degenerate=False
    )
    if len(faces) > 2_000_000:
        raise ValueError("La superficie pulmonar excede el límite de complejidad del visor.")
    indices_xyz = (vertices + lower - 1)[:, ::-1]
    direction = np.array(image.GetDirection()).reshape(3, 3)
    vertices = (indices_xyz * image.GetSpacing()) @ direction.T + image.GetOrigin()
    # Reversing ZYX to XYZ can reverse orientation. Give every triangle outward winding.
    triangles = vertices[faces] - vertices.mean(axis=0)
    signed_volume = np.einsum(
        "ij,ij->i", triangles[:, 0], np.cross(triangles[:, 1], triangles[:, 2])
    ).sum()
    if signed_volume < 0:
        faces = faces[:, [0, 2, 1]]
    return vertices, faces


def write_surface_stl(image: sitk.Image, destination: Path) -> Path:
    """Write a versioned binary STL atomically without touching existing CT derivatives."""
    vertices, faces = mask_surface_mesh(surface_lung_mask(image), image)
    triangles = vertices[faces]
    normals = np.cross(triangles[:, 1] - triangles[:, 0], triangles[:, 2] - triangles[:, 0])
    normals /= np.linalg.norm(normals, axis=1, keepdims=True)
    records = np.zeros(len(faces), dtype=[
        ("normal", "<f4", (3,)), ("vertices", "<f4", (3, 3)), ("attribute", "<u2")
    ])
    records["normal"] = normals
    records["vertices"] = triangles
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=destination.parent, suffix=".tmp", delete=False) as f:
            temporary = Path(f.name)
            f.write(b"OnControl3D referential LPS mm surface v1".ljust(80, b"\0"))
            f.write(struct.pack("<I", len(faces)))
            f.write(records.tobytes())
        os.replace(temporary, destination)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return destination
