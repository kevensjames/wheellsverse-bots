import { api } from "./client";

export type PlanCode = "pro" | "elite";

export type Subscription = {
  plan_code: string;
  plan_name: string;
  status: string;
  predictions_per_day: number;
  current_period_end: string | null;
  cancel_url: string | null;
};

export async function fetchSubscription(): Promise<Subscription> {
  const { data } = await api.get<Subscription>("/billing/subscription");
  return data;
}

export async function startCheckout(plan: PlanCode): Promise<string> {
  const { data } = await api.post<{ checkout_url: string; plan_code: PlanCode }>(
    "/billing/checkout",
    { plan_code: plan },
  );
  return data.checkout_url;
}

export async function openPortal(): Promise<string> {
  const { data } = await api.post<{ portal_url: string }>("/billing/portal");
  return data.portal_url;
}
