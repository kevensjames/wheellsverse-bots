import { api } from "./client";
import { setTokens } from "../lib/auth";

export type TokenResponse = {
  access_token: string;
  refresh_token: string;
  token_type: string;
};

export type Me = {
  id: string;
  email: string;
  full_name: string | null;
  phone: string | null;
  is_verified: boolean;
  is_active: boolean;
  created_at: string;
};

export async function signup(input: {
  email: string;
  password: string;
  full_name?: string;
}): Promise<TokenResponse> {
  const { data } = await api.post<TokenResponse>("/auth/signup", input);
  setTokens(data.access_token, data.refresh_token);
  return data;
}

export async function login(input: {
  email: string;
  password: string;
}): Promise<TokenResponse> {
  const { data } = await api.post<TokenResponse>("/auth/login", input);
  setTokens(data.access_token, data.refresh_token);
  return data;
}

export async function me(): Promise<Me> {
  const { data } = await api.get<Me>("/auth/me");
  return data;
}
