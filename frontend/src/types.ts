export type HistoryPoint = {
  date: number;
  price: number;
};

export type ForecastPoint = {
  date: number;
  price: number;
  index: number;
  increase: number;
  stable: number;
  fall: number;
};

export type ResultMeta = {
  forecast_start_date?: number;
  forecast_end_date?: number;
  actual_history_end_date?: number;
};

export type Result = {
  history: HistoryPoint[];
  forecast: ForecastPoint[];
  meta?: ResultMeta;
};

export type AssetsResponse = {
  assets: string[];
};
