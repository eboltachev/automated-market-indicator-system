import { Suspense, lazy, useMemo, useState } from 'react';
import { predict, predictFile, updateData } from './api';
import type { Result } from './types';

const Plot = lazy(() =>
  import('react-plotly.js')
    .then((module) => ({ default: module.default }))
    .catch(() => ({
      default: () => (
        <div className='plot-fallback'>
          Не удалось загрузить модуль графика. Проверьте зависимости фронтенда.
        </div>
      ),
    })),
);

export default function App() {
  const [asset, setAsset] = useState(import.meta.env.VITE_DEFAULT_ASSET || 'LKOH');
  const [period, setPeriod] = useState(Number(import.meta.env.VITE_DEFAULT_PERIOD || 7));
  const [data, setData] = useState<Result | null>(null);
  const [rows, setRows] = useState([{ date: '', text: '' }]);
  const [manual, setManual] = useState(false);
  const [fileModal, setFileModal] = useState(false);
  const [file, setFile] = useState<File | null>(null);
  const [status, setStatus] = useState('');
  const [loading, setLoading] = useState(false);
  const [updating, setUpdating] = useState(false);

  const traces = useMemo(() => {
    if (!data) return [];
    const hist = [...data.history].sort((a, b) => a.date - b.date);
    const fc = [...data.forecast].sort((a, b) => a.date - b.date);
    const last = hist.at(-1)?.date || 0;
    const fh = fc.filter((x) => x.date <= last);
    const ff = fc.filter((x) => x.date > last);
    const d = (x: number) => new Date(x * 1000);

    return [
      { x: fh.map((x) => d(x.date)), y: fh.map((x) => x.index), name: 'Индекс: история', mode: 'lines+markers', line: { color: 'blue', dash: 'dash' } },
      { x: ff.map((x) => d(x.date)), y: ff.map((x) => x.index), name: 'Индекс: прогноз', mode: 'lines+markers', line: { color: 'red', dash: 'dash' } },
      { x: hist.map((x) => d(x.date)), y: hist.map((x) => x.price), name: 'Цена: история', mode: 'lines+markers', yaxis: 'y2', line: { color: 'blue' } },
      { x: ff.map((x) => d(x.date)), y: ff.map((x) => x.price), name: 'Цена: прогноз', mode: 'lines+markers', yaxis: 'y2', line: { color: 'red' } },
    ];
  }, [data]);

  return (
    <div>
      <div className='top'>
        <input value={asset} onChange={(e) => setAsset(e.target.value)} />
        <input type='number' value={period} onChange={(e) => setPeriod(Number(e.target.value))} />
        <button onClick={() => setFileModal(true)}>Загрузить файл</button>
        <button onClick={() => setManual(true)}>Ввести данные</button>
        <button
          disabled={updating}
          onClick={async () => {
            setUpdating(true);
            setStatus('');
            try {
              await updateData();
              setStatus('Данные обновлены');
            } catch {
              setStatus('Произошла ошибка. Попробуйте позже.');
            } finally {
              setUpdating(false);
            }
          }}
        >
          {updating ? 'Выполняется обновление' : 'Получить обновления'}
        </button>
        <span>{status}</span>
      </div>

      {data && (
        <Suspense fallback={<div className='plot-fallback'>Загрузка графика…</div>}>
          <Plot
            data={traces as never[]}
            layout={{
              title: `Индекс и прогноз цены ${asset}`,
              yaxis: { range: [0, 100], title: 'Индекс' },
              yaxis2: { overlaying: 'y', side: 'right', title: 'Абсолютное значение цены' },
              autosize: true,
            }}
            style={{ width: '100%', height: '80vh' }}
          />
        </Suspense>
      )}

      {fileModal && (
        <div className='modal'>
          <input type='file' accept='.xls,.xlsx' onChange={(e) => setFile(e.target.files?.[0] || null)} />
          <button
            disabled={!file || loading}
            onClick={async () => {
              if (!file) return;
              setLoading(true);
              const f = new FormData();
              f.append('file', file);
              f.append('asset', asset);
              f.append('period', String(period));
              try {
                setData(await predictFile(f));
                setFileModal(false);
              } finally {
                setLoading(false);
              }
            }}
          >
            Ок
          </button>
          <button onClick={() => setFileModal(false)}>Отмена</button>
        </div>
      )}

      {manual && (
        <div className='modal'>
          {rows.map((r, i) => (
            <div key={i}>
              <input
                type='date'
                value={r.date}
                onChange={(e) => {
                  const n = [...rows];
                  n[i].date = e.target.value;
                  setRows(n);
                }}
              />
              <textarea
                value={r.text}
                onChange={(e) => {
                  const n = [...rows];
                  n[i].text = e.target.value;
                  setRows(n);
                }}
              />
            </div>
          ))}
          <button onClick={() => setRows([...rows, { date: '', text: '' }])}>+</button>
          <button
            onClick={async () => {
              const news = rows.filter((r) => r.date && r.text.trim());
              if (!news.length) {
                setStatus('Нет валидных новостей');
                return;
              }
              setData(await predict({ asset, period, news }));
              setManual(false);
            }}
          >
            Ок
          </button>
          <button onClick={() => setManual(false)}>Отмена</button>
        </div>
      )}
    </div>
  );
}
