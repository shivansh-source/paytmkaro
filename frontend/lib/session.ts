// Session: mock OTP (123456), but a real server session. The token from POST /v1/auth/login goes with every
// API call; the account and its documents live on the server, so they work on any device.

export type Role = "msme" | "lender";

export interface Session {
  role: Role;
  name: string;
  organisation: string;
  mobile: string;
  signedInAt: string;
  token: string; // bearer token for the API
  accountId: string; // SME-<mobile> / LENDER-<mobile>; an MSME's id is its sme_id
}

const KEY = "creditsetu.session";

export function readSession(): Session | null {
  if (typeof window === "undefined") return null;
  try {
    const session = JSON.parse(window.localStorage.getItem(KEY) ?? "null");
    return session?.token ? session : null; // sessions saved before server login count as signed out
  } catch {
    return null;
  }
}

export function writeSession(session: Session) {
  window.localStorage.setItem(KEY, JSON.stringify(session));
}

export function clearSession() {
  window.localStorage.removeItem(KEY);
}

export const DEMO_OTP = "123456";
export const homeFor = (role: Role) => (role === "msme" ? "/msme/start" : "/lender");
