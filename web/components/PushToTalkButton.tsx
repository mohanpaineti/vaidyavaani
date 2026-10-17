"use client";

/**
 * One of the two things on screen that is meant to be tapped. Hold = speak,
 * release = end of turn (docs/01 §2, docs/02 §1.3).
 *
 * Pointer events rather than mouse/touch pairs, so a stylus, a finger and a
 * mouse all behave the same; `setPointerCapture` means a finger that slides off
 * the button mid-sentence still releases on this element rather than stranding
 * the mic open.
 */

import { useCallback, useRef } from "react";

export interface PushToTalkButtonProps {
  side: "patient" | "doctor";
  label: string;
  /** Second line, in the patient's script on the patient side. */
  sublabel?: string;
  fontClass?: string;
  held: boolean;
  /** True while the OTHER side holds — nothing else is tappable during a turn. */
  disabled: boolean;
  size: "patient" | "doctor";
  onPress: () => void;
  onRelease: () => void;
}

export function PushToTalkButton({
  side,
  label,
  sublabel,
  fontClass = "",
  held,
  disabled,
  size,
  onPress,
  onRelease,
}: PushToTalkButtonProps) {
  const captured = useRef<number | null>(null);

  const down = useCallback(
    (e: React.PointerEvent<HTMLButtonElement>) => {
      if (disabled) return;
      e.preventDefault();
      try {
        e.currentTarget.setPointerCapture(e.pointerId);
        captured.current = e.pointerId;
      } catch {
        /* capture is a nicety, not a requirement */
      }
      onPress();
    },
    [disabled, onPress],
  );

  const up = useCallback(
    (e: React.PointerEvent<HTMLButtonElement>) => {
      if (captured.current !== null) {
        try {
          e.currentTarget.releasePointerCapture(captured.current);
        } catch {
          /* already released */
        }
        captured.current = null;
      }
      onRelease();
    },
    [onRelease],
  );

  const base =
    size === "patient"
      ? "min-h-[9rem] text-patient px-6 py-7"
      : "min-h-[4.5rem] text-xl px-5 py-4";

  return (
    <button
      type="button"
      aria-pressed={held}
      aria-label={`${side} push to talk`}
      disabled={disabled}
      onPointerDown={down}
      onPointerUp={up}
      onPointerCancel={up}
      // Space/Enter on a focused button fires click, not pointer events; keep the
      // keyboard path honest for desk testing.
      onKeyDown={(e) => {
        if ((e.key === " " || e.key === "Enter") && !e.repeat && !disabled) {
          e.preventDefault();
          onPress();
        }
      }}
      onKeyUp={(e) => {
        if (e.key === " " || e.key === "Enter") {
          e.preventDefault();
          onRelease();
        }
      }}
      className={[
        "ptt w-full rounded-3xl border-4 font-bold uppercase tracking-wide transition-colors",
        base,
        held
          ? "border-red-300 bg-red-600 text-white shadow-[0_0_0_10px_rgba(220,38,38,0.25)]"
          : "border-sky-400/60 bg-sky-700/30 text-sky-50 hover:bg-sky-700/50",
        disabled ? "cursor-not-allowed opacity-30" : "",
      ].join(" ")}
    >
      <span className="flex items-center justify-center gap-3">
        <span
          aria-hidden
          className={[
            "inline-block rounded-full",
            size === "patient" ? "h-7 w-7" : "h-4 w-4",
            held ? "animate-pulse bg-white" : "bg-sky-300",
          ].join(" ")}
        />
        <span className={fontClass}>{sublabel ?? label}</span>
      </span>
      {sublabel ? (
        <span className="mt-2 block text-base font-medium normal-case tracking-normal opacity-70">
          {label}
        </span>
      ) : null}
    </button>
  );
}
