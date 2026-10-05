// The toasts a session raises, on any page, when it starts to need its
// person: one of theirs, or a sub-agent in a tree of theirs. Each says its
// title and what it needs, the agent's question where it asks one, and
// opens it. They read the sessions list the shell already keeps live.
import { useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { NeedsYouIcon, Toast } from "../../design/kit";
import { askedIn, oneLine } from "../../features/session/timelineModel";
import { useStepsBeforeAnswer } from "../../queries/agentSessions";
import { nextToasts, NO_TOASTS, type NeedsYouNotice } from "./shellModel";

function NeedsYouToast({ notice, onOpen, onDismiss }: { notice: NeedsYouNotice; onOpen: () => void; onDismiss: () => void }) {
  const steps = useStepsBeforeAnswer(notice.id, notice.asks);
  const question = steps.data ? askedIn(steps.data) : null;
  return (
    <Toast action="Open" onAction={onOpen} onDismiss={onDismiss}>
      <span className="acme-needs-toast">
        <NeedsYouIcon size={16} />
        <span className="acme-needs-toast-text">
          <strong>{notice.title}</strong>
          <span>{question ? oneLine(question, 120) : notice.need}</span>
        </span>
      </span>
    </Toast>
  );
}

export function NeedsYouToasts({ needing, ready }: { needing: ReadonlyMap<string, NeedsYouNotice>; ready: boolean }) {
  const navigate = useNavigate();
  const { pathname } = useLocation();
  const open = /^\/sessions\/([^/]+)/.exec(pathname)?.[1] ?? null;
  const [state, setState] = useState(NO_TOASTS);
  // Read again with each read of the list: what changed since the last.
  const next = ready ? nextToasts(state, needing, open) : state;
  if (next !== state) setState(next);
  const drop = (id: string) => setState((now) => ({ ...now, toasts: now.toasts.filter((toast) => toast.id !== id) }));
  if (next.toasts.length === 0) return null;
  return (
    <div className="acme-needs-toasts" role="region" aria-label="Sessions that need you">
      {next.toasts.map((notice) => (
        <NeedsYouToast
          key={notice.id}
          notice={notice}
          onOpen={() => {
            drop(notice.id);
            navigate(`/sessions/${notice.id}`);
          }}
          onDismiss={() => drop(notice.id)}
        />
      ))}
    </div>
  );
}
