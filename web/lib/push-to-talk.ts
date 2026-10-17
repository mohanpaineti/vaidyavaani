/**
 * Push-to-talk — a LiveKit track mute, per docs/02 §1.3.
 *
 * The mic track is published muted and is unmuted ONLY while a button is held.
 * Release mutes it again, which produces a clean silence boundary immediately;
 * that boundary is what lets the agent run `pace: snappy` turn detection without
 * the usual risk of cutting people off.
 *
 * Two side effects go with every press:
 *   1. Barge-in — agent playback stops the instant a new press lands.
 *   2. An advisory `ptt` frame (docs/04 §5) so the console has the ground-truth
 *      speaker side for display and audit. Advisory only: the mute above is the
 *      enforcement.
 *
 * The track is created and published lazily on the first press, so we never hold
 * the mic open before anyone has asked to speak, and we avoid renegotiating the
 * publication on every press.
 */

import {
  createLocalAudioTrack,
  type LocalAudioTrack,
  type Room,
} from "livekit-client";
import type { ClientFrame } from "./types";

export type PttSide = "patient" | "doctor";

export interface PushToTalkOptions {
  room: Room;
  /** Sends the advisory frame; wired to ConsoleSocket.send. */
  sendFrame: (frame: ClientFrame) => void;
  /** Barge-in hook; wired to RoomHandle.stopAgentAudio. */
  stopAgentAudio: () => void;
  onChange?: (holding: PttSide | null) => void;
  onError?: (err: unknown) => void;
}

export class PushToTalk {
  private track: LocalAudioTrack | null = null;
  private holding: PttSide | null = null;
  /** Guards against a release landing before the lazy publish resolves. */
  private pending: Promise<void> | null = null;

  constructor(private readonly opts: PushToTalkOptions) {}

  get heldBy(): PttSide | null {
    return this.holding;
  }

  /** Button down. Ignored if the other side is already holding — one speaker at a time. */
  async press(side: PttSide): Promise<void> {
    if (this.holding && this.holding !== side) return;

    // Barge-in first: the patient pressing while the agent talks must cut it dead.
    this.opts.stopAgentAudio();

    this.holding = side;
    this.opts.onChange?.(side);
    this.opts.sendFrame({ type: "ptt", side, state: "down" });

    this.pending = this.openMic(side);
    try {
      await this.pending;
    } finally {
      this.pending = null;
    }
  }

  /** Button up. Mutes the track — the end-of-turn signal. */
  async release(side: PttSide): Promise<void> {
    if (this.holding !== side) return;
    this.holding = null;
    this.opts.onChange?.(null);
    this.opts.sendFrame({ type: "ptt", side, state: "up" });

    if (this.pending) await this.pending.catch(() => undefined);
    if (this.track) await this.track.mute();
  }

  private async openMic(side: PttSide): Promise<void> {
    try {
      if (!this.track) {
        const track = await createLocalAudioTrack({
          echoCancellation: true,
          noiseSuppression: true,
          autoGainControl: true,
        });
        // Mute before publishing so nothing leaks between publish and the first unmute.
        await track.mute();
        await this.opts.room.localParticipant.publishTrack(track, {
          name: "ptt-mic",
          // Voice-grade; the noisy OPD does not reward a wider band.
          audioPreset: { maxBitrate: 32_000 },
        });
        this.track = track;
      }
      // The button may already be back up by the time the mic opened.
      if (this.holding === side) {
        await this.track.unmute();
      } else {
        await this.track.mute();
      }
    } catch (err) {
      this.holding = null;
      this.opts.onChange?.(null);
      this.opts.onError?.(err);
    }
  }

  /** Session teardown: unpublish and stop the mic entirely. */
  async dispose(): Promise<void> {
    if (!this.track) return;
    const track = this.track;
    this.track = null;
    try {
      await this.opts.room.localParticipant.unpublishTrack(track);
    } catch {
      /* room may already be gone */
    }
    track.stop();
  }
}
