import { api } from "./client";

export type Signal = "BUY" | "SELL" | "HOLD";

export type Prediction = {
  id: number;
  asset_symbol: string;
  signal: Signal;
  confidence: number;
  target_price: number | null;
  stop_loss: number | null;
  horizon_hours: number;
  created_at: string;
};

export type PredictionStats = {
  total_predictions: number;
  by_signal: { BUY: number; SELL: number; HOLD: number };
  closed_predictions: number;
  win_rate: number | null;
  avg_confidence: number;
};

export async function fetchToday(params?: {
  asset_type?: "stock" | "crypto";
}): Promise<Prediction[]> {
  const { data } = await api.get<Prediction[]>("/predictions/today", {
    params,
  });
  return data;
}

export async function fetchStats(): Promise<PredictionStats> {
  const { data } = await api.get<PredictionStats>("/predictions/stats");
  return data;
}

export async function fetchForSymbol(symbol: string): Promise<Prediction[]> {
  const { data } = await api.get<Prediction[]>(
    `/predictions/${encodeURIComponent(symbol)}`,
  );
  return data;
}
