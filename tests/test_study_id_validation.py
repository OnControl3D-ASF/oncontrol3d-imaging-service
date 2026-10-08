import pytest

from tests.conftest import VALID_STUDY_ID

MALICIOUS_IDS = ["%2e%2e", "abc", "6e2c0ec2", "6E2C0EC2-5D99E8CA-4A4F0AB4-80B5D01C-A7A1F4A1"]

# These never reach a handler: ".." is normalized by the client and "%2f" decodes
# to "/", so no route matches. 404 is the expected (and equally safe) rejection.
UNROUTABLE_IDS = ["..", "%2e%2e%2f%2e%2e"]

ENDPOINTS = [
    ("post", "/studies/{id}/segment-lungs?force=true"),
    ("get", "/studies/{id}/derived/lung-volume"),
    ("get", "/studies/{id}/derived/lung-mask"),
    ("get", "/studies/{id}/derived/lung-highlighted"),
    ("get", "/studies/{id}/viewer-url"),
    ("get", "/orthanc/studies/{id}"),
]


@pytest.mark.parametrize("study_id", MALICIOUS_IDS)
@pytest.mark.parametrize("method,path", ENDPOINTS)
def test_rejects_study_ids_that_are_not_orthanc_ids(client, method, path, study_id):
    response = getattr(client, method)(path.format(id=study_id))

    assert response.status_code == 422


@pytest.mark.parametrize("study_id", UNROUTABLE_IDS)
@pytest.mark.parametrize("method,path", ENDPOINTS)
def test_traversal_ids_never_reach_a_handler(client, method, path, study_id):
    response = getattr(client, method)(path.format(id=study_id))

    assert response.status_code == 404
    assert response.json() == {"detail": "Not Found"}


def test_force_reprocess_with_traversal_id_does_not_delete_storage(client, storage):
    sentinel = storage / "derived" / VALID_STUDY_ID / "lung_only.mha"
    sentinel.parent.mkdir(parents=True)
    sentinel.write_bytes(b"patient volume")

    client.post("/studies/%2e%2e/segment-lungs?force=true")

    assert sentinel.exists()


def test_accepts_well_formed_orthanc_study_id(client):
    response = client.get(f"/studies/{VALID_STUDY_ID}/viewer-url")

    assert response.status_code == 404
