from io import BytesIO
from pathlib import Path
from uuid import UUID

import pytest
from PIL import Image
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject
from sqlalchemy import select
from test_auth import ORIGIN
from test_care import account, request, sign_in, transition
from test_clinical_record import linked_accounts

from app.core.document_config import MAX_MULTIPART_BYTES
from app.db.session import get_db
from app.main import app
from app.models.document import PrivateDocument
from app.models.professional_link import CareAuditEvent

DOCUMENTS = "/api/v1/documents"


@pytest.fixture
def storage(tmp_path, monkeypatch):
    directory = tmp_path / "private_uploads"
    monkeypatch.setenv("UPLOAD_DIR", str(directory))
    monkeypatch.setenv("OCR_LANG", "por+eng")
    monkeypatch.setenv("TESSERACT_CMD", str(tmp_path / "missing-tesseract"))
    return directory


def pdf(content=None):
    writer = PdfWriter()
    page = writer.add_blank_page(width=300, height=300)
    if content:
        font = DictionaryObject({
            NameObject("/Type"): NameObject("/Font"),
            NameObject("/Subtype"): NameObject("/Type1"),
            NameObject("/BaseFont"): NameObject("/Helvetica"),
        })
        page[NameObject("/Resources")] = DictionaryObject({
            NameObject("/Font"): DictionaryObject({NameObject("/F1"): font}),
        })
        stream = DecodedStreamObject()
        stream.set_data(b"BT /F1 12 Tf 20 200 Td (" + content + b") Tj ET")
        page.replace_contents(stream)
    output = BytesIO()
    writer.write(output)
    return output.getvalue()


def upload(client, content, *, title="Synthetic document", name="test.pdf", mime="application/pdf", patient_id=None):
    fields = {"title": title}
    if patient_id is not None:
        fields["patient_id"] = patient_id
    return client.post(DOCUMENTS, data=fields, files={"file": (name, content, mime)}, headers=ORIGIN)


def test_private_upload_download_and_review(client, storage):
    patient = account(client, "PATIENT", "owner")
    original = pdf(b"Synthetic extraction")
    response = upload(client, original, name="test document.pdf")
    assert response.status_code == 201
    assert response.headers["cache-control"] == "no-store"
    row = response.json()
    assert row["patient_id"] == patient["id"]
    assert row["uploaded_by"] == patient["user_id"]
    assert row["ocr_status"] == "completed"
    assert row["extracted_text"] == "Synthetic extraction"
    assert row["is_verified"] is False
    assert "storage_key" not in row
    stored, = list(storage.iterdir())
    assert UUID(hex=stored.name).hex == stored.name
    assert stored.name != UUID(row["id"]).hex
    assert stored.read_bytes() == original

    resource = f"{DOCUMENTS}/{row['id']}"
    download = client.get(f"{resource}/download")
    assert download.content == original
    assert download.headers["cache-control"] == "no-store"
    assert download.headers["x-content-type-options"] == "nosniff"
    assert download.headers["content-disposition"] == "attachment; filename*=UTF-8''test%20document.pdf"
    review_url = f"{resource}/verify"
    assert client.post(review_url, headers=ORIGIN, json={"extracted_text": " "}).status_code == 422
    verified = client.post(review_url, headers=ORIGIN, json={"extracted_text": "Reviewed synthetic text"})
    assert verified.status_code == 200
    assert verified.json()["extracted_text"] == "Reviewed synthetic text"
    assert verified.json()["is_verified"] is True
    assert verified.json()["verified_at"].endswith("Z")
    assert client.get(DOCUMENTS).json()["items"] == [verified.json()]
    assert client.get(f"/private_uploads/{stored.name}").status_code == 404

    with next(app.dependency_overrides[get_db]()) as db:
        persisted = db.get(PrivateDocument, row["id"])
        assert persisted.raw_text == "Synthetic extraction"
        assert persisted.reviewed_by == patient["user_id"]
        events = db.scalars(select(CareAuditEvent).where(CareAuditEvent.resource_id == row["id"])).all()
        assert {event.action for event in events} == {
            "document_uploaded", "document_downloaded", "document_ocr_reviewed",
        }


