from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import router
from app.core.settings import settings
from app.services.forecaster import AsyncNewsPriceForecaster, NewsPriceForecasterConfig


@asynccontextmanager
async def lifespan(app: FastAPI):
    config = NewsPriceForecasterConfig(
        model_name=settings.model_name,
        checkpoint_path=settings.model_checkpoint_path,
        local_files_only=settings.model_local_files_only,
        default_assets=settings.assets,
        history_days=settings.history_days,
        index_window=settings.index_window,
        ewma_lambda=settings.ewma_lambda,
        ridge_alpha=settings.ridge_alpha,
        max_daily_signal_impact=settings.max_daily_signal_impact,
        http_timeout=settings.http_timeout,
    )
    app.state.forecaster = await AsyncNewsPriceForecaster.create(config=config, assets=settings.assets)
    yield


app = FastAPI(title=settings.app_name, lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(router)
