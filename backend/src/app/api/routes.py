import asyncio
import logging
from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile

from app.core.settings import settings
from app.schemas.prediction import PredictRequest, UpdateRequest
from app.services.excel_parser import parse_news_excel

router = APIRouter()
logger = logging.getLogger(__name__)


@router.get('/health')
async def health() -> dict[str, str]:
    return {"status": "ok"}


@router.post('/api/predict')
async def predict(payload: PredictRequest, request: Request):
    forecaster = request.app.state.forecaster
    return await forecaster.predict(payload.model_dump(mode='json'))


@router.post('/api/predict/file')
async def predict_file(request: Request, file: UploadFile = File(...), asset: str = Form(...), period: int = Form(...)):
    if period <= 0:
        raise HTTPException(status_code=422, detail="period должен быть > 0")
    if not (file.filename or '').lower().endswith((".xlsx", ".xls")):
        raise HTTPException(status_code=400, detail="Поддерживаются только .xlsx/.xls")
    file_bytes = await file.read()
    try:
        news = await asyncio.to_thread(parse_news_excel, file_bytes)
    except Exception as exc:
        logger.exception('Excel parse failed')
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    forecaster = request.app.state.forecaster
    return await forecaster.predict({"asset": asset, "period": period, "news": news})


@router.post('/api/update')
async def update(payload: UpdateRequest, request: Request):
    forecaster = request.app.state.forecaster
    assets = payload.assets or list(settings.assets)
    try:
        loaded = await forecaster.update(assets=assets)
        return {"status": "ok", "loaded": loaded}
    except Exception:
        logger.exception('Update failed')
        raise HTTPException(status_code=500, detail="Произошла ошибка. Попробуйте позже.")
