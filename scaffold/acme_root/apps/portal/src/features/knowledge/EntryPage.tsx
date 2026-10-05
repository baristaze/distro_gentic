import type { FormEvent } from "react";
import { Link, useParams } from "react-router-dom";
import { errorMessage } from "../../app/errorMessage";
import { Banner, Button, Card, ErrorText, Markdown, Muted, Page, Pill, TextArea, TextField } from "../../design/kit";
import { tokens } from "../../design/tokens";
import { ProviderNotice } from "../providers/ProviderNotice";
import { shortTime } from "../sessions/sessionsModel";
import { ENTRY_EXAMPLES } from "./knowledgeModel";
import { useEntryVm } from "./useEntryVm";

const back = <Link to="/knowledge">← Knowledge</Link>;
const grid = { display: "grid", gap: tokens.space.md } as const;

export function EntryPage() {
  const { entryId = "" } = useParams();
  const vm = useEntryVm(entryId);
  if (vm.missing) {
    return (
      <Page title="No entry here" back={back}>
        <Card>
          <Muted>This org holds no entry with this address. It may belong to another org.</Muted>
        </Card>
      </Page>
    );
  }
  if (!vm.entry) {
    return (
      <Page title="Entry" back={back}>
        {vm.error ? <Banner>{errorMessage(vm.error, "The entry could not be read.")}</Banner> : <Muted>Loading</Muted>}
      </Page>
    );
  }
  const entry = vm.entry;
  const onSubmit = (event: FormEvent) => {
    event.preventDefault();
    vm.submit();
  };
  return (
    <Page title={entry.title} back={back} notice={<ProviderNotice />}>
      <Card id="entry">
        <div style={grid} data-entry>
          <div style={{ display: "flex", gap: tokens.space.sm, flexWrap: "wrap", alignItems: "center" }}>
            <Pill tone={entry.status === "reviewed" ? "accent" : entry.status === "rejected" ? "danger" : "plain"}>{entry.state}</Pill>
            <Muted>
              Recalled by {entry.trigger.join(", ")}. Version {entry.version}, {shortTime(entry.updatedAt)}.
            </Muted>
          </div>
          <Muted style={{ fontSize: tokens.font.size.sm }}>
            {entry.suggestedIn ? (
              <>
                Suggested by the agent of <Link to={`/sessions/${entry.suggestedIn}`}>a session</Link>
                {entry.reviewedBy ? `; reviewed by ${entry.reviewedBy}.` : "."}
              </>
            ) : (
              `Written by ${entry.reviewedBy ?? "a person"}.`
            )}
          </Muted>
          <Markdown text={entry.text} />
          {vm.problem && !vm.draft ? <ErrorText>{vm.problem}</ErrorText> : null}
          {vm.mayWrite && entry.status === "suggested" ? (
            <div style={{ display: "flex", gap: tokens.space.sm }}>
              <Button onClick={vm.keep} disabled={vm.reviewing}>
                Keep
              </Button>
              <Button tone="danger" onClick={vm.reject} disabled={vm.reviewing}>
                Reject
              </Button>
            </div>
          ) : null}
        </div>
      </Card>
      {vm.mayWrite ? (
        <Card title="Edit" id="edit">
          {vm.draft ? (
            <form onSubmit={onSubmit} style={grid} aria-label="Edit entry">
              <TextField label="Title" placeholder={ENTRY_EXAMPLES.title} value={vm.draft.title} onChange={(title) => vm.setDraft({ ...vm.draft!, title })} />
              <TextField
                label="Recalled by"
                placeholder={ENTRY_EXAMPLES.trigger}
                info={ENTRY_EXAMPLES.triggerInfo}
                value={vm.draft.trigger}
                onChange={(trigger) => vm.setDraft({ ...vm.draft!, trigger })}
              />
              <TextArea
                label="What a session should know (Markdown)"
                placeholder={ENTRY_EXAMPLES.text}
                value={vm.draft.text}
                onChange={(text) => vm.setDraft({ ...vm.draft!, text })}
              />
              {vm.problem ? <ErrorText>{vm.problem}</ErrorText> : null}
              <div style={{ display: "flex", gap: tokens.space.sm }}>
                <Button type="submit" disabled={vm.saving}>
                  {vm.saving ? "Saving" : "Save"}
                </Button>
                <Button tone="plain" onClick={vm.cancel}>
                  Cancel
                </Button>
              </div>
            </form>
          ) : (
            <Button onClick={vm.startEdit}>Edit the entry</Button>
          )}
        </Card>
      ) : null}
    </Page>
  );
}
