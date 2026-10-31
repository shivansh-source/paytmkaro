// Demo session: mobile + mock OTP, stored in localStorage. No real authentication for the hackathon.

export type Role = "msme" | "lender";

export interface Session {
  role: Role;
  name: string;
  organisation: string;
  mobile: string;
  signedInAt: string;
}

const KEY = "creditsetu.session";

export function readSession(): Session | null {
  if (typeof window === "undefined") return null;
  try {
    return JSON.parse(window.localStorage.getItem(KEY) ?? "null");
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
