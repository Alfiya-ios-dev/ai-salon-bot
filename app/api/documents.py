from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth_dependencies import get_current_tenant_db
from app.models import RagDocument
from app.schemas import DocumentResponse

router = APIRouter()


def _to_document_response(doc: RagDocument) -> DocumentResponse:
    # Falls back to title for any row that predates the filename column
    # (e.g. freeform knowledge seeded directly, not via /upload).
    return DocumentResponse(id=doc.id, filename=doc.filename or doc.title, created_at=doc.created_at)


@router.get("", response_model=list[DocumentResponse])
async def list_documents(db: AsyncSession = Depends(get_current_tenant_db)):
    result = await db.execute(select(RagDocument).order_by(RagDocument.id))
    return [_to_document_response(doc) for doc in result.scalars().all()]


@router.post("/upload", response_model=DocumentResponse, status_code=201)
async def upload_document(
    file: UploadFile = File(...),
    title: str | None = Form(None),
    db: AsyncSession = Depends(get_current_tenant_db),
):
    """Stores an uploaded document as a RagDocument, so it's immediately
    picked up by knowledge_service.py and fed into the AI's prompt context.

    Only UTF-8 text content is supported (.txt, .md, ...) — there's no
    PDF/DOCX text-extraction library in this project yet, so binary formats
    are rejected rather than stored unusably.
    """
    raw = await file.read()
    try:
        content = raw.decode("utf-8")
    except UnicodeDecodeError:
        raise HTTPException(
            status_code=400,
            detail="Only UTF-8 text files are supported (.txt, .md) — binary formats like PDF/DOCX aren't parsed yet.",
        )
    if not content.strip():
        raise HTTPException(status_code=400, detail="Uploaded file is empty")

    doc = RagDocument(
        title=title or file.filename or "Документ",
        filename=file.filename,
        content=content,
    )
    db.add(doc)
    await db.commit()
    await db.refresh(doc)
    return _to_document_response(doc)


@router.delete("/{document_id}", status_code=204)
async def delete_document(document_id: int, db: AsyncSession = Depends(get_current_tenant_db)):
    doc = await db.get(RagDocument, document_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="Document not found")
    await db.delete(doc)
    await db.commit()
