/** The browser half of the console HTTP API, docs/04 §4. */

import type { RxLine, SessionCreated, SessionState } from "./types";

export const CONSOLE_URL =
  process.env.NEXT_PUBLIC_CONSOLE_URL ?? "http://127.0.0.1:8808";

export class ConsoleApiError extends Error {
  constructor(
    readonly status: number,
    readonly body: string,
  ) {
    super(`console ${status}: ${body}`);
    this.name = "ConsoleApiError";
  }
}

async function req<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${CONSOLE_URL}${path}`, {
    ...init,
    headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) },
  });
  if (!res.ok) throw new ConsoleApiError(res.status, await res.text().catch(() => ""));
  if (res.status === 204) return undefined as T;
  const text = await res.text();
  return (text ? JSON.parse(text) : undefined) as T;
}

export const api = {
  createSession: () =>
    req<SessionCreated>("/api/sessions", { method: "POST", body: "{}" }),

  getSession: (id: string) => req<SessionState>(`/api/sessions/${id}`),

  setLanguage: (id: string, side: "patient" | "doctor", lang: string) =>
    req<unknown>(`/api/sessions/${id}/language`, {
      method: "POST",
      body: JSON.stringify({ side, lang }),
    }),

  setConsent: (id: string, given: boolean) =>
    req<unknown>(`/api/sessions/${id}/consent`, {
      method: "POST",
      body: JSON.stringify({ given }),
    }),

  /** PATCH one line. Clears `confirmed` server-side, per docs/04 §4. */
  patchRxLine: (id: string, lineId: string, patch: Partial<RxLine>) =>
    req<RxLine | { line: RxLine }>(`/api/sessions/${id}/rx/${lineId}`, {
      method: "PATCH",
      body: JSON.stringify(patch),
    }),

  confirmRxLine: (id: string, lineId: string) =>
    req<unknown>(`/api/sessions/${id}/rx/${lineId}/confirm`, { method: "POST", body: "{}" }),

  /** The doctor's tap. 409 if any line is unconfirmed — that is the real gate. */
  confirmAll: (id: string) =>
    req<unknown>(`/api/sessions/${id}/rx/confirm-all`, { method: "POST", body: "{}" }),

  rejectRx: (id: string) =>
    req<unknown>(`/api/sessions/${id}/rx/reject`, { method: "POST", body: "{}" }),

  endSession: (id: string) =>
    req<unknown>(`/api/sessions/${id}/end`, { method: "POST", body: "{}" }),

  voiceNoteUrl: (token: string) => `${CONSOLE_URL}/api/voicenote/${token}`,
};
