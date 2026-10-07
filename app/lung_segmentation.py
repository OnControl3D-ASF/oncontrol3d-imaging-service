import os
import zipfile
from pathlib import Path

import numpy as np
import SimpleITK as sitk
from scipy import ndimage as ndi
from skimage import measure, morphology
from skimage.segmentation import clear_border


def unzip_archive(zip_path: Path, output_dir: Path) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)

    with zipfile.ZipFile(zip_path, "r") as zip_ref:
        zip_ref.extractall(output_dir)

    return output_dir


def read_largest_dicom_series(root_dir: Path) -> tuple[sitk.Image, dict]:
    """
    Lee la serie DICOM más grande dentro del ZIP descargado desde Orthanc.
    Normalmente esa será la serie CT principal.
    """

    reader = sitk.ImageSeriesReader()
    candidates = []

    for dirpath, _, _ in os.walk(root_dir):
        series_ids = reader.GetGDCMSeriesIDs(dirpath)

        if not series_ids:
            continue

        for series_id in series_ids:
            files = reader.GetGDCMSeriesFileNames(dirpath, series_id)
            candidates.append(
                {
                    "dirpath": dirpath,
                    "series_id": series_id,
                    "files": files,
                    "count": len(files),
                }
            )

    if not candidates:
        raise ValueError("No se encontró ninguna serie DICOM válida en el archivo descargado.")

    best = max(candidates, key=lambda item: item["count"])

    reader.SetFileNames(best["files"])
    image = reader.Execute()

    metadata = {
        "seriesId": best["series_id"],
        "numberOfSlices": best["count"],
        "spacing": image.GetSpacing(),
        "origin": image.GetOrigin(),
        "size": image.GetSize(),
    }

    return image, metadata


def keep_lung_regions_per_slice(binary_volume: np.ndarray) -> np.ndarray:
    """
    Limpieza 2D por corte axial:
    - elimina aire exterior conectado al borde
    - conserva las regiones internas más grandes
    """

    cleaned = np.zeros_like(binary_volume, dtype=bool)

    for z in range(binary_volume.shape[0]):
        slice_mask = binary_volume[z]

        # Quita regiones pegadas al borde: normalmente aire externo.
        slice_mask = clear_border(slice_mask)

        # Quita ruido pequeño.
        slice_mask = morphology.remove_small_objects(slice_mask, max_size=79)

        labels = measure.label(slice_mask)
        regions = measure.regionprops(labels)

        if not regions:
            continue

        # Pulmón izquierdo, derecho y a veces tráquea/bronquios.
        regions = sorted(regions, key=lambda region: region.area, reverse=True)
        keep_labels = []

        for region in regions[:3]:
            if region.area >= 300:
                keep_labels.append(region.label)

        if keep_labels:
            cleaned[z] = np.isin(labels, keep_labels)

    return cleaned


def segment_lung_mask(
    hu_volume: np.ndarray,
    threshold_hu: int = -400,
    border_erosion_radius: int = 1,
) -> np.ndarray:
    """
    Segmentación básica de pulmones en CT.

    hu_volume llega como array [z, y, x].

    threshold_hu:
    -400 suele funcionar para separar región pulmonar del tejido blando.
    Puedes probar -500, -450, -400 o -350.

    border_erosion_radius:
    "Come" el borde externo de la máscara pulmonar.
    Sirve para eliminar la capa superficial que aparece alrededor del pulmón.
    Valores recomendados:
    0 = no erosionar
    1 = erosión suave
    2 = erosión moderada
    3 = erosión agresiva
    """

    # Aire / pulmón aproximado.
    binary = hu_volume < threshold_hu

    # Limpieza por corte para eliminar aire externo.
    mask = keep_lung_regions_per_slice(binary)

    # Suaviza y une pequeñas discontinuidades.
    mask = morphology.closing(mask, morphology.ball(2))

    # Elimina componentes 3D pequeñas.
    mask = morphology.remove_small_objects(mask, max_size=4999)

    # Rellena huecos dentro del pulmón por corte.
    # Esto ayuda a conservar vasos/arterias dentro de la región pulmonar.
    filled = np.zeros_like(mask, dtype=bool)
    for z in range(mask.shape[0]):
        filled[z] = ndi.binary_fill_holes(mask[z])

    mask = filled

    # Come un poco el borde externo para quitar la "capa" alrededor del pulmón.
    # Esto debe hacerse después del fill_holes para no perder arterias internas.
    if border_erosion_radius > 0:
        mask = morphology.erosion(
            mask,
            morphology.ball(border_erosion_radius)
        )

    # Limpieza final por si la erosión dejó fragmentos pequeños.
    mask = morphology.remove_small_objects(mask, max_size=2999)

    return mask.astype(bool)


def segment_dense_regions(
    hu_volume: np.ndarray,
    lung_mask: np.ndarray,
    dense_threshold_hu: int = -150,
    min_size: int = 20,
) -> np.ndarray:
    """
    Marca las regiones DENSAS dentro del pulmón: el parénquima aireado ronda
    -700/-900 HU, mientras que nódulos, masas y vasos son mucho más densos
    (> -150 HU aprox.). Es un realce REFERENCIAL, no un detector de tumores:
    también resalta vasos. Sirve para dirigir la mirada a zonas de interés.
    """
    dense = lung_mask & (hu_volume > dense_threshold_hu)
    dense = morphology.remove_small_objects(dense, max_size=min_size - 1)
    return dense.astype(bool)


