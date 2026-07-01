from pathlib import Path
import shutil
import urllib.parse

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

from app.config import settings
from app.orthanc_client import download_study_archive, get_study_metadata
from app.lung_segmentation import (
    unzip_archive,
    read_largest_dicom_series,
    create_lung_only_volume,
    save_images,
)

app = FastAPI(
    title="OnControl Imaging Service",
    version="0.1.0",
    description="Microservicio para procesamiento y segmentación pulmonar de tomografías.",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Solo desarrollo. En producción restringir.
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def get_storage_paths(orthanc_study_id: str) -> dict:
    base = Path(settings.storage_dir)

    return {
        "raw_dir": base / "raw" / orthanc_study_id,
        "zip_path": base / "raw" / orthanc_study_id / "study.zip",
        "unzip_dir": base / "raw" / orthanc_study_id / "dicom",
        "derived_dir": base / "derived" / orthanc_study_id,
        "lung_path": base / "derived" / orthanc_study_id / "lung_only.mha",
        "mask_path": base / "derived" / orthanc_study_id / "lung_mask.mha",
        "highlight_path": base / "derived" / orthanc_study_id / "lung_highlighted.mha",
    }


@app.get("/health")
def health():
    return {
        "status": "ok",
        "service": "oncontrol-imaging-service",
    }


@app.get("/orthanc/studies/{orthanc_study_id}")
def orthanc_study_info(orthanc_study_id: str):
    try:
        return get_study_metadata(orthanc_study_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Error consultando Orthanc: {exc}")


@app.post("/studies/{orthanc_study_id}/segment-lungs")
def segment_lungs(
    orthanc_study_id: str,
    threshold_hu: int = Query(
    -400,
    description="Umbral HU para segmentación pulmonar. Prueba -500, -450, -400 o -350.",
    ),
    border_erosion_radius: int = Query(
        1,
        description="Cantidad de borde pulmonar a erosionar. 0=no erosiona, 1=suave, 2=moderado, 3=agresivo.",
    ),
    force: bool = Query(
        False,
        description="Si true, recalcula aunque ya exista un volumen derivado.",
    ),
    viewer_shrink: int = Query(
        2,
        description="Submuestreo del volumen servido al visor (no afecta la "
        "segmentación). 1=full, 2=~8x más liviano (recomendado), 3+=agresivo.",
    ),
):
    paths = get_storage_paths(orthanc_study_id)

    if paths["lung_path"].exists() and not force:
        return build_segmentation_response(orthanc_study_id, already_processed=True)

    try:
        # Limpia datos previos si se fuerza reprocesamiento.
        if force and paths["derived_dir"].exists():
            shutil.rmtree(paths["derived_dir"])

        if force and paths["raw_dir"].exists():
            shutil.rmtree(paths["raw_dir"])

        # 1. Descarga ZIP del estudio desde Orthanc.
        download_study_archive(orthanc_study_id, paths["zip_path"])

        # 2. Descomprime.
        unzip_archive(paths["zip_path"], paths["unzip_dir"])

        # 3. Lee la serie DICOM principal.
        image, series_metadata = read_largest_dicom_series(paths["unzip_dir"])

        # 4. Segmenta pulmón + zonas densas.
        lung_image, mask_image, highlight_image, metrics = create_lung_only_volume(
            image=image,
            threshold_hu=threshold_hu,
            border_erosion_radius=border_erosion_radius,
        )

        # 5. Guarda derivados (incluye el volumen resaltado).
        saved = save_images(
            lung_image=lung_image,
            mask_image=mask_image,
            highlight_image=highlight_image,
            output_dir=paths["derived_dir"],
            viewer_shrink=viewer_shrink,
        )

        response = build_segmentation_response(
            orthanc_study_id,
            already_processed=False,
        )

        response["seriesMetadata"] = series_metadata
        response["metrics"] = metrics
        response["files"] = {
            "lungVolume": str(saved["lungVolumePath"]),
            "lungMask": str(saved["lungMaskPath"]),
            "highlightVolume": str(saved["highlightVolumePath"]),
        }

        return response

    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Error segmentando pulmones: {exc}")


@app.get("/studies/{orthanc_study_id}/derived/lung-volume")
def get_lung_volume(orthanc_study_id: str):
    paths = get_storage_paths(orthanc_study_id)

    if not paths["lung_path"].exists():
        raise HTTPException(
            status_code=404,
            detail="Todavía no existe volumen pulmonar. Ejecuta primero /segment-lungs.",
        )

    return FileResponse(
        path=paths["lung_path"],
        media_type="application/octet-stream",
        filename=f"{orthanc_study_id}_lung_only.mha",
    )


@app.get("/studies/{orthanc_study_id}/derived/lung-mask")
def get_lung_mask(orthanc_study_id: str):
    paths = get_storage_paths(orthanc_study_id)

    if not paths["mask_path"].exists():
        raise HTTPException(
            status_code=404,
            detail="Todavía no existe máscara pulmonar. Ejecuta primero /segment-lungs.",
        )

    return FileResponse(
        path=paths["mask_path"],
        media_type="application/octet-stream",
        filename=f"{orthanc_study_id}_lung_mask.mha",
    )


@app.get("/studies/{orthanc_study_id}/derived/lung-highlighted")
def get_lung_highlighted(orthanc_study_id: str):
    paths = get_storage_paths(orthanc_study_id)

    if not paths["highlight_path"].exists():
        raise HTTPException(
            status_code=404,
            detail="Todavía no existe volumen resaltado. Ejecuta primero /segment-lungs.",
        )

    return FileResponse(
        path=paths["highlight_path"],
        media_type="application/octet-stream",
        filename=f"{orthanc_study_id}_lung_highlighted.mha",
    )


@app.get("/studies/{orthanc_study_id}/viewer-url")
def get_volview_url(orthanc_study_id: str):
    paths = get_storage_paths(orthanc_study_id)

    if not paths["lung_path"].exists():
        raise HTTPException(
            status_code=404,
            detail="Todavía no existe volumen pulmonar. Ejecuta primero /segment-lungs.",
        )

    return build_segmentation_response(orthanc_study_id, already_processed=True)


def build_segmentation_response(orthanc_study_id: str, already_processed: bool):
    base = f"{settings.public_base_url}/studies/{orthanc_study_id}/derived"
    lung_volume_url = f"{base}/lung-volume"
    highlight_volume_url = f"{base}/lung-highlighted"

    paths = get_storage_paths(orthanc_study_id)

    # Por defecto el visor abre el volumen RESALTADO (zonas densas destacadas).
    # Si aún no existe (caché antigua), cae al volumen pulmonar plano.
    if paths["highlight_path"].exists():
        view_name = f"{orthanc_study_id}_lung_highlighted.mha"
        view_url = highlight_volume_url
    else:
        view_name = f"{orthanc_study_id}_lung_only.mha"
        view_url = lung_volume_url

    encoded_name = urllib.parse.quote(view_name)
    encoded_url = urllib.parse.quote(view_url, safe=":/?&=%")

    volview_url = (
        f"{settings.volview_url}"
        f"?names=[{encoded_name}]"
        f"&urls=[{encoded_url}]"
    )

    return {
        "orthancStudyId": orthanc_study_id,
        "alreadyProcessed": already_processed,
        "lungVolumeUrl": lung_volume_url,
        "highlightVolumeUrl": highlight_volume_url,
        "volviewUrl": volview_url,
        "message": "Volumen pulmonar generado correctamente.",
    }