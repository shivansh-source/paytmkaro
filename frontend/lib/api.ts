import type {
  Application,
  ApplicationSummary,
  AssessBody,
  Assessment,
  DecisionBody,
  LenderProduct,
  LoanRequest,
  MatchResult,
  OfferEstimate,
  Profile,
  SampleApplicant,
  SortOrder
} from "./types";

const BASE = "/api/v1";

async function call<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(BASE + path, { ...init, headers: { "Content-Type": "application/json" } });
  if (!response.ok) {
    let detail = (await response.text()).slice(0, 300);
    try {
      detail = JSON.parse(detail).detail ?? detail;
    } catch {
      /* not JSON */
    }
    throw new Error(typeof detail === "string" ? detail : `${response.status}`);
  }
  return response.json() as Promise<T>;
}

const post = (body: unknown): RequestInit => ({ method: "POST", body: JSON.stringify(body) });

export const api = {
  sample: (id: "a" | "b") => call<SampleApplicant>(`/samples/${id}`),
  assess: (body: AssessBody) => call<Assessment>("/assess", post(body)),
  match: (profile: Profile, request: LoanRequest, sort: SortOrder) =>
    call<MatchResult[]>(`/match/profile?sort=${sort}`, post({ profile, request })),
  offer: (productId: string, amount: number, tenureMonths: number) =>
    call<OfferEstimate>(`/offers/${encodeURIComponent(productId)}/explain?amount=${amount}&tenure_months=${tenureMonths}`),
  lenders: () => call<LenderProduct[]>("/lenders"),
  apply: (body: AssessBody & { request: LoanRequest; product_id: string; consent_accepted: boolean }) =>
    call<Application>("/applications", post(body)),
  applications: (filter: { lender?: string; sme_id?: string }) =>
    call<ApplicationSummary[]>(`/applications?${new URLSearchParams(filter as Record<string, string>)}`),
  application: (id: string) => call<Application>(`/applications/${encodeURIComponent(id)}`),
  decide: (id: string, body: DecisionBody) => call<Application>(`/applications/${encodeURIComponent(id)}/decision`, post(body))
};
