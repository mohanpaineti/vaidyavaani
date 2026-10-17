"use client";

/**
 * Wires the three transports into one object the page renders from:
 *   console WS   → everything visual (docs/04 §5)
 *   LiveKit room → agent audio
 *   push-to-talk → the mic track mute (docs/02 §1.3)
 *
 * Identical against `console --mock` and the real console. No mock branch here.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { ConsoleSocket, emptyView, type ConsoleView } from "@/lib/console-ws";
import { api, ConsoleApiError } from "@/lib/console-api";
import { joinRoom, type RoomHandle } from "@/lib/livekit-room";
import { PushToTalk, type PttSide } from "@/lib/push-to-talk";
import type { RxLine, SessionCreated } from "@/lib/types";

export interface UseSession {
  view: ConsoleView;
  session: SessionCreated | null;
  starting: boolean;
  /** Set when the console could not be reached at all, so the screen can say so. */
  startError: string | null;
  audioJoined: boolean;
  /** Null when nobody is holding a button. */
  holding: PttSide | null;
  agentSpeaking: boolean;
  /** 409 from confirm-all — the server-side gate refusing. */
  gateRefusal: string | null;
  start: () => Promise<void>;
  pressPtt: (side: PttSide) => void;
  releasePtt: (side: PttSide) => void;
  patchLine: (lineId: string, patch: Partial<RxLine>) => Promise<void>;
  confirmLine: (lineId: string) => Promise<void>;
  confirmAll: () => Promise<void>;
  rejectRx: () => Promise<void>;
  setLanguage: (side: "patient" | "doctor", lang: string) => Promise<void>;
  setConsent: (given: boolean) => Promise<void>;
  endSession: () => Promise<void>;
}

export function useSession(): UseSession {
  const [view, setView] = useState<ConsoleView>(emptyView);
  const [session, setSession] = useState<SessionCreated | null>(null);
  const [starting, setStarting] = useState(false);
  const [startError, setStartError] = useState<string | null>(null);
  const [audioJoined, setAudioJoined] = useState(false);
  const [holding, setHolding] = useState<PttSide | null>(null);
  const [agentSpeaking, setAgentSpeaking] = useState(false);
  const [gateRefusal, setGateRefusal] = useState<string | null>(null);

  const socketRef = useRef<ConsoleSocket | null>(null);
  const roomRef = useRef<RoomHandle | null>(null);
  const pttRef = useRef<PushToTalk | null>(null);
  const sessionIdRef = useRef<string | null>(null);

  const start = useCallback(async () => {
    if (starting || sessionIdRef.current) return;
    setStarting(true);
    setStartError(null);
    try {
      const created = await api.createSession();
      sessionIdRef.current = created.session_id;
      setSession(created);

      const socket = new ConsoleSocket({
        consoleUrl: process.env.NEXT_PUBLIC_CONSOLE_URL ?? "http://127.0.0.1:8808",
        sessionId: created.session_id,
        onView: setView,
      });
      socket.connect();
      socketRef.current = socket;

      // Audio is best-effort: the screen is the doctor's primary channel, so a
      // LiveKit failure must not take the console down with it.
      try {
        const handle = await joinRoom(created, {
          onAgentSpeaking: setAgentSpeaking,
          onConnectionChange: setAudioJoined,
        });
        roomRef.current = handle;
        pttRef.current = new PushToTalk({
          room: handle.room,
          sendFrame: (frame) => socket.send(frame),
          stopAgentAudio: handle.stopAgentAudio,
          onChange: setHolding,
        });
      } catch {
        setAudioJoined(false);
      }
    } catch (err) {
      setStartError(err instanceof Error ? err.message : String(err));
      sessionIdRef.current = null;
    } finally {
      setStarting(false);
    }
  }, [starting]);

  useEffect(() => {
    return () => {
      void pttRef.current?.dispose();
      void roomRef.current?.disconnect();
      socketRef.current?.close();
    };
  }, []);

  const pressPtt = useCallback((side: PttSide) => {
    setAgentSpeaking(false);
    const ptt = pttRef.current;
    if (!ptt) {
      // No LiveKit: still record who is speaking, so the audit trail survives.
      setHolding(side);
      socketRef.current?.send({ type: "ptt", side, state: "down" });
      return;
    }
    void ptt.press(side);
  }, []);

  const releasePtt = useCallback((side: PttSide) => {
    const ptt = pttRef.current;
    if (!ptt) {
      setHolding(null);
      socketRef.current?.send({ type: "ptt", side, state: "up" });
      return;
    }
    void ptt.release(side);
  }, []);

  const withId = useCallback(
    async <T,>(fn: (id: string) => Promise<T>): Promise<T | undefined> => {
      const id = sessionIdRef.current;
      if (!id) return undefined;
      return fn(id);
    },
    [],
  );

  const patchLine = useCallback(
    async (lineId: string, patch: Partial<RxLine>) => {
      // The console answers with rx_line_updated over the WS, so nothing is
      // applied optimistically here — one source of truth.
      await withId((id) => api.patchRxLine(id, lineId, patch));
    },
    [withId],
  );

  const confirmLine = useCallback(
    async (lineId: string) => {
      await withId((id) => api.confirmRxLine(id, lineId));
    },
    [withId],
  );

  const confirmAll = useCallback(async () => {
    setGateRefusal(null);
    try {
      await withId((id) => api.confirmAll(id));
    } catch (err) {
      if (err instanceof ConsoleApiError && err.status === 409) {
        setGateRefusal("Console refused: a line is still unconfirmed.");
      } else {
        setGateRefusal(err instanceof Error ? err.message : String(err));
      }
    }
  }, [withId]);

  const rejectRx = useCallback(async () => {
    await withId((id) => api.rejectRx(id));
  }, [withId]);

  const setLanguage = useCallback(
    async (side: "patient" | "doctor", lang: string) => {
      await withId((id) => api.setLanguage(id, side, lang));
    },
    [withId],
  );

  const setConsent = useCallback(
    async (given: boolean) => {
      await withId((id) => api.setConsent(id, given));
    },
    [withId],
  );

  const endSession = useCallback(async () => {
    await withId((id) => api.endSession(id));
    await pttRef.current?.dispose();
    await roomRef.current?.disconnect();
    socketRef.current?.close();
  }, [withId]);

  return useMemo(
    () => ({
      view,
      session,
      starting,
      startError,
      audioJoined,
      holding,
      agentSpeaking,
      gateRefusal,
      start,
      pressPtt,
      releasePtt,
      patchLine,
      confirmLine,
      confirmAll,
      rejectRx,
      setLanguage,
      setConsent,
      endSession,
    }),
    [
      view,
      session,
      starting,
      startError,
      audioJoined,
      holding,
      agentSpeaking,
      gateRefusal,
      start,
      pressPtt,
      releasePtt,
      patchLine,
      confirmLine,
      confirmAll,
      rejectRx,
      setLanguage,
      setConsent,
      endSession,
    ],
  );
}