def create_lung_only_volume(
    image: sitk.Image,
    threshold_hu: int = -400,
    background_hu: int = -1000,
    border_erosion_radius: int = 1,
    dense_threshold_hu: int = -150,
    highlight_value: int = 1500,
) -> tuple[sitk.Image, sitk.Image, sitk.Image, dict]:
    """
    Devuelve:
    - volumen CT con solo pulmones visibles (fondo = aire, para un render más limpio)
    - máscara binaria de pulmones
    - volumen "resaltado": igual que el pulmonar pero con las zonas densas
      llevadas a una intensidad alta (`highlight_value`) para que destaquen en 3D
    - métricas (incluye hallazgos densos)
    """

    hu = sitk.GetArrayFromImage(image).astype(np.int16)

    mask = segment_lung_mask(
        hu,
        threshold_hu=threshold_hu,
        border_erosion_radius=border_erosion_radius,
    )

    # Fondo = aire (-1000) en vez de -3024: evita la "niebla" oscura que algunos
    # presets de VolView renderizan con valores extremos.
    lung_only = np.full_like(hu, fill_value=background_hu, dtype=np.int16)
    lung_only[mask] = hu[mask]

    # Zonas densas dentro del pulmón (referencial).
    dense = segment_dense_regions(hu, mask, dense_threshold_hu=dense_threshold_hu)

    # Volumen resaltado: pulmón normal + zonas densas empujadas a intensidad alta.
    lung_highlighted = lung_only.copy()
    lung_highlighted[dense] = highlight_value

    lung_image = sitk.GetImageFromArray(lung_only)
    lung_image.CopyInformation(image)

    mask_image = sitk.GetImageFromArray(mask.astype(np.uint8))
    mask_image.CopyInformation(image)

    highlight_image = sitk.GetImageFromArray(lung_highlighted)
    highlight_image.CopyInformation(image)

    spacing = image.GetSpacing()
    voxel_volume_mm3 = spacing[0] * spacing[1] * spacing[2]
    lung_volume_ml = float(mask.sum() * voxel_volume_mm3 / 1000.0)
    dense_volume_ml = float(dense.sum() * voxel_volume_mm3 / 1000.0)
    dense_region_count = int(measure.label(dense).max())

    metrics = {
        "thresholdHu": threshold_hu,
        "backgroundHu": background_hu,
        "borderErosionRadius": border_erosion_radius,
        "denseThresholdHu": dense_threshold_hu,
        "lungVoxelCount": int(mask.sum()),
        "lungVolumeMl": round(lung_volume_ml, 2),
        "denseVoxelCount": int(dense.sum()),
        "denseVolumeMl": round(dense_volume_ml, 2),
        "denseRegionCount": dense_region_count,
        "inputShapeZYX": list(hu.shape),
        "minHuOriginal": int(hu.min()),
        "maxHuOriginal": int(hu.max()),
    }

    return lung_image, mask_image, highlight_image, metrics


def save_images(
    lung_image: sitk.Image,
    mask_image: sitk.Image,
    output_dir: Path,
    highlight_image: sitk.Image | None = None,
    viewer_shrink: int = 2,
) -> dict:
    """
    Guarda los volúmenes derivados.

    viewer_shrink:
    Factor de submuestreo aplicado SOLO al volumen que se sirve al visor
    (la segmentación ya se hizo a resolución completa, así que la calidad de
    la máscara no cambia). Reduce enormemente el tamaño de descarga y acelera
    el render en VolView, que es referencial y no diagnóstico.
    1 = sin submuestreo, 2 = ~8x menos vóxeles (recomendado), 3+ = más agresivo.

    Además comprime el .mha (ITK/VolView lo leen de forma transparente).
    """
    output_dir.mkdir(parents=True, exist_ok=True)

    if viewer_shrink and viewer_shrink > 1:
        # sitk.Shrink hace submuestreo (no promedia), evitando el "sangrado"
        # del fondo hacia los bordes del pulmón.
        lung_image = sitk.Shrink(lung_image, [viewer_shrink] * 3)
        mask_image = sitk.Shrink(mask_image, [viewer_shrink] * 3)
        if highlight_image is not None:
            highlight_image = sitk.Shrink(highlight_image, [viewer_shrink] * 3)

    lung_path = output_dir / "lung_only.mha"
    mask_path = output_dir / "lung_mask.mha"
    highlight_path = output_dir / "lung_highlighted.mha"

    sitk.WriteImage(lung_image, str(lung_path), useCompression=True)
    sitk.WriteImage(mask_image, str(mask_path), useCompression=True)
    if highlight_image is not None:
        sitk.WriteImage(highlight_image, str(highlight_path), useCompression=True)

    return {
        "lungVolumePath": lung_path,
        "lungMaskPath": mask_path,
        "highlightVolumePath": highlight_path,
    }