"""Document tools: search and read (read-only)."""
from __future__ import annotations

from pydantic import Field

from app.core.types import ToolContext, ToolParams, ToolResult
from app.services.common import join_words, note_untrusted_addresses, require_ok, untrusted
from app.utils.timeparse import fmt_date, to_local

CONTENT_LIMIT = 3000


class SearchDocumentsParams(ToolParams):
    query: str = Field(min_length=1, max_length=200)
    limit: int = Field(5, ge=1, le=10)


class ReadDocumentParams(ToolParams):
    document_id: str = Field(min_length=1, max_length=40)


def search_documents(ctx: ToolContext, p: SearchDocumentsParams) -> ToolResult:
    res = ctx.adapters.documents.search(ctx.user.id, query=p.query, limit=p.limit)
    rows = require_ok(res, "document library")
    items = [{
        "document_id": d.id, "title": d.title,
        "updated": fmt_date(to_local(d.updated_at, ctx.tz).date(), ctx.today),
        "preview": untrusted(" ".join(d.content.split()), 140)["text"],
    } for d in rows]
    if not items:
        speech = f"I found no documents matching {p.query}."
    else:
        speech = (f"I found {len(items)} document{'s' if len(items) != 1 else ''}: "
                  f"{join_words([it['title'] for it in items])}.")
    ctx.remember(last_document_ids=[it["document_id"] for it in items])
    return ToolResult(speech=speech, data={"count": len(items), "documents": items, "preview_trust": "untrusted"})


def read_document(ctx: ToolContext, p: ReadDocumentParams) -> ToolResult:
    doc = require_ok(ctx.adapters.documents.get(ctx.user.id, p.document_id), "document")
    note_untrusted_addresses(ctx, doc.content)
    return ToolResult(
        speech=f"I have the document '{doc.title}'. Its text is included for you to summarise.",
        data={"document_id": doc.id, "title": doc.title,
              "updated": fmt_date(to_local(doc.updated_at, ctx.tz).date(), ctx.today),
              "content": untrusted(doc.content, CONTENT_LIMIT)},
    )
