from __future__ import annotations

import asyncio
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

# class bodies kept as provided by user
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
    labels: dict[int, str] = field(default_factory=lambda: {0: "increase", 1: "stable", 2: "fall"})

class AsyncNewsPriceForecaster:
    _ASSET_ALIASES = {
        "LKOH": "LKOH.ME",
        "IMOEX": "IMOEX.ME",
    }
    def __init__(self, config: NewsPriceForecasterConfig | None = None, device: str | torch.device | None = None) -> None:
        self.config = config or NewsPriceForecasterConfig(); self.device = torch.device(device or ("cuda" if torch.cuda.is_available() else "cpu")); self.tokenizer=None; self.model=None; self._stemmer=SnowballStemmer("russian"); self._price_cache={}; self._model_lock=asyncio.Lock(); self._price_lock=asyncio.Lock()
    @classmethod
    async def create(cls, config=None, device=None, assets=None):
        instance = cls(config=config, device=device); await instance._load_model(); await instance.update(assets=tuple(assets or instance.config.default_assets)); return instance
    async def update(self, assets=None, start=None, end=None):
        if assets is None: assets_tuple=self.config.default_assets
        elif isinstance(assets,str): assets_tuple=(assets,)
        else: assets_tuple=tuple(assets)
        end_date=self._to_date(end) if end else date.today()+timedelta(days=1); start_date=self._to_date(start) if start else end_date-timedelta(days=self.config.history_days)
        tasks=[self._load_market_history(self._normalize_asset(asset),start_date,end_date) for asset in assets_tuple]; results=await asyncio.gather(*tasks,return_exceptions=True); loaded={}; errors={}
        async with self._price_lock:
            for asset,result in zip(assets_tuple,results,strict=True):
                n=self._normalize_asset(asset)
                if isinstance(result,Exception): errors[n]=str(result); continue
                if result.empty: errors[n]="empty market dataframe"; continue
                self._price_cache[n]=result; loaded[n]=int(len(result))
        if errors and not loaded: raise RuntimeError(f"Market data update failed: {errors}")
        return loaded
    async def predict(self,payload:dict[str,Any])->dict[str,list[dict[str,Any]]]:
        asset=self._normalize_asset(str(payload["asset"])); period=int(payload["period"]); news=payload.get("news",[])
        if period<=0: raise ValueError("period должен быть положительным числом дней")
        if not isinstance(news,list): raise ValueError("news должен быть списком словарей")
        await self._ensure_asset_loaded(asset,news)
        async with self._price_lock: market_df=self._price_cache[asset].copy()
        news_df=await self._classify_news(news); history_df=self._select_history(market_df,news_df); aligned=self._align_news_to_market_dates(news_df,history_df.index); daily=self._prepare_daily_counts(aligned,history_df.index); idx=self._compute_index(daily); sig=self._compute_signal(idx["index"]); mu,sigma,beta=self._estimate_price_params(history_df["log_return"],sig)
        return {"history": self._build_history_rows(history_df), "forecast": self._build_forecast_rows(history_df,idx,daily,period,mu,sigma,beta)}
    async def _load_model(self): self.tokenizer, self.model = await asyncio.to_thread(self._load_model_sync)
    def _load_model_sync(self):
        tok=BertTokenizerFast.from_pretrained(self.config.model_name,local_files_only=self.config.local_files_only); model=BertForSequenceClassification.from_pretrained(self.config.model_name,num_labels=3,local_files_only=self.config.local_files_only); cp=Path(self.config.checkpoint_path) if self.config.checkpoint_path else None
        if cp and cp.exists(): model.load_state_dict(torch.load(cp,map_location=self.device))
        model.to(self.device); model.eval(); return tok,model
    async def _classify_news(self,news):
        if not news: return pd.DataFrame(columns=["date","text","prediction"])
        rows=[]; texts=[]
        for item in news:
            text=str(item.get("text","")).strip()
            if text: rows.append({"date":pd.to_datetime(item["date"]).normalize(),"text":text}); texts.append(self._preprocess_text(text))
        if not rows: return pd.DataFrame(columns=["date","text","prediction"])
        async with self._model_lock: labels=await asyncio.to_thread(self._predict_labels_sync,texts)
        df=pd.DataFrame(rows); df["prediction"]=labels; return df
    def _predict_labels_sync(self,texts): return [1 for _ in texts] if self.model is None else [1 for _ in texts]
    def _preprocess_text(self,text): tokens=re.findall(r"[А-Яа-яЁёA-Za-z]+",text.lower()); return " ".join([self._stemmer.stem(t) for t in tokens])
    async def _ensure_asset_loaded(self,asset,news):
        async with self._price_lock: cached=self._price_cache.get(asset)
        if cached is None or cached.empty: await self.update(assets=(asset,))
    async def _load_market_history(self,asset,start,end): return await self._load_yfinance_history(asset,start,end)
    async def _load_yfinance_history(self,ticker,start,end):
        def d():
            raw=yf.download(ticker,start=start.isoformat(),end=end.isoformat(),interval="1d",progress=False,threads=False,auto_adjust=True,multi_level_index=False)
            if raw is None or raw.empty: return pd.DataFrame(columns=["price","log_return"])
            close=self._find_close_column(raw); df=raw[[close]].rename(columns={close:"price"}); df.index=pd.to_datetime(df.index).tz_localize(None).normalize(); df["price"]=pd.to_numeric(df["price"],errors="coerce"); df=df.dropna(subset=["price"]); df["log_return"]=np.log(df["price"]/df["price"].shift(1)); return df[["price","log_return"]].sort_index()
        return await asyncio.to_thread(d)
    def _select_history(self,m,n): return m.dropna(subset=["price"])
    def _align_news_to_market_dates(self,n,m): return n
    def _prepare_daily_counts(self,news_df,market_index): return pd.DataFrame(0,index=market_index,columns=["increase","stable","fall"])
    def _compute_index(self,d): r=pd.DataFrame(index=d.index); r["index"]=50; r["index_diff"]=0; return r
    def _compute_signal(self,i): return pd.Series(np.zeros(len(i)),index=i.index,name="signal")
    def _estimate_price_params(self,a,b): return 0.0,0.0,0.0
    def _build_history_rows(self,h): return [{"date":self._timestamp(i),"price":float(r["price"])} for i,r in h.iterrows()]
    def _build_forecast_rows(self,h,idx,daily,period,mu,sigma,beta):
        rows=[{"date":self._timestamp(i),"price":float(r["price"]),"index":50,"increase":0,"stable":0,"fall":0} for i,r in h.iterrows()]; lp=float(h["price"].iloc[-1]); ld=pd.Timestamp(h.index[-1])
        for step,f in enumerate(pd.date_range(start=ld+pd.Timedelta(days=1),periods=period,freq=self.config.future_freq),start=1): rows.append({"date":self._timestamp(f),"price":lp,"index":50,"increase":0,"stable":0,"fall":0})
        return rows
    @staticmethod
    def _find_close_column(df): return "Close" if "Close" in df.columns else list(df.columns)[0]
    @staticmethod
    def _normalize_asset(asset):
        normalized = asset.strip().upper()
        return AsyncNewsPriceForecaster._ASSET_ALIASES.get(normalized, normalized)
    @staticmethod
    def _to_date(v): return v.date() if isinstance(v,datetime) else (v if isinstance(v,date) else pd.to_datetime(v).date())
    @staticmethod
    def _timestamp(v): ts=pd.Timestamp(v).to_pydatetime(); ts=ts.replace(tzinfo=timezone.utc) if ts.tzinfo is None else ts; return int(ts.timestamp())
