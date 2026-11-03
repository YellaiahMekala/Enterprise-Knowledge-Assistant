"""Document endpoints: upload, list, read, delete (TDD 6.1). All are owner-scoped: the user id
comes from the credential, and another user's id returns 404."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, File, Query, Response, UploadFile
from fastapi.responses import Response as PlainResponse

from eka.api.deps import CurrentPrincipal, DocumentServices, MaxUploadBytes
from eka.api.schemas import NOT_FOUND_RESPONSE, UNAUTHORIZED_RESPONSE, DocumentList, DocumentOut
from eka.domain.errors import PayloadTooLarge
from eka.domain.models import DocumentStatus

router = APIRouter(prefix="/api/v1/documents", tags=["documents"])

_UPLOAD_ERRORS: dict[int | str, dict[str, object]] = {
    **UNAUTHORIZED_RESPONSE,
    200: {"model": DocumentOut, "description": "Identical bytes were already uploaded."},
    403: {"description": "Document quota reached."},
    413: {"description": "File too large."},
    415: {"description": "Unsupported file type, or the bytes do not match the type."},
}


@router.post("", status_code=202, responses=_UPLOAD_ERRORS)
async def upload_document(
    response: Response,
    principal: CurrentPrincipal,
    services: DocumentServices,
    max_upload_bytes: MaxUploadBytes,
    file: Annotated[UploadFile, File(description="PDF, DOCX, CSV, or a code/text file")],
) -> DocumentOut:
    """Upload one file. A new file returns 202 and is ingested in the background; poll the
    document until ``status`` is ``ready`` or ``failed``. The same bytes again return 200 with
    the existing document."""
    if file.size is not None and file.size > max_upload_bytes:
        raise PayloadTooLarge()
    data = await file.read(max_upload_bytes + 1)
    async with services(principal.user_id, principal.role) as service:
        document, created = await service.upload(
            principal.user_id, file.filename, file.content_type, data
        )
    if created:
        response.headers["Location"] = f"/api/v1/documents/{document.id}"
    else:
        response.status_code = 200
    return DocumentOut.from_domain(document)


@router.get("", responses=UNAUTHORIZED_RESPONSE)
async def list_documents(
    principal: CurrentPrincipal,
    services: DocumentServices,
    status: DocumentStatus | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> DocumentList:
    """The caller's documents, newest first."""
    async with services(principal.user_id, principal.role) as service:
        documents = await service.list(principal.user_id, status=status, limit=limit, offset=offset)
    return DocumentList(
        items=[DocumentOut.from_domain(d) for d in documents], limit=limit, offset=offset
    )


@router.get("/{document_id}", responses={**UNAUTHORIZED_RESPONSE, **NOT_FOUND_RESPONSE})
async def get_document(
    document_id: UUID, principal: CurrentPrincipal, services: DocumentServices
) -> DocumentOut:
    async with services(principal.user_id, principal.role) as service:
        document = await service.get(principal.user_id, document_id)
    return DocumentOut.from_domain(document)


@router.delete(
    "/{document_id}",
    status_code=204,
    responses={**UNAUTHORIZED_RESPONSE, **NOT_FOUND_RESPONSE},
)
async def delete_document(
    document_id: UUID, principal: CurrentPrincipal, services: DocumentServices
) -> PlainResponse:
    """Delete the document, its chunks and its stored file."""
    async with services(principal.user_id, principal.role) as service:
        await service.delete(principal.user_id, document_id)
    return PlainResponse(status_code=204)
