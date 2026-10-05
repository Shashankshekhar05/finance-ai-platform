"""AI answer route. Thin: guard → one service call → typed answer.

POST /ai/answer (viewer and above — answering is read-only). The body
carries a question plus allowlisted backend evidence SPECS (calculation /
retrieval requests), never evidence itself: the service resolves them
through tenant-scoped services before any provider call.
"""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import get_db, get_llm_client, get_settings, require_viewer
from app.schemas.ai import AnswerRequest, AnswerResponse
from app.services import answer_service
from app.services.groq_client import GroqClient
from app.services.tenancy import TenantContext

router = APIRouter(tags=["ai"])


@router.post("/ai/answer", response_model=AnswerResponse)
def post_answer(
    payload: AnswerRequest,
    ctx: TenantContext = Depends(require_viewer),
    session: Session = Depends(get_db),
    llm_client: GroqClient = Depends(get_llm_client),
) -> AnswerResponse:
    return answer_service.answer_question(
        session,
        company_id=ctx.company_id,
        question=payload.question,
        calculation=payload.calculation,
        retrieval=payload.retrieval,
        settings=get_settings(),
        llm_client=llm_client,
    )