def test_document_specific_grants_and_link_revocation(client, storage):
    clinician, patient, link = linked_accounts(client)
    clinician_cookies = dict(client.cookies)
    clinician_file = upload(client, pdf(), patient_id=patient["id"]).json()
    assert clinician_file["ocr_status"] == "unsupported"
    sign_in(client, "patient")
    patient_file = upload(client, pdf()).json()
    patient_url = f"{DOCUMENTS}/{patient_file['id']}"
    clinician_url = f"{DOCUMENTS}/{clinician_file['id']}"
    access_url = f"{patient_url}/access/{clinician['id']}"
    assert client.get(f"{clinician_url}/download").status_code == 200
    account(client, "PATIENT", "outsider")
    assert client.get(DOCUMENTS).json()["items"] == []
    assert client.get(f"{patient_url}/download").status_code == 404
    assert client.post(access_url, headers=ORIGIN).status_code == 404
    assert upload(client, pdf(), patient_id=patient["id"]).status_code == 404

    sign_in(client, "clinician")
    professional_filters = {"patient_id": patient["id"]}
    assert client.get(DOCUMENTS, params=professional_filters).json()["items"] == [clinician_file]
    assert client.get(f"{patient_url}/download").status_code == 404
    assert client.post(access_url, headers=ORIGIN).status_code == 403
    assert client.post(f"{patient_url}/verify", headers=ORIGIN, json={"extracted_text": "Synthetic"}).status_code == 404

    sign_in(client, "patient")
    assert client.post(access_url, headers=ORIGIN).status_code == 204
    sign_in(client, "clinician")
    assert client.get(f"{patient_url}/download").status_code == 200
    assert client.post(f"{patient_url}/verify", headers=ORIGIN, json={"extracted_text": "Manual transcription"}).json()[
        "is_verified"
    ] is True
    sign_in(client, "patient")
    assert client.delete(access_url, headers=ORIGIN).status_code == 204
    sign_in(client, "clinician")
    assert client.get(f"{patient_url}/download").status_code == 404
    assert client.get(f"{clinician_url}/download").status_code == 200

    sign_in(client, "patient")
    assert client.post(access_url, headers=ORIGIN).status_code == 204
    assert transition(client, link, "revoke").status_code == 204
    next_link = request(client, clinician).json()["id"]
    client.cookies.clear()
    client.cookies.update(clinician_cookies)
    assert client.get(DOCUMENTS, params=professional_filters).status_code == 404
    assert client.get(f"{clinician_url}/download").status_code == 404
    assert upload(client, pdf(), patient_id=patient["id"]).status_code == 404
    assert transition(client, next_link, "accept").status_code == 200
    assert client.get(DOCUMENTS, params=professional_filters).json()["items"] == []
    assert client.get(f"{patient_url}/download").status_code == 404


def test_rejects_malicious_uploads_and_reports_bounded_ocr_failure(client, storage):
    account(client, "PATIENT", "owner")
    for name, mime, contents, expected in (
        ("../test.pdf", "application/pdf", pdf(), 422),
        ("test.txt", "application/pdf", pdf(), 415),
        ("test.png", "image/png", pdf(), 415),
        ("test.pdf", "image/png", pdf(), 415),
        ("test.pdf", "application/pdf", b"%PDF-1.7\nnot a pdf\n%%EOF", 415),
        ("test.png", "image/png", b"\x89PNG\r\n\x1a\ncorrupt", 415),
        ("test.png", "image/png", bytes(MAX_MULTIPART_BYTES), 413),
    ):
        response = upload(client, contents, name=name, mime=mime)
        assert response.status_code == expected, (name, response.json())
    assert not storage.exists()
    assert client.get(DOCUMENTS).json()["items"] == []

    png = BytesIO()
    Image.new("RGB", (24, 24), color="white").save(png, "PNG")
    result = upload(client, png.getvalue(), name="test.png", mime="image/png")
    assert result.status_code == 201
    assert result.json()["ocr_status"] == "failed"
    assert result.json()["extracted_text"] is None
    assert "missing-tesseract" not in result.json()["ocr_error"]
    client.cookies.clear()
    assert upload(client, pdf()).status_code == 401
    assert client.get(f"{DOCUMENTS}/{result.json()['id']}/download").status_code == 401


def test_storage_rejects_paths_outside_the_private_directory(tmp_path):
    from app.core.document_storage import document_path

    for bad_key in ("../test.pdf", str(Path.cwd() / "test.pdf"), "test.pdf"):
        with pytest.raises(ValueError):
            document_path(tmp_path, bad_key)


def test_image_worker_sends_normalized_image_to_tesseract(monkeypatch):
    from subprocess import CompletedProcess

    from app.services import document_ocr

    def tesseract(arguments, *, input, timeout, env, **kwargs):
        assert arguments == ["synthetic-tesseract", "stdin", "stdout", "-l", "por+eng"]
        assert timeout == 12
        assert env["OMP_THREAD_LIMIT"] == "1"
        with Image.open(BytesIO(input)) as normalized:
            assert normalized.format == "PNG"
            assert normalized.mode == "L"
        return CompletedProcess(arguments, 0, stdout=b" Synthetic output\n")

    monkeypatch.setattr(document_ocr.subprocess, "run", tesseract)
    original = BytesIO()
    Image.new("RGB", (24, 24), color="white").save(original, "JPEG")
    assert document_ocr.extract_image(original.getvalue(), "image/jpeg", "synthetic-tesseract", "por+eng") == (
        "completed", "Synthetic output", None,
    )
