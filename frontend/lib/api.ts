import type { AssessBody, Assessment, LoanRequest, MatchResult, OfferEstimate, Profile, SampleApplicant, SortOrder } from "./types";

const BASE = "/api/v1";

async function call<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(BASE + path, { ...init, headers: { "Content-Type": "application/json" } });
  if (!response.ok) {
    throw new Error(`${response.status}: ${(await response.text()).slice(0, 300)}`);
  }
  return response.json() as Promise<T>;
}

export const api = {
  sample: (id: "a" | "b") => call<SampleApplicant>(`/samples/${id}`),
  assess: (body: AssessBody) => call<Assessment>("/assess", { method: "POST", body: JSON.stringify(body) }),
  match: (profile: Profile, request: LoanRequest, sort: SortOrder) =>
    call<MatchResult[]>(`/match/profile?sort=${sort}`, { method: "POST", body: JSON.stringify({ profile, request }) }),
  offer: (productId: string, amount: number, tenureMonths: number) =>
    call<OfferEstimate>(`/offers/${encodeURIComponent(productId)}/explain?amount=${amount}&tenure_months=${tenureMonths}`)
};
