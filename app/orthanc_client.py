from pathlib import Path
import requests

from app.config import settings


def get_auth():
    if settings.orthanc_username and settings.orthanc_password:
        return (settings.orthanc_username, settings.orthanc_password)
    return None


def get_study_metadata(orthanc_study_id: str) -> dict:
    url = f"{settings.orthanc_url}/studies/{orthanc_study_id}"

    response = requests.get(url, auth=get_auth(), timeout=30)

    if response.status_code == 404:
        raise ValueError(f"No existe el estudio en Orthanc: {orthanc_study_id}")

    response.raise_for_status()
    return response.json()


def download_study_archive(orthanc_study_id: str, output_zip: Path) -> Path:
    url = f"{settings.orthanc_url}/studies/{orthanc_study_id}/archive"

    output_zip.parent.mkdir(parents=True, exist_ok=True)

    with requests.get(url, auth=get_auth(), stream=True, timeout=120) as response:
        if response.status_code == 404:
            raise ValueError(f"No existe el estudio en Orthanc: {orthanc_study_id}")

        response.raise_for_status()

        with output_zip.open("wb") as file:
            for chunk in response.iter_content(chunk_size=1024 * 1024):
                if chunk:
                    file.write(chunk)

    return output_zip