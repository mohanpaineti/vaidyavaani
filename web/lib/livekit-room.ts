/**
 * LiveKit room: join with the token from POST /api/sessions and play agent audio.
 *
 * The mic track is NOT published here — push-to-talk owns that (see push-to-talk.ts
 * and docs/02 §1.3). This module only gets us into the room and gets the agent's
 * voice out of the speakers.
 */

import {
  Room,
  RoomEvent,
  Track,
  type RemoteAudioTrack,
  type RemoteTrack,
  type RemoteTrackPublication,
} from "livekit-client";
import type { SessionCreated } from "./types";

export interface RoomHandle {
  room: Room;
  /** Barge-in: stop whatever the agent is currently saying. */
  stopAgentAudio: () => void;
  disconnect: () => Promise<void>;
}

export interface JoinOptions {
  onAgentSpeaking?: (speaking: boolean) => void;
  onConnectionChange?: (connected: boolean) => void;
}

/**
 * Agent audio is attached to detached <audio> elements we own, so barge-in can
 * pause them instantly without waiting on the agent to stop generating.
 */
export async function joinRoom(
  session: SessionCreated,
  opts: JoinOptions = {},
): Promise<RoomHandle> {
  const room = new Room({ adaptiveStream: false, dynacast: false });
  const elements = new Set<HTMLMediaElement>();

  room.on(RoomEvent.TrackSubscribed, (track: RemoteTrack, _pub: RemoteTrackPublication) => {
    if (track.kind !== Track.Kind.Audio) return;
    const el = (track as RemoteAudioTrack).attach();
    el.autoplay = true;
    el.setAttribute("data-vv-agent-audio", "true");
    document.body.appendChild(el);
    elements.add(el);
    void el.play().catch(() => {
      /* Autoplay can be blocked until the first user gesture; the first PTT press unblocks it. */
    });
  });

  room.on(RoomEvent.TrackUnsubscribed, (track: RemoteTrack) => {
    track.detach().forEach((el) => {
      elements.delete(el);
      el.remove();
    });
  });

  room.on(RoomEvent.ActiveSpeakersChanged, (speakers) => {
    const agentSpeaking = speakers.some((p) => p.identity !== room.localParticipant.identity);
    opts.onAgentSpeaking?.(agentSpeaking);
  });

  room.on(RoomEvent.Disconnected, () => opts.onConnectionChange?.(false));
  room.on(RoomEvent.Reconnected, () => opts.onConnectionChange?.(true));

  await room.connect(session.livekit_url, session.livekit_token, { autoSubscribe: true });
  opts.onConnectionChange?.(true);

  return {
    room,
    stopAgentAudio: () => {
      elements.forEach((el) => {
        try {
          el.pause();
          el.currentTime = el.duration && Number.isFinite(el.duration) ? el.duration : 0;
        } catch {
          /* a live MediaStream element has no seekable duration; pause is enough */
        }
      });
    },
    disconnect: async () => {
      elements.forEach((el) => el.remove());
      elements.clear();
      await room.disconnect();
    },
  };
}
