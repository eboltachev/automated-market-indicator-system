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
};

const initialRows: NewsRow[] = [{ date: '', text: '' }];

function buildPolyline<T>(items: T[], x: (item: T) => number, y: (item: T) => number): string {
  return items.map((item) => `${x(item).toFixed(2)},${y(item).toFixed(2)}`).join(' ');
}

function PriceIndexChart({ asset, history, forecast }: ChartProps) {
  const width = 1200;
  const height = 540;
  const padding = { top: 48, right: 88, bottom: 64, left: 72 };
  const plotWidth = width - padding.left - padding.right;
  const plotHeight = height - padding.top - padding.bottom;

  const hist = [...history].sort((a, b) => a.date - b.date);
  const fc = [...forecast].sort((a, b) => a.date - b.date);
  const lastHistoryDate = hist.at(-1)?.date ?? 0;
  const forecastHistory = fc.filter((point) => point.date <= lastHistoryDate);
  const forecastFuture = fc.filter((point) => point.date > lastHistoryDate);
  const timeline = [...hist, ...forecastFuture];

  if (!hist.length || !fc.length || !timeline.length) {
    return <div className="empty-chart">Нет данных для построения графика</div>;
  }

  const xMin = Math.min(...timeline.map((point) => point.date));
  const xMax = Math.max(...timeline.map((point) => point.date));
  const priceValues = [...hist.map((point) => point.price), ...forecastFuture.map((point) => point.price)];
  const rawPriceMin = Math.min(...priceValues);
  const rawPriceMax = Math.max(...priceValues);
  const pricePadding = Math.max((rawPriceMax - rawPriceMin) * 0.08, rawPriceMax * 0.01, 1);
  const priceMin = rawPriceMin - pricePadding;
  const priceMax = rawPriceMax + pricePadding;

  const xScale = (timestamp: number) =>
    padding.left + ((timestamp - xMin) / Math.max(xMax - xMin, 1)) * plotWidth;
  const indexScale = (value: number) => padding.top + (1 - value / 100) * plotHeight;
  const priceScale = (value: number) =>
    padding.top + (1 - (value - priceMin) / Math.max(priceMax - priceMin, 1)) * plotHeight;

  const historyPriceLine = buildPolyline(hist, (point) => xScale(point.date), (point) => priceScale(point.price));
  const futurePriceLine = buildPolyline(
    hist.at(-1) ? [hist.at(-1)!, ...forecastFuture] : forecastFuture,
    (point) => xScale(point.date),
    (point) => priceScale(point.price),
  );
  const indexHistoryLine = buildPolyline(
    forecastHistory,
    (point) => xScale(point.date),
    (point) => indexScale(point.index),
  );
  const indexFutureLine = buildPolyline(
    forecastHistory.at(-1) ? [forecastHistory.at(-1)!, ...forecastFuture] : forecastFuture,
    (point) => xScale(point.date),
    (point) => indexScale(point.index),
  );

  const firstDate = new Date(xMin * 1000).toLocaleDateString();
  const lastDate = new Date(xMax * 1000).toLocaleDateString();

  return (
    <div className="chart-card">
      <svg viewBox={`0 0 ${width} ${height}`} role="img" aria-label={`Индекс и прогноз цены ${asset}`}>
        <text x={padding.left} y={30} className="chart-title">
          Индекс и прогноз цены {asset}
        </text>

        <line x1={padding.left} y1={padding.top} x2={padding.left} y2={height - padding.bottom} className="axis" />
        <line
          x1={padding.left}
          y1={height - padding.bottom}
          x2={width - padding.right}
          y2={height - padding.bottom}
          className="axis"
        />
        <line
          x1={width - padding.right}
          y1={padding.top}
          x2={width - padding.right}
          y2={height - padding.bottom}
          className="axis muted"
        />

        {[0, 25, 50, 75, 100].map((tick) => (
          <g key={tick}>
            <line
              x1={padding.left}
              y1={indexScale(tick)}
              x2={width - padding.right}
              y2={indexScale(tick)}
              className="grid"
            />
            <text x={padding.left - 12} y={indexScale(tick) + 4} textAnchor="end" className="tick">
              {tick}
            </text>
          </g>
        ))}

        {[priceMin, (priceMin + priceMax) / 2, priceMax].map((tick) => (
          <text key={tick} x={width - padding.right + 12} y={priceScale(tick) + 4} className="tick">
            {tick.toFixed(2)}
          </text>
        ))}

        <text x={padding.left} y={height - 24} className="tick">
          {firstDate}
        </text>
        <text x={width - padding.right} y={height - 24} textAnchor="end" className="tick">
          {lastDate}
        </text>

        {historyPriceLine && <polyline points={historyPriceLine} className="line price-history" />}
        {futurePriceLine && <polyline points={futurePriceLine} className="line price-forecast" />}
        {indexHistoryLine && <polyline points={indexHistoryLine} className="line index-history" />}
        {indexFutureLine && <polyline points={indexFutureLine} className="line index-forecast" />}

        <g transform={`translate(${padding.left}, ${height - 48})`} className="legend">
          <rect x="0" y="-10" width="20" height="3" className="legend-line price-history" />
          <text x="28" y="-6">Цена: история</text>
          <rect x="170" y="-10" width="20" height="3" className="legend-line price-forecast" />
          <text x="198" y="-6">Цена: прогноз</text>
          <rect x="350" y="-10" width="20" height="3" className="legend-line index-history" />
          <text x="378" y="-6">Индекс: история</text>
          <rect x="550" y="-10" width="20" height="3" className="legend-line index-forecast" />
          <text x="578" y="-6">Индекс: прогноз</text>
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
        <PriceIndexChart asset={asset} history={data.history} forecast={data.forecast} />
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
