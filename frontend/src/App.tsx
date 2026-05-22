import React, { useMemo, useState } from 'react';
import { predict, predictFile, updateData } from './api';
import type { ForecastPoint, HistoryPoint, Result } from './types';

type NewsRow = {
  date: string;
  text: string;
};

type ChartProps = {
  asset: string;
  history: HistoryPoint[];
  forecast: ForecastPoint[];
  meta?: Result['meta'];
};

const initialRows: NewsRow[] = [{ date: '', text: '' }];

function buildPolyline<T>(items: T[], x: (item: T) => number, y: (item: T) => number): string {
  return items.map((item) => `${x(item).toFixed(2)},${y(item).toFixed(2)}`).join(' ');
}

function buildLinearTicks(min: number, max: number, count: number): number[] {
  if (!Number.isFinite(min) || !Number.isFinite(max) || count <= 1) return [];
  if (min === max) return [min];
  return Array.from({ length: count }, (_, index) => min + ((max - min) * index) / (count - 1));
}

function buildDateTicks(min: number, max: number, count: number): number[] {
  return Array.from(new Set(buildLinearTicks(min, max, count).map((tick) => Math.round(tick))));
}

function PriceIndexChart({ asset, history, forecast, meta }: ChartProps) {
  const width = 1280;
  const height = 640;
  const padding = { top: 78, right: 118, bottom: 118, left: 96 };
  const plotWidth = width - padding.left - padding.right;
  const plotHeight = height - padding.top - padding.bottom;
  const dateFormatter = new Intl.DateTimeFormat('ru-RU', { day: '2-digit', month: '2-digit', year: '2-digit' });
  const fullDateFormatter = new Intl.DateTimeFormat('ru-RU', { day: '2-digit', month: '2-digit', year: 'numeric' });
  const priceFormatter = new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 2 });

  const hist = [...history].sort((a, b) => a.date - b.date);
  const fc = [...forecast].sort((a, b) => a.date - b.date);

  if (!hist.length || !fc.length) {
    return <div className="empty-chart">Нет данных для построения графика</div>;
  }

  const fallbackForecastStartDate = hist.at(-1)?.date ?? fc.at(-1)?.date ?? 0;
  const forecastStartDate = meta?.forecast_start_date ?? fallbackForecastStartDate;
  const forecastHistory = fc.filter((point) => point.date <= forecastStartDate);
  const forecastFuture = fc.filter((point) => point.date > forecastStartDate);
  const forecastAnchor =
    [...forecastHistory].reverse().find((point) => point.date <= forecastStartDate) ??
    [...fc].reverse().find((point) => point.date <= forecastStartDate) ??
    hist.find((point) => point.date >= forecastStartDate) ??
    hist.at(-1);
  const forecastPricePoints = forecastAnchor ? [forecastAnchor, ...forecastFuture] : forecastFuture;
  const indexFuturePoints = forecastAnchor ? [forecastAnchor, ...forecastFuture] : forecastFuture;
  const timeline = [...hist, ...forecastPricePoints];

  if (!timeline.length) {
    return <div className="empty-chart">Нет данных для построения графика</div>;
  }

  const xMin = Math.min(...timeline.map((point) => point.date));
  const xMax = Math.max(...timeline.map((point) => point.date));
  const priceValues = [...hist.map((point) => point.price), ...forecastPricePoints.map((point) => point.price)];
  const rawPriceMin = Math.min(...priceValues);
  const rawPriceMax = Math.max(...priceValues);
  const pricePadding = Math.max((rawPriceMax - rawPriceMin) * 0.1, rawPriceMax * 0.01, 1);
  const priceMin = rawPriceMin - pricePadding;
  const priceMax = rawPriceMax + pricePadding;
  const priceTicks = buildLinearTicks(priceMin, priceMax, 5);
  const dateTicks = buildDateTicks(xMin, xMax, 7);

  const xScale = (timestamp: number) =>
    padding.left + ((timestamp - xMin) / Math.max(xMax - xMin, 1)) * plotWidth;
  const indexScale = (value: number) => padding.top + (1 - value / 100) * plotHeight;
  const priceScale = (value: number) =>
    padding.top + (1 - (value - priceMin) / Math.max(priceMax - priceMin, 1)) * plotHeight;

  const historyPriceLine = buildPolyline(hist, (point) => xScale(point.date), (point) => priceScale(point.price));
  const futurePriceLine = buildPolyline(
    forecastPricePoints,
    (point) => xScale(point.date),
    (point) => priceScale(point.price),
  );
  const indexHistoryLine = buildPolyline(
    forecastHistory,
    (point) => xScale(point.date),
    (point) => indexScale(point.index),
  );
  const indexFutureLine = buildPolyline(
    indexFuturePoints,
    (point) => xScale(point.date),
    (point) => indexScale(point.index),
  );

  const plotTop = padding.top;
  const plotBottom = height - padding.bottom;
  const plotLeft = padding.left;
  const plotRight = width - padding.right;
  const forecastStartX = xScale(forecastStartDate);
  const actualHistoryEndDate = meta?.actual_history_end_date ?? hist.at(-1)?.date ?? forecastStartDate;
  const forecastEndDate = meta?.forecast_end_date ?? forecastFuture.at(-1)?.date ?? xMax;
  const historyEndLabel = fullDateFormatter.format(new Date(actualHistoryEndDate * 1000));
  const forecastStartLabel = fullDateFormatter.format(new Date(forecastStartDate * 1000));
  const forecastEndLabel = fullDateFormatter.format(new Date(forecastEndDate * 1000));

  return (
    <div className="chart-card">
      <svg viewBox={`0 0 ${width} ${height}`} role="img" aria-label={`Индекс и прогноз цены ${asset}`}>
        <text x={padding.left} y={32} className="chart-title">
          Индекс и прогноз цены {asset}
        </text>
        <text x={padding.left} y={56} className="chart-subtitle">
          История до {historyEndLabel}; прогноз с {forecastStartLabel} на {forecastFuture.length} дн. до {forecastEndLabel}
        </text>

        {forecastFuture.length > 0 && (
          <rect
            x={forecastStartX}
            y={plotTop}
            width={Math.max(plotRight - forecastStartX, 0)}
            height={plotHeight}
            className="forecast-zone"
          />
        )}

        <line x1={plotLeft} y1={plotTop} x2={plotLeft} y2={plotBottom} className="axis" />
        <line x1={plotLeft} y1={plotBottom} x2={plotRight} y2={plotBottom} className="axis" />
        <line x1={plotRight} y1={plotTop} x2={plotRight} y2={plotBottom} className="axis muted" />

        {[0, 25, 50, 75, 100].map((tick) => (
          <g key={tick}>
            <line x1={plotLeft} y1={indexScale(tick)} x2={plotRight} y2={indexScale(tick)} className="grid" />
            <text x={plotLeft - 12} y={indexScale(tick) + 4} textAnchor="end" className="tick">
              {tick}
            </text>
          </g>
        ))}

        {priceTicks.map((tick) => (
          <text key={tick} x={plotRight + 12} y={priceScale(tick) + 4} className="tick">
            {priceFormatter.format(tick)}
          </text>
        ))}

        {dateTicks.map((tick) => (
          <g key={tick}>
            <line x1={xScale(tick)} y1={plotBottom} x2={xScale(tick)} y2={plotBottom + 6} className="axis" />
            <text x={xScale(tick)} y={plotBottom + 26} textAnchor="middle" className="tick tick-date">
              {dateFormatter.format(new Date(tick * 1000))}
            </text>
          </g>
        ))}

        {forecastFuture.length > 0 && (
          <g>
            <line x1={forecastStartX} y1={plotTop} x2={forecastStartX} y2={plotBottom} className="forecast-divider" />
            <text x={forecastStartX + 8} y={plotTop + 18} className="forecast-label">
              начало прогноза
            </text>
          </g>
        )}

        {historyPriceLine && <polyline points={historyPriceLine} className="line price-history" />}
        {futurePriceLine && <polyline points={futurePriceLine} className="line price-forecast" />}
        {indexHistoryLine && <polyline points={indexHistoryLine} className="line index-history" />}
        {indexFutureLine && <polyline points={indexFutureLine} className="line index-forecast" />}

        <text x={plotLeft + plotWidth / 2} y={height - 44} textAnchor="middle" className="axis-label">
          Дата
        </text>
        <text
          x={24}
          y={plotTop + plotHeight / 2}
          textAnchor="middle"
          className="axis-label"
          transform={`rotate(-90 24 ${plotTop + plotHeight / 2})`}
        >
          Индекс новостей, 0–100
        </text>
        <text
          x={width - 28}
          y={plotTop + plotHeight / 2}
          textAnchor="middle"
          className="axis-label"
          transform={`rotate(90 ${width - 28} ${plotTop + plotHeight / 2})`}
        >
          Цена
        </text>

        <g transform={`translate(${padding.left}, ${height - 18})`} className="legend">
          <rect x="0" y="-10" width="22" height="3" className="legend-line price-history" />
          <text x="30" y="-6">Цена: история</text>
          <rect x="185" y="-10" width="22" height="3" className="legend-line price-forecast" />
          <text x="215" y="-6">Цена: прогноз</text>
          <rect x="390" y="-10" width="22" height="3" className="legend-line index-history" />
          <text x="420" y="-6">Индекс: история</text>
          <rect x="610" y="-10" width="22" height="3" className="legend-line index-forecast" />
          <text x="640" y="-6">Индекс: прогноз</text>
        </g>
      </svg>
    </div>
  );
}

