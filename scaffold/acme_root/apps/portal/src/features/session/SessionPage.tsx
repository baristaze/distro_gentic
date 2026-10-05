import { Link, useParams } from "react-router-dom";
import { errorMessage } from "../../app/errorMessage";
import { usePageCommands } from "../../app/shell/shellContext";
import { Banner, Card, Muted, Page, SegmentedControl } from "../../design/kit";
import { SESSION_TABS } from "./sessionModel";
import { ChangesPart, ChildrenPart, EvidencePart, LivePart, SessionHeader, ThreadPart, TimelinePart, ToolCallsPart } from "./SessionParts";
import { useSessionVm } from "./useSessionVm";

const back = <Link to="/sessions">← Sessions</Link>;

/** One session: its header and what it asks of a person, then one part at a
 * time (the thread, the timeline, its tool calls, its evidence, its changes,
 * its sub-agents, and the live view with take control). A session the
 * member's org does not hold shows nothing of it. */
export function SessionPage() {
  const { sessionId = "" } = useParams();
  const vm = useSessionVm(sessionId);
  // What the page can do now, offered first in the shell's search (Cmd-K).
  usePageCommands(vm.commands);
  if (vm.missing) {
    return (
      <Page title="No session here" back={back}>
        <Card>
          <Muted>This org holds no session with this address. It may belong to another org, or it was deleted.</Muted>
        </Card>
      </Page>
    );
  }
  if (!vm.session) {
    return (
      <Page title="Session" back={back}>
        {vm.error ? <Banner>{errorMessage(vm.error, "The session could not be read.")}</Banner> : <Muted>Loading</Muted>}
      </Page>
    );
  }
  return (
    <Page title={vm.session.title} back={back}>
      <SessionHeader vm={vm} />
      <div style={{ overflowX: "auto" }}>
        <SegmentedControl label="Part of the session" value={vm.tab} options={SESSION_TABS} onChange={vm.setTab} />
      </div>
      {vm.tab === "thread" ? <ThreadPart vm={vm} /> : null}
      {vm.tab === "timeline" ? <TimelinePart key={vm.id} vm={vm} /> : null}
      {vm.tab === "tools" ? <ToolCallsPart vm={vm} /> : null}
      {vm.tab === "evidence" ? <EvidencePart vm={vm} /> : null}
      {vm.tab === "changes" ? <ChangesPart vm={vm} /> : null}
      {vm.tab === "children" ? <ChildrenPart vm={vm} /> : null}
      {vm.tab === "live" ? <LivePart vm={vm} /> : null}
    </Page>
  );
}
