from __future__ import annotations

import asyncio
import logging
import math
import re
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import httpx
import numpy as np
import pandas as pd
import torch
import yfinance as yf
from nltk.stem.snowball import SnowballStemmer
from transformers import BertForSequenceClassification, BertTokenizerFast

logger = logging.getLogger(__name__)


class MarketDataUnavailableError(RuntimeError):
    """Raised when a market data provider cannot return usable history."""


@dataclass(frozen=True, slots=True)
class NewsPriceForecasterConfig:
    model_name: str = "cointegrated/rubert-tiny"
    checkpoint_path: str | Path | None = "model_rubert-tiny1.pt"
    local_files_only: bool = False
    default_assets: tuple[str, ...] = ("BZ=F", "LKOH", "IMOEX")
    history_days: int = 365
    max_length: int = 128
    batch_size: int = 64
    index_window: int = 3
    long_bias: float = 0.7
    short_bias: float = 0.3
    stable_long_weight: float = 0.3
    stable_short_weight: float = 0.2
    index_scale: float = 2.0
    ewma_lambda: float = 0.94
    ridge_alpha: float = 1e-4
    max_daily_signal_impact: float = 0.03
    signal_temperature: float = 10.0
    signal_momentum_temperature: float = 5.0
    future_index_decay: float = 0.85
    future_freq: str = "D"
    http_timeout: float = 20.0
    moex_base_url: str = "https://iss.moex.com/iss"
    yfinance_aliases: dict[str, str] = field(
        default_factory=lambda: {
            "LKOH": "LKOH.ME",
            "SBER": "SBER.ME",
            "SBERP": "SBERP.ME",
            "GAZP": "GAZP.ME",
            "ROSN": "ROSN.ME",
            "GMKN": "GMKN.ME",
            "NVTK": "NVTK.ME",
            "TATN": "TATN.ME",
            "TATNP": "TATNP.ME",
            "IMOEX": "IMOEX.ME",
            "RTSI": "RTSI.ME",
        }
    )
    labels: dict[int, str] = field(
        default_factory=lambda: {
            0: "increase",
            1: "stable",
            2: "fall",
        }
    )


