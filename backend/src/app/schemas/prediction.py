from datetime import date
from pydantic import BaseModel, Field, field_validator


class NewsItem(BaseModel):
    date: date
    text: str

    @field_validator("text")
    @classmethod
    def text_not_empty(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("text must not be empty")
        return value


class PredictRequest(BaseModel):
    asset: str
    period: int = Field(gt=0)
    news: list[NewsItem]

    @field_validator("news")
    @classmethod
    def news_not_empty(cls, value: list[NewsItem]) -> list[NewsItem]:
        if not value:
            raise ValueError("news must not be empty")
        return value


class UpdateRequest(BaseModel):
    assets: list[str] | None = None
