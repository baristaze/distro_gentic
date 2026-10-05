// The live view of a session: a read, never a push. The API hands the
// viewer a short-lived handle, and the viewer reads each open stream from
// the part it last saw. A stream that is no longer open has become a step,
// which the history shows.
import { useEffect, useState } from "react";
import type { LivePageView, LivePartView, LiveReadView, LiveStreamView } from "@acme/client";
import { api } from "../app/api";

export const LIVE_POLL_MS = 1000;

/** A run of one stream's parts of one kind, for one call when they name
 * one: a tool's input names the call it asks for, as its output may. */
export interface LiveRun {
  kind: LivePartView["kind"];
  tool: string | null;
  toolUseId: string | null;
  text: string;
}

/** One open stream as the viewer holds it: its parts joined into runs of one
 * kind, the last place read, and whether the buffer dropped parts before
 * the first one held. */
export interface LiveStream {
  stepId: string;
  last: number | null;
  dropped: boolean;
  runs: LiveRun[];
}

function joined(runs: readonly LiveRun[], parts: readonly LivePartView[]): LiveRun[] {
  const out = runs.map((run) => ({ ...run }));
  for (const part of parts) {
    const tail = out[out.length - 1];
    const tool = part.tool ?? null;
    const toolUseId = part.tool_use_id ?? null;
    if (tail && tail.kind === part.kind && tail.tool === tool && tail.toolUseId === toolUseId) tail.text += part.text;
    else out.push({ kind: part.kind, tool, toolUseId, text: part.text });
  }
  return out;
}

/** The streams a read answered, each added to what was held for it: the
 * open streams are the ones the read names, so a stream it no longer names
 * is gone. A stream the viewer had not seen starts from what it returned. */
export function mergeLive(held: readonly LiveStream[], read: readonly LiveStreamView[]): LiveStream[] {
  const before = new Map(held.map((stream) => [stream.stepId, stream]));
  return read.map((stream) => {
    const known = before.get(stream.step_id);
    const last = stream.parts.length > 0 ? stream.parts[stream.parts.length - 1]!.last : (known?.last ?? null);
    return {
      stepId: stream.step_id,
      last,
      dropped: (known?.dropped ?? false) || stream.dropped,
      runs: joined(known?.runs ?? [], stream.parts),
    };
  });
}

/** The session's open streams, read from the part each was last read at. The
 * read is a handle's, asked for again before it ends; a read that fails is
 * tried again at the next tick, since a live part is a cache whose loss
 * costs nothing: the step it adds up to is the record. */
export function useLiveStreams(id: string, active: boolean): LiveStream[] {
  const [streams, setStreams] = useState<LiveStream[]>([]);
  useEffect(() => {
    if (!active) return;
    let stopped = false;
    let handle: LiveReadView | null = null;
    let shown: LiveStream[] = [];
    let timer: ReturnType<typeof setTimeout>;
    const tick = async () => {
      try {
        if (!handle || Date.parse(handle.expires_at) - Date.now() < LIVE_POLL_MS * 5) {
          handle = await api.post<LiveReadView>(`/v1/agent-sessions/${encodeURIComponent(id)}/live`);
        }
        const params = new URLSearchParams({ handle: handle.handle });
        for (const stream of shown) if (stream.last !== null) params.append("after", `${stream.stepId}:${stream.last}`);
        const page = await api.get<LivePageView>(`/v1/live?${params}`);
        if (stopped) return;
        shown = mergeLive(shown, page.streams);
        setStreams(shown);
      } catch {
        handle = null;
      }
      if (!stopped) timer = setTimeout(() => void tick(), LIVE_POLL_MS);
    };
    timer = setTimeout(() => void tick(), 0);
    return () => {
      stopped = true;
      clearTimeout(timer);
      setStreams([]);
    };
  }, [id, active]);
  return active ? streams : [];
}