class AsyncNewsPriceForecaster:
    _MOEX_INDEX_ASSETS = frozenset({"IMOEX", "RTSI", "MOEXBC", "MOEXOG", "MOEXFN", "MOEXMM"})

    def __init__(
        self,
        config: NewsPriceForecasterConfig | None = None,
        device: str | torch.device | None = None,
    ) -> None:
        self.config = config or NewsPriceForecasterConfig()
        self.device = torch.device(device or ("cuda" if torch.cuda.is_available() else "cpu"))
        self.tokenizer: BertTokenizerFast | None = None
        self.model: BertForSequenceClassification | None = None
        self._stemmer = SnowballStemmer("russian")
        self._price_cache: dict[str, pd.DataFrame] = {}
        self._model_lock = asyncio.Lock()
        self._price_lock = asyncio.Lock()

    @classmethod
    async def create(
        cls,
        config: NewsPriceForecasterConfig | None = None,
        device: str | torch.device | None = None,
        assets: tuple[str, ...] | list[str] | None = None,
    ) -> "AsyncNewsPriceForecaster":
        instance = cls(config=config, device=device)
        await instance._load_model()
        try:
            await instance.update(assets=tuple(assets or instance.config.default_assets))
        except MarketDataUnavailableError as exc:
            # Не блокируем старт FastAPI из-за временной недоступности провайдера.
            # При первом /api/predict сервис повторит загрузку нужного актива.
            logger.warning("Initial market data loading failed: %s", exc)
        return instance

    async def available_assets(self) -> list[str]:
        async with self._price_lock:
            cached_assets = {
                asset
                for asset, frame in self._price_cache.items()
                if frame is not None and not frame.empty
            }
        ordered_assets: list[str] = []
        for asset in self.config.default_assets:
            normalized_asset = self._normalize_asset(asset)
            if normalized_asset in cached_assets and normalized_asset not in ordered_assets:
                ordered_assets.append(normalized_asset)
        ordered_assets.extend(sorted(cached_assets - set(ordered_assets)))
        return ordered_assets

    async def update(
        self,
        assets: tuple[str, ...] | list[str] | str | None = None,
        start: str | date | datetime | None = None,
        end: str | date | datetime | None = None,
    ) -> dict[str, int]:
        if assets is None:
            assets_tuple = self.config.default_assets
        elif isinstance(assets, str):
            assets_tuple = (assets,)
        else:
            assets_tuple = tuple(assets)
        end_date = self._to_date(end) if end else date.today() + timedelta(days=1)
        start_date = (
            self._to_date(start)
            if start
            else end_date - timedelta(days=self.config.history_days)
        )
        if start_date >= end_date:
            end_date = start_date + timedelta(days=1)
        normalized_assets = tuple(self._normalize_asset(asset) for asset in assets_tuple)
        tasks = [
            self._load_market_history(asset, start_date, end_date)
            for asset in normalized_assets
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        loaded: dict[str, int] = {}
        errors: dict[str, str] = {}
        async with self._price_lock:
            for asset, result in zip(normalized_assets, results, strict=True):
                if isinstance(result, Exception):
                    errors[asset] = str(result)
                    continue
                if result.empty:
                    errors[asset] = "empty market dataframe"
                    continue
                existing = self._price_cache.get(asset)
                if existing is not None and not existing.empty:
                    result = self._merge_market_history(existing, result)
                self._price_cache[asset] = result
                loaded[asset] = int(len(result))
        if errors and not loaded:
            raise MarketDataUnavailableError(f"Market data update failed: {errors}")
        if errors:
            logger.warning("Some market data assets were not loaded: %s", errors)
        return loaded

    async def predict(self, payload: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
        asset = self._normalize_asset(str(payload["asset"]))
        period = int(payload["period"])
        news = payload.get("news", [])
        if period <= 0:
            raise ValueError("period должен быть положительным числом дней")
        if not isinstance(news, list):
            raise ValueError("news должен быть списком словарей")

        news_bounds = self._news_date_bounds(news)
        await self._ensure_asset_loaded(asset, news_bounds, period=period)
        async with self._price_lock:
            market_df = self._price_cache[asset].copy()
        if market_df.empty:
            raise MarketDataUnavailableError(f"Нет рыночных данных для asset={asset}")

        news_df = await self._classify_news(news)
        model_history_df = self._select_history(market_df, news_df, news_bounds=news_bounds)
        if model_history_df.empty:
            raise MarketDataUnavailableError(f"Нет исторических цен для asset={asset}")

        forecast_start = pd.Timestamp(model_history_df.index[-1]).normalize()
        forecast_end = forecast_start + pd.Timedelta(days=period)
        visible_history_df = self._select_visible_history(
            market_df=market_df,
            model_history_df=model_history_df,
            forecast_end=forecast_end,
        )

        aligned_news = self._align_news_to_market_dates(news_df, model_history_df.index)
        daily_counts = self._prepare_daily_counts(aligned_news, model_history_df.index)
        index_df = self._compute_index(daily_counts)
        signals = self._compute_signal(index_df["index"])
        mu, sigma, beta = self._estimate_price_params(model_history_df["log_return"], signals)
        history_rows = self._build_history_rows(visible_history_df)
        forecast_rows = self._build_forecast_rows(
            history_df=model_history_df,
            index_df=index_df,
            daily_counts=daily_counts,
            period=period,
            mu=mu,
            sigma=sigma,
            beta=beta,
        )
        return {
            "history": history_rows,
            "forecast": forecast_rows,
            "meta": {
                "forecast_start_date": self._timestamp(forecast_start),
                "forecast_end_date": self._timestamp(forecast_end),
                "actual_history_end_date": self._timestamp(visible_history_df.index[-1]),
            },
        }

    async def _load_model(self) -> None:
        tokenizer, model = await asyncio.to_thread(self._load_model_sync)
        self.tokenizer = tokenizer
        self.model = model

    def _load_model_sync(self) -> tuple[BertTokenizerFast, BertForSequenceClassification]:
        tokenizer = BertTokenizerFast.from_pretrained(
            self.config.model_name,
            local_files_only=self.config.local_files_only,
        )
        model = BertForSequenceClassification.from_pretrained(
            self.config.model_name,
            num_labels=3,
            local_files_only=self.config.local_files_only,
        )
        checkpoint_path = Path(self.config.checkpoint_path) if self.config.checkpoint_path else None
        if checkpoint_path and checkpoint_path.exists():
            state_dict = torch.load(checkpoint_path, map_location=self.device)
            model.load_state_dict(state_dict)
        model.to(self.device)
        model.eval()
        return tokenizer, model

    async def _classify_news(self, news: list[dict[str, Any]]) -> pd.DataFrame:
        if not news:
            return pd.DataFrame(columns=["date", "text", "prediction"])
        rows: list[dict[str, Any]] = []
        texts: list[str] = []
        for item in news:
            text = str(item.get("text", "")).strip()
            if not text:
                continue
            rows.append({"date": pd.to_datetime(item["date"]).normalize(), "text": text})
            texts.append(self._preprocess_text(text))
        if not rows:
            return pd.DataFrame(columns=["date", "text", "prediction"])
        async with self._model_lock:
            labels = await asyncio.to_thread(self._predict_labels_sync, texts)
        df = pd.DataFrame(rows)
        df["prediction"] = labels
        return df

    def _predict_labels_sync(self, texts: list[str]) -> list[int]:
        if self.tokenizer is None or self.model is None:
            raise RuntimeError("Model is not loaded")
        labels: list[int] = []
        for start in range(0, len(texts), self.config.batch_size):
            batch = texts[start : start + self.config.batch_size]
            inputs = self.tokenizer(
                batch,
                return_tensors="pt",
                truncation=True,
                padding=True,
                max_length=self.config.max_length,
            )
            inputs = {key: value.to(self.device) for key, value in inputs.items()}
            with torch.inference_mode():
                logits = self.model(**inputs).logits
            labels.extend(torch.argmax(logits, dim=1).detach().cpu().tolist())
        return labels

    def _preprocess_text(self, text: str) -> str:
        tokens = re.findall(r"[А-Яа-яЁёA-Za-z]+", text.lower())
        stems = [self._stemmer.stem(token) for token in tokens]
        return " ".join(stems)

    def _news_date_bounds(self, news: list[dict[str, Any]]) -> tuple[date, date] | None:
        news_dates: list[date] = []
        for item in news:
            if item.get("date") is None:
                continue
            news_dates.append(pd.to_datetime(item["date"]).date())
        if not news_dates:
            return None
        return min(news_dates), max(news_dates)

    def _required_market_range(
        self,
        news_bounds: tuple[date, date] | None,
        period: int = 0,
    ) -> tuple[date, date] | None:
        if news_bounds is None:
            return None
        min_news_date, max_news_date = news_bounds
        forecast_days = max(int(period), 0)
        start = min_news_date - timedelta(days=self.config.index_window + 3)
        # yfinance treats `end` as exclusive; MOEX tolerates the extra day as well.
        # Загружаем также прогнозный интервал: если на нем уже есть фактические
        # биржевые цены, frontend покажет их как продолжение исторической линии,
        # не сдвигая и не обрезая прогнозную кривую.
        end = max_news_date + timedelta(days=forecast_days + 1)
        return start, end

    async def _ensure_asset_loaded(
        self,
        asset: str,
        news_bounds: tuple[date, date] | None,
        period: int = 0,
    ) -> None:
        required_range = self._required_market_range(news_bounds, period=period)
        async with self._price_lock:
            cached = self._price_cache.get(asset)

        if cached is None or cached.empty:
            if required_range is None:
                await self.update(assets=(asset,))
            else:
                await self.update(assets=(asset,), start=required_range[0], end=required_range[1])
            return

        if required_range is None:
            return

        min_required, end_required = required_range
        cached_start = cached.index.min().date()
        cached_end_exclusive = cached.index.max().date() + timedelta(days=1)
        if min_required < cached_start or end_required > cached_end_exclusive:
            await self.update(
                assets=(asset,),
                start=min(min_required, cached_start),
                end=max(end_required, cached_end_exclusive),
            )

    async def _load_market_history(
        self,
        asset: str,
        start: date,
        end: date,
    ) -> pd.DataFrame:
        if asset == "BZ=F":
            return await self._load_yfinance_history("BZ=F", start, end)
        if self._looks_like_moex_asset(asset):
            try:
                return await self._load_moex_history(asset, start, end)
            except Exception as moex_exc:  # noqa: BLE001 - fallback to yfinance alias if available
                yf_ticker = self.config.yfinance_aliases.get(asset)
                if not yf_ticker:
                    raise
                logger.warning("MOEX load failed for %s, trying yfinance %s: %s", asset, yf_ticker, moex_exc)
                return await self._load_yfinance_history(yf_ticker, start, end)
        return await self._load_yfinance_history(asset, start, end)

    def _looks_like_moex_asset(self, asset: str) -> bool:
        if asset in self._MOEX_INDEX_ASSETS:
            return True
        return bool(re.fullmatch(r"[A-Z]{4,5}P?", asset)) and not asset.endswith("=F")

    async def _load_yfinance_history(
        self,
        ticker: str,
        start: date,
        end: date,
    ) -> pd.DataFrame:
        def download() -> pd.DataFrame:
            raw = yf.download(
                ticker,
                start=start.isoformat(),
                end=end.isoformat(),
                interval="1d",
                progress=False,
                threads=False,
                auto_adjust=True,
                multi_level_index=False,
            )
            if raw is None or raw.empty:
                return pd.DataFrame(columns=["price", "log_return"])
            if isinstance(raw.columns, pd.MultiIndex):
                raw.columns = [
                    "_".join(str(part) for part in col if part).strip()
                    for col in raw.columns.to_flat_index()
                ]
            close_col = self._find_close_column(raw)
            df = raw[[close_col]].rename(columns={close_col: "price"})
            df.index = pd.to_datetime(df.index).tz_localize(None).normalize()
            df["price"] = pd.to_numeric(df["price"], errors="coerce")
            df = df.dropna(subset=["price"])
            df["log_return"] = np.log(df["price"] / df["price"].shift(1))
            return df[["price", "log_return"]].sort_index()
        return await asyncio.to_thread(download)

    async def _load_moex_history(
        self,
        ticker: str,
        start: date,
        end: date,
    ) -> pd.DataFrame:
        errors: list[str] = []
        async with httpx.AsyncClient(timeout=self.config.http_timeout) as client:
            for url in self._moex_history_urls(ticker):
                params: dict[str, Any] = {
                    "from": start.isoformat(),
                    "till": end.isoformat(),
                    "start": 0,
                    "limit": 100,
                    "iss.meta": "off",
                }
                chunks: list[pd.DataFrame] = []
                try:
                    while True:
                        response = await client.get(url, params=params)
                        response.raise_for_status()
                        data = response.json()
                        block = data.get("history") or data.get("historydata")
                        if not block:
                            break
                        columns = block.get("columns", [])
                        rows = block.get("data", [])
                        if not rows:
                            break
                        chunks.append(pd.DataFrame(rows, columns=columns))
                        if len(rows) < int(params["limit"]):
                            break
                        params["start"] = int(params["start"]) + int(params["limit"])
                except Exception as exc:  # noqa: BLE001 - try alternate MOEX URL before failing
                    errors.append(f"{url}: {exc}")
                    continue

                if not chunks:
                    errors.append(f"{url}: empty history")
                    continue

                raw = pd.concat(chunks, ignore_index=True)
                try:
                    df = self._moex_history_to_frame(raw, ticker)
                except Exception as exc:  # noqa: BLE001
                    errors.append(f"{url}: {exc}")
                    continue
                if not df.empty:
                    return df
                errors.append(f"{url}: empty dataframe")

        raise MarketDataUnavailableError(f"MOEX history is unavailable for {ticker}: {'; '.join(errors)}")

    def _moex_history_urls(self, ticker: str) -> tuple[str, ...]:
        base = self.config.moex_base_url.rstrip("/")
        if ticker in self._MOEX_INDEX_ASSETS:
            return (
                f"{base}/history/engines/stock/markets/index/securities/{ticker}.json",
                f"{base}/history/engines/stock/markets/index/boards/SNDX/securities/{ticker}.json",
            )
        return (
            f"{base}/history/engines/stock/markets/shares/boards/TQBR/securities/{ticker}.json",
            f"{base}/history/engines/stock/markets/shares/securities/{ticker}.json",
        )

    def _moex_history_to_frame(self, raw: pd.DataFrame, ticker: str) -> pd.DataFrame:
        date_col = "TRADEDATE" if "TRADEDATE" in raw.columns else None
        close_col = "CLOSE" if "CLOSE" in raw.columns else None
        if date_col is None or close_col is None:
            raise RuntimeError(f"MOEX response does not contain TRADEDATE/CLOSE for {ticker}")
        df = raw[[date_col, close_col]].rename(columns={date_col: "date", close_col: "price"})
        df["date"] = pd.to_datetime(df["date"], errors="coerce").dt.normalize()
        df["price"] = pd.to_numeric(df["price"], errors="coerce")
        df = df.dropna(subset=["date", "price"]).drop_duplicates(subset=["date"])
        if df.empty:
            return pd.DataFrame(columns=["price", "log_return"])
        df = df.set_index("date").sort_index()
        df["log_return"] = np.log(df["price"] / df["price"].shift(1))
        return df[["price", "log_return"]]

    def _select_history(
        self,
        market_df: pd.DataFrame,
        news_df: pd.DataFrame,
        news_bounds: tuple[date, date] | None = None,
    ) -> pd.DataFrame:
        if not news_df.empty or news_bounds is not None:
            start_date, anchor_date = news_bounds or (
                news_df["date"].min().date(),
                news_df["date"].max().date(),
            )
            start = pd.Timestamp(start_date) - pd.Timedelta(days=self.config.index_window + 3)
            end = pd.Timestamp(anchor_date).normalize()
            history = market_df.loc[(market_df.index >= start) & (market_df.index <= end)].copy()
            history = history.dropna(subset=["price"])
            if not history.empty:
                history = self._append_anchor_price_if_missing(history, end)
            return history
        history = market_df.tail(min(len(market_df), 60)).copy()
        return history.dropna(subset=["price"])

    def _select_visible_history(
        self,
        market_df: pd.DataFrame,
        model_history_df: pd.DataFrame,
        forecast_end: pd.Timestamp,
    ) -> pd.DataFrame:
        if model_history_df.empty:
            return model_history_df.copy()
        start = pd.Timestamp(model_history_df.index.min()).normalize()
        forecast_end = pd.Timestamp(forecast_end).normalize()
        visible_market_history = market_df.loc[
            (market_df.index >= start) & (market_df.index <= forecast_end)
        ].copy()
        visible_market_history = visible_market_history.dropna(subset=["price"])
        if visible_market_history.empty:
            return model_history_df.copy().sort_index()
        visible = self._merge_market_history(visible_market_history, model_history_df)
        return visible.loc[visible.index <= forecast_end].sort_index()

    def _align_news_to_market_dates(
        self,
        news_df: pd.DataFrame,
        market_index: pd.DatetimeIndex,
    ) -> pd.DataFrame:
        if news_df.empty:
            return news_df.copy()
        market_dates = pd.DatetimeIndex(market_index).sort_values()
        aligned = news_df.copy()
        assigned_dates: list[pd.Timestamp | pd.NaT] = []
        for news_date in aligned["date"]:
            position = market_dates.searchsorted(pd.Timestamp(news_date), side="left")
            if position >= len(market_dates):
                assigned_dates.append(pd.NaT)
            else:
                assigned_dates.append(market_dates[position])
        aligned["date"] = assigned_dates
        aligned = aligned.dropna(subset=["date"])
        return aligned

    def _prepare_daily_counts(
        self,
        news_df: pd.DataFrame,
        market_index: pd.DatetimeIndex,
    ) -> pd.DataFrame:
        columns = ["increase", "stable", "fall"]
        if news_df.empty:
            return pd.DataFrame(0, index=market_index, columns=columns)
        df = news_df.copy()
        df["label"] = df["prediction"].map(self.config.labels)
        df = df[df["label"].isin(columns)]
        daily = (
            df.groupby(["date", "label"])
            .size()
            .unstack(fill_value=0)
            .reindex(columns=columns, fill_value=0)
        )
        daily = daily.reindex(market_index, fill_value=0)
        daily.index = pd.to_datetime(daily.index).normalize()
        return daily.astype(int)

    def _compute_index(self, daily_counts: pd.DataFrame) -> pd.DataFrame:
        inc = daily_counts["increase"].rolling(self.config.index_window, min_periods=1).sum()
        stable = daily_counts["stable"].rolling(self.config.index_window, min_periods=1).sum()
        fall = daily_counts["fall"].rolling(self.config.index_window, min_periods=1).sum()
        index = (
            50.0
            + (inc * self.config.long_bias + stable * self.config.stable_long_weight)
            * self.config.index_scale
            - (fall * self.config.short_bias + stable * self.config.stable_short_weight)
            * self.config.index_scale
        )
        index = index.clip(lower=0.0, upper=100.0)
        result = pd.DataFrame(index=daily_counts.index)
        result["index"] = index
        result["index_diff"] = result["index"].diff().fillna(0.0)
        return result

    def _compute_signal(self, index_series: pd.Series) -> pd.Series:
        diff = index_series.diff().fillna(0.0)
        signal = np.tanh(
            ((index_series - 50.0) / self.config.signal_temperature)
            + (diff / self.config.signal_momentum_temperature)
        )
        return pd.Series(signal, index=index_series.index, name="signal")

    def _estimate_price_params(
        self,
        log_returns: pd.Series,
        signals: pd.Series,
    ) -> tuple[float, float, float]:
        returns = log_returns.dropna()
        if returns.empty:
            return 0.0, 0.0, 0.0
        lam = self.config.ewma_lambda
        alpha = 1.0 - lam
        mu = float(returns.ewm(alpha=alpha, adjust=False).mean().iloc[-1])
        variance = float((returns**2).ewm(alpha=alpha, adjust=False).mean().iloc[-1])
        sigma = math.sqrt(max(variance, 0.0))
        x = signals.shift(1).reindex(returns.index)
        y = returns.reindex(x.index)
        valid = ~(x.isna() | y.isna())
        x_values = x[valid].to_numpy(dtype=float)
        y_values = y[valid].to_numpy(dtype=float)
        if len(x_values) < 10 or np.nanvar(x_values) == 0:
            beta = 0.0
        else:
            x_centered = x_values - x_values.mean()
            y_centered = y_values - y_values.mean()
            beta = float(
                np.dot(x_centered, y_centered)
                / (np.dot(x_centered, x_centered) + self.config.ridge_alpha)
            )
        beta = float(
            np.clip(
                beta,
                -self.config.max_daily_signal_impact,
                self.config.max_daily_signal_impact,
            )
        )
        return mu, sigma, beta

    def _build_history_rows(self, history_df: pd.DataFrame) -> list[dict[str, Any]]:
        return [
            {
                "date": self._timestamp(index),
                "price": float(row["price"]),
            }
            for index, row in history_df.iterrows()
        ]

    def _build_forecast_rows(
        self,
        history_df: pd.DataFrame,
        index_df: pd.DataFrame,
        daily_counts: pd.DataFrame,
        period: int,
        mu: float,
        sigma: float,
        beta: float,
    ) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for dt, row in history_df.iterrows():
            counts = daily_counts.loc[dt]
            index_value = index_df.loc[dt, "index"]
            rows.append(
                {
                    "date": self._timestamp(dt),
                    "price": float(row["price"]),
                    "index": int(round(index_value)),
                    "increase": int(counts["increase"]),
                    "stable": int(counts["stable"]),
                    "fall": int(counts["fall"]),
                }
            )
        last_price = float(history_df["price"].iloc[-1])
        last_index = float(index_df["index"].iloc[-1])
        last_date = pd.Timestamp(history_df.index[-1])
        future_dates = pd.date_range(
            start=last_date + pd.Timedelta(days=1),
            periods=period,
            freq=self.config.future_freq,
        )
        for step, future_date in enumerate(future_dates, start=1):
            future_index = 50.0 + (last_index - 50.0) * (self.config.future_index_decay**step)
            future_signal = math.tanh((future_index - 50.0) / self.config.signal_temperature)
            next_log_return = mu + beta * future_signal - 0.5 * (sigma**2)
            last_price = last_price * math.exp(next_log_return)
            rows.append(
                {
                    "date": self._timestamp(future_date),
                    "price": float(last_price),
                    "index": int(round(float(np.clip(future_index, 0.0, 100.0)))),
                    "increase": 0,
                    "stable": 0,
                    "fall": 0,
                }
            )
        return rows

    @staticmethod
    def _merge_market_history(existing: pd.DataFrame, loaded: pd.DataFrame) -> pd.DataFrame:
        merged = pd.concat([existing, loaded]).sort_index()
        merged = merged[~merged.index.duplicated(keep="last")]
        merged["price"] = pd.to_numeric(merged["price"], errors="coerce")
        merged = merged.dropna(subset=["price"])
        merged["log_return"] = np.log(merged["price"] / merged["price"].shift(1))
        return merged[["price", "log_return"]]

    @staticmethod
    def _append_anchor_price_if_missing(history: pd.DataFrame, anchor: pd.Timestamp) -> pd.DataFrame:
        anchor = pd.Timestamp(anchor).normalize()
        last_date = pd.Timestamp(history.index.max()).normalize()
        if last_date >= anchor:
            return history.sort_index()
        # Небольшой разрыв обычно означает выходной/праздник: фиксируем последнюю
        # известную цену на дату последней новости, чтобы прогноз начинался строго от нее.
        if (anchor.date() - last_date.date()).days > 10:
            return history.sort_index()
        history = history.copy()
        history.loc[anchor, "price"] = float(history.loc[history.index.max(), "price"])
        history = history.sort_index()
        history["log_return"] = np.log(history["price"] / history["price"].shift(1))
        return history[["price", "log_return"]]

    @staticmethod
    def _find_close_column(df: pd.DataFrame) -> str:
        candidates = ["Close", "Adj Close", "price"]
        for candidate in candidates:
            if candidate in df.columns:
                return candidate
        close_columns = [column for column in df.columns if "Close" in str(column)]
        if close_columns:
            return close_columns[0]
        raise RuntimeError(f"Close column not found. Columns: {list(df.columns)}")

    @staticmethod
    def _normalize_asset(asset: str) -> str:
        normalized = asset.strip().upper()
        aliases = {
            "BRENT": "BZ=F",
            "BZ": "BZ=F",
            "BZ=F": "BZ=F",
            "LUKOIL": "LKOH",
            "LKOH": "LKOH",
            "MOEX": "IMOEX",
            "IMOEX": "IMOEX",
        }
        if normalized.startswith("MOEX:"):
            normalized = normalized.split(":", 1)[1]
        return aliases.get(normalized, normalized)

    @staticmethod
    def _to_date(value: str | date | datetime) -> date:
        if isinstance(value, datetime):
            return value.date()
        if isinstance(value, date):
            return value
        return pd.to_datetime(value).date()

    @staticmethod
    def _timestamp(value: pd.Timestamp | datetime | date) -> int:
        ts = pd.Timestamp(value).to_pydatetime()
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        return int(ts.timestamp())
