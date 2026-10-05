"""AI query route. Thin: guard → one orchestrator call → typed answer.

POST /ai/query (viewer and above — answering is read-only). The body
carries a question plus OPTIONAL controlled specs; the deterministic
router derives anything missing from the question text. POST /ai/answer
remains available unchanged.
"""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import get_db, get_llm_client, get_settings, require_viewer
from app.schemas.ai import AnswerResponse
from app.schemas.ai_query import QueryRequest
from app.services import ai_query_service
from app.services.groq_client import GroqClient
from app.services.tenancy import TenantContext

router = APIRouter(tags=["ai"])


@router.post("/ai/query", response_model=AnswerResponse)
def post_query(
    payload: QueryRequest,
    ctx: TenantContext = Depends(require_viewer),
    session: Session = Depends(get_db),
    llm_client: GroqClient = Depends(get_llm_client),
) -> AnswerResponse:
    return ai_query_service.answer_query(
        session,
        ctx=ctx,
        request=payload,
        settings=get_settings(),
        llm_client=llm_client,
    )
