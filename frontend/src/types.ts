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

export type Result = {
  history: HistoryPoint[];
  forecast: ForecastPoint[];
};
