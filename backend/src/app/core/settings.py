from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    app_name: str = "news-price-forecaster"
    api_host: str = "0.0.0.0"
    api_port: int = 8000
    backend_cors_origins: str = "http://localhost:3000,http://frontend"
    model_name: str = "cointegrated/rubert-tiny"
    model_checkpoint_path: str = "/models/model_rubert-tiny1.pt"
    model_local_files_only: bool = False
    default_assets: str = "LKOH,IMOEX,BZ=F"
    default_asset: str = "LKOH"
    default_period: int = 7
    history_days: int = 365
    index_window: int = 3
    ewma_lambda: float = 0.94
    ridge_alpha: float = 0.0001
    max_daily_signal_impact: float = 0.03
    http_timeout: float = 20

    @property
    def cors_origins(self) -> list[str]:
        return [x.strip() for x in self.backend_cors_origins.split(",") if x.strip()]

    @property
    def assets(self) -> tuple[str, ...]:
        return tuple(x.strip() for x in self.default_assets.split(",") if x.strip())


settings = Settings()
