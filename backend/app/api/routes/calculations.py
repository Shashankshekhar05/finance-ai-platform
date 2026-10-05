"""Calculation route. Thin: guard → one service call → typed result.

POST /calculations (viewer and above — calculations are read-only).
No company_id in the body: tenant scope comes only from the token.
"""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import get_db, require_viewer
from app.schemas.calculation import CalculationRequest, CalculationResponse
from app.services import calculation_service
from app.services.tenancy import TenantContext

router = APIRouter(tags=["calculations"])


@router.post("/calculations", response_model=CalculationResponse)
def run_calculation(
    payload: CalculationRequest,
    ctx: TenantContext = Depends(require_viewer),
    session: Session = Depends(get_db),
) -> CalculationResponse:
    return calculation_service.calculate(
        session, company_id=ctx.company_id, request=payload
    )
