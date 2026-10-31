import { clearSession, readSession, type Role } from "./session";
import type {
  Application,
  ApplicationSummary,
  AssessBody,
  Assessment,
  DecisionBody,
  DocumentType,
  Interpretation,
  LenderProduct,
  LoanRequest,
  MatchResult,
  OfferEstimate,
  Prequalification,
  Profile,
  QuestionnaireAnswers,
  SampleApplicant,
  SortOrder,
  UploadResult
} from "./types";

// Deployed: the browser calls the API directly (NEXT_PUBLIC_API_URL, e.g. https://creditsetu-api.onrender.com/v1),
// which avoids proxy timeouts on slow photo reads. Locally: /api/v1, proxied by next.config.mjs.
const BASE = process.env.NEXT_PUBLIC_API_URL ?? "/api/v1";

function auth(): Record<string, string> {
  const token = readSession()?.token;
  return token ? { Authorization: `Bearer ${token}` } : {};
}

async function call<T>(path: string, init?: RequestInit): Promise<T> {
  return read<T>(await fetch(BASE + path, { ...init, headers: { "Content-Type": "application/json", ...auth() } }));
}

async function read<T>(response: Response): Promise<T> {
  if (response.status === 401 && readSession()) {
    // The session expired or was signed out elsewhere: back to sign-in.
    clearSession();
    window.location.assign("/register");
  }
  if (response.status === 204) return undefined as T;
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
  // Multipart, so no JSON content type: the browser sets the form boundary.
  login: (body: { role: Role; name: string; organisation: string; mobile: string; otp: string }) =>
    call<{ token: string; account: { id: string; role: Role; name: string; organisation: string; mobile: string } }>(
      "/auth/login",
      post(body)
    ),
  logout: () => call<void>("/auth/logout", { method: "POST" }),
  progress: () => call<Record<string, unknown> | null>("/progress"),
  saveProgress: (state: unknown) => call<void>("/progress", { method: "PUT", body: JSON.stringify(state) }),
  clearDocuments: () => call<void>("/documents", { method: "DELETE" }),
  loadSample: (id: "a" | "b") => call<SampleApplicant>(`/samples/${id}/load`, { method: "POST" }),
  upload: async (file: File, documentType?: DocumentType, password?: string) => {
    const form = new FormData();
    form.append("file", file);
    if (documentType) form.append("document_type", documentType);
    if (password) form.append("password", password);
    return read<UploadResult>(await fetch(BASE + "/documents", { method: "POST", body: form, headers: auth() }));
  },
  sample: (id: "a" | "b") => call<SampleApplicant>(`/samples/${id}`),
  assess: (body: AssessBody) => call<Assessment>("/assess", post(body)),
  match: (profile: Profile, request: LoanRequest, sort: SortOrder) =>
    call<MatchResult[]>(`/match/profile?sort=${sort}`, post({ profile, request })),
  offer: (productId: string, amount: number, tenureMonths: number) =>
    call<OfferEstimate>(`/offers/${encodeURIComponent(productId)}/explain?amount=${amount}&tenure_months=${tenureMonths}`),
  lenders: () => call<LenderProduct[]>("/lenders"),
  prequalify: (answers: QuestionnaireAnswers) => call<Prequalification>("/prequalify", post({ answers })),
  interpret: (step: string, text: string) => call<Interpretation>("/questionnaire/interpret", post({ step, text })),
  apply: (body: AssessBody & { request: LoanRequest; product_id: string; consent_accepted: boolean }) =>
    call<Application>("/applications", post(body)),
  applications: (filter: { lender?: string; sme_id?: string }) =>
    call<ApplicationSummary[]>(`/applications?${new URLSearchParams(filter as Record<string, string>)}`),
  application: (id: string) => call<Application>(`/applications/${encodeURIComponent(id)}`),
  decide: (id: string, body: DecisionBody) => call<Application>(`/applications/${encodeURIComponent(id)}/decision`, post(body))
};

/** End the server session, forget it locally, and leave with a full page load (page guards would race a
 * client-side navigation). The account's saved work stays on the server. */
export async function signOut() {
  try {
    await api.logout();
  } catch {
    /* already signed out or offline: forget it locally anyway */
  }
  clearSession();
  window.location.assign("/");
}
