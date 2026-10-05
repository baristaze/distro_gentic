// The support dock: the shell's column at the right edge, a conversation
// with the platform assistant beside whatever page is open. It never
// navigates on its own, and no page opens anything in it. A link in a reply
// that the router serves is a chip, which opens its page in the main area
// and leaves the dock as it is; any other link is text with its address.
// ✕ or Esc closes it, Expand gives the chat the main area's width, and New
// conversation starts the next message afresh.
import { type FormEvent, type KeyboardEvent, type ReactNode } from "react";
import { Link, type RouteObject } from "react-router-dom";
import {
  CloseTabIcon,
  CollapseIcon,
  ExpandIcon,
  Muted,
  NewSessionIcon,
  SendIcon,
  TextArea,
  Tooltip,
  useSplitter,
  type LinkView,
} from "../../design/kit";
import { Timeline } from "../../features/session/Timeline";
import { DOCK, type DockMode } from "./dockModel";
import { supportLink } from "./supportLinks";
import type { SupportVm } from "./useSupportVm";

/** A reply's links as the dock draws them: a chip for a page the router
 * serves, which `go` opens; its words and address as text for any other. */
export function chipLinks(routes: readonly RouteObject[], go: (to: string) => void): LinkView {
  return (link) => {
    const drawn = supportLink(link.href, link.text, routes);
    if (drawn.kind === "text") return drawn.text;
    return (
      <button type="button" className="acme-link-chip" title={drawn.to} onClick={() => go(drawn.to)}>
        {link.label as ReactNode}
      </button>
    );
  };
}

export const SUPPORT_EXAMPLE = 'Ask how something works, or why it waits, e.g. "Why is this session parked?"';

export function SupportDock({
  vm,
  mode,
  width,
  draft,
  onDraft,
  links,
  onClose,
  onExpand,
  onResize,
}: {
  vm: SupportVm;
  mode: Exclude<DockMode, "closed">;
  width: number;
  draft: string;
  onDraft: (draft: string) => void;
  links: LinkView;
  onClose: () => void;
  onExpand: () => void;
  onResize: (width: number) => void;
}) {
  const splitter = useSplitter(width, onResize, DOCK, "left");
  const submit = () => {
    const text = draft.trim();
    if (text && !vm.sending) vm.send(text, () => onDraft(""));
  };
  const onSubmit = (event: FormEvent) => {
    event.preventDefault();
    submit();
  };
  const onKey = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    if (event.key !== "Enter" || !(event.metaKey || event.ctrlKey)) return;
    event.preventDefault();
    submit();
  };
  // Esc closes the dock from anywhere inside it, unless a control in it
  // used the key already (a menu, a tooltip).
  const onEscape = (event: KeyboardEvent<HTMLElement>) => {
    if (event.key !== "Escape" || event.defaultPrevented) return;
    event.preventDefault();
    onClose();
  };
  const expanded = mode === "expanded";
  return (
    <aside
      className="acme-dock"
      data-mode={mode}
      aria-label="Support"
      style={mode === "expanded" ? undefined : { width }}
      onKeyDown={onEscape}
    >
      {mode === "side" ? <div className="acme-dock-splitter" aria-label="Resize support" title="Drag to resize; double-click resets" {...splitter} /> : null}
      <header className="acme-dock-head">
        <strong>Support</strong>
        {vm.id ? (
          <Link className="acme-head-link" to={`/sessions/${vm.id}`} title="This conversation as a session, in the main area">
            As a session
          </Link>
        ) : null}
        <span className="acme-composer-gap" />
        <Tooltip tip="New conversation" side="bottom">
          <button type="button" className="acme-icon-button" aria-label="New conversation" disabled={vm.id === null} onClick={vm.fresh}>
            <NewSessionIcon />
          </button>
        </Tooltip>
        {mode === "sheet" ? null : (
          <Tooltip tip={expanded ? "Back beside the page" : "Expand"} side="bottom">
            <button type="button" className="acme-icon-button" aria-label={expanded ? "Back beside the page" : "Expand"} aria-pressed={expanded} onClick={onExpand}>
              {expanded ? <CollapseIcon /> : <ExpandIcon />}
            </button>
          </Tooltip>
        )}
        <Tooltip tip="Close" shortcut="Esc" side="bottom">
          <button type="button" className="acme-icon-button" aria-label="Close support" onClick={onClose}>
            <CloseTabIcon />
          </button>
        </Tooltip>
      </header>
      {vm.id === null ? (
        <div className="acme-dock-empty">
          {vm.reading ? (
            <Muted>Loading</Muted>
          ) : (
            <>
              <p>Ask how the platform works, or why something waits.</p>
              <Muted>The assistant reads with your permissions, and it knows the page you are on. A link in its answer opens beside this conversation.</Muted>
            </>
          )}
        </div>
      ) : (
        <Timeline vm={vm.timeline} compact link={links} empty="Nothing yet." />
      )}
      <div className="acme-dock-composer">
        {vm.maySend ? (
          <form className="acme-composer" aria-label="Ask support" onSubmit={onSubmit}>
            <TextArea label="Ask support" hideLabel rows={2} autoFocus placeholder={SUPPORT_EXAMPLE} value={draft} onChange={onDraft} onKeyDown={onKey} />
            <div className="acme-composer-bar">
              {vm.working ? <Muted>It works; a message now is read at its next step.</Muted> : null}
              <span className="acme-composer-gap" />
              <Tooltip tip="Send" shortcut="⌘↵" side="top">
                <button type="submit" className="acme-send" aria-label="Send" disabled={vm.sending || !draft.trim()}>
                  <SendIcon />
                </button>
              </Tooltip>
            </div>
          </form>
        ) : (
          <Muted>A member who may write asks support here.</Muted>
        )}
      </div>
    </aside>
  );
}
