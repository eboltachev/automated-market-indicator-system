from __future__ import annotations

from io import BytesIO

import pandas as pd


def parse_news_excel(file_bytes: bytes) -> list[dict[str, str]]:
    df = pd.read_excel(BytesIO(file_bytes))
    if "date" in df.columns and "text" in df.columns:
        date_col, text_col = "date", "text"
    elif "Unnamed: 0" in df.columns and "Unnamed: 1" in df.columns:
        date_col, text_col = "Unnamed: 0", "Unnamed: 1"
    else:
        raise ValueError("Excel должен содержать колонки date/text или Unnamed: 0/Unnamed: 1")
    rows: list[dict[str, str]] = []
    for _, row in df.iterrows():
        text = str(row[text_col]).strip() if not pd.isna(row[text_col]) else ""
        if not text:
            continue
        dt = pd.to_datetime(row[date_col]).date().isoformat()
        rows.append({"date": dt, "text": text})
    return rows
