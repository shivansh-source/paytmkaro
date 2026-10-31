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

const BASE = "/api/v1";

async function call<T>(path: string, init?: RequestInit): Promise<T> {
  return read<T>(await fetch(BASE + path, { ...init, headers: { "Content-Type": "application/json" } }));
}

async function read<T>(response: Response): Promise<T> {
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
  upload: async (file: File, smeId: string, documentType?: DocumentType, password?: string) => {
    const form = new FormData();
    form.append("file", file);
    form.append("sme_id", smeId);
    if (documentType) form.append("document_type", documentType);
    if (password) form.append("password", password);
    return read<UploadResult>(await fetch(BASE + "/documents", { method: "POST", body: form }));
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