export default function App() {
  const [asset, setAsset] = useState(import.meta.env.VITE_DEFAULT_ASSET || 'LKOH');
  const [period, setPeriod] = useState(Number(import.meta.env.VITE_DEFAULT_PERIOD || 7));
  const [data, setData] = useState<Result | null>(null);
  const [rows, setRows] = useState<NewsRow[]>(initialRows);
  const [manual, setManual] = useState(false);
  const [fileModal, setFileModal] = useState(false);
  const [file, setFile] = useState<File | null>(null);
  const [status, setStatus] = useState('');
  const [loading, setLoading] = useState(false);
  const [updating, setUpdating] = useState(false);

  const canPredict = useMemo(() => asset.trim().length > 0 && period > 0, [asset, period]);

  const setRow = (index: number, patch: Partial<NewsRow>) => {
    const nextRows = [...rows];
    nextRows[index] = { ...nextRows[index], ...patch };
    setRows(nextRows);
  };

  const showError = (error: unknown) => {
    setStatus(error instanceof Error ? error.message : 'Произошла ошибка. Попробуйте позже.');
  };

  const runManualPrediction = async () => {
    const news = rows.filter((row) => row.date && row.text.trim());
    if (!news.length) {
      setStatus('Нет валидных новостей');
      return;
    }

    setLoading(true);
    setStatus('');
    try {
      setData(await predict({ asset, period, news }));
      setManual(false);
    } catch (error) {
      showError(error);
    } finally {
      setLoading(false);
    }
  };

  const runFilePrediction = async () => {
    if (!file) return;
    setLoading(true);
    setStatus('');
    const form = new FormData();
    form.append('file', file);
    form.append('asset', asset);
    form.append('period', String(period));

    try {
      setData(await predictFile(form));
      setFileModal(false);
    } catch (error) {
      showError(error);
    } finally {
      setLoading(false);
    }
  };

  const runUpdate = async () => {
    setUpdating(true);
    setStatus('');
    try {
      await updateData();
      setStatus('Данные обновлены');
    } catch (error) {
      showError(error);
    } finally {
      setUpdating(false);
    }
  };

  return (
    <div className="page">
      <div className="top">
        <input value={asset} onChange={(event) => setAsset(event.target.value)} placeholder="Тикер" />
        <input
          type="number"
          min={1}
          value={period}
          onChange={(event) => setPeriod(Number(event.target.value))}
          placeholder="Период"
        />
        <button disabled={!canPredict} onClick={() => setFileModal(true)}>Загрузить файл</button>
        <button disabled={!canPredict} onClick={() => setManual(true)}>Ввести данные</button>
        <button disabled={updating} onClick={runUpdate}>
          {updating ? 'Выполняется обновление' : 'Получить обновления'}
        </button>
        {status && <span className="status">{status}</span>}
      </div>

      {data ? (
        <PriceIndexChart asset={asset} history={data.history} forecast={data.forecast} meta={data.meta} />
      ) : (
        <div className="placeholder">Загрузите Excel-файл или введите новости вручную, чтобы построить график.</div>
      )}

      {fileModal && (
        <div className="modal-backdrop">
          <div className="modal">
            <h2>Загрузка новостей из Excel</h2>
            <input type="file" accept=".xls,.xlsx" onChange={(event) => setFile(event.target.files?.[0] || null)} />
            <div className="modal-actions">
              <button disabled={!file || loading} onClick={runFilePrediction}>Ок</button>
              <button onClick={() => setFileModal(false)}>Отмена</button>
            </div>
          </div>
        </div>
      )}

      {manual && (
        <div className="modal-backdrop">
          <div className="modal wide">
            <h2>Ввод новостей</h2>
            {rows.map((row, index) => (
              <div className="news-row" key={index}>
                <input type="date" value={row.date} onChange={(event) => setRow(index, { date: event.target.value })} />
                <textarea value={row.text} onChange={(event) => setRow(index, { text: event.target.value })} />
              </div>
            ))}
            <button onClick={() => setRows([...rows, { date: '', text: '' }])}>+</button>
            <div className="modal-actions">
              <button disabled={loading} onClick={runManualPrediction}>Ок</button>
              <button onClick={() => setManual(false)}>Отмена</button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
