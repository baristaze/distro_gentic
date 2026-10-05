import type { FormEvent } from "react";
import { errorMessage } from "../../app/errorMessage";
import { Banner, Button, Card, ErrorText, Markdown, Muted, Page, TextArea, TextField } from "../../design/kit";
import { tokens } from "../../design/tokens";
import { ProviderNotice } from "../providers/ProviderNotice";
import { shortTime } from "../sessions/sessionsModel";
import { gateLine } from "./playbooksModel";
import { usePlaybooksVm } from "./usePlaybooksVm";

const grid = { display: "grid", gap: tokens.space.md } as const;

export function PlaybooksPage() {
  const vm = usePlaybooksVm();
  const onFind = (event: FormEvent) => {
    event.preventDefault();
    vm.find();
  };
  const onPublish = (event: FormEvent) => {
    event.preventDefault();
    vm.submit();
  };
  return (
    <Page title="Playbooks" notice={<ProviderNotice />}>
      <Card title="Open a playbook" id="open">
        <form onSubmit={onFind} style={{ display: "flex", gap: tokens.space.sm, alignItems: "end", flexWrap: "wrap" }} aria-label="Open a playbook">
          <TextField label="Playbook name" value={vm.lookup} placeholder="release-notes" onChange={vm.setLookup} />
          <Button type="submit">Open</Button>
        </form>
      </Card>
      {vm.error ? <Banner>{errorMessage(vm.error, "The playbook could not be read.")}</Banner> : null}
      {vm.loading ? <Muted>Loading</Muted> : null}
      {vm.name && vm.playbook === null ? (
        <Card>
          <Muted>The org has no playbook named {vm.name}.</Muted>
        </Card>
      ) : null}
      {vm.playbook ? (
        <Card title={`${vm.playbook.name}, version ${vm.playbook.version}`} id="playbook">
          <div style={grid} data-playbook>
            <p style={{ margin: 0 }}>{vm.playbook.description}</p>
            <Muted style={{ fontSize: tokens.font.size.sm }}>
              Published by {vm.playbook.publishedBy}, {shortTime(vm.playbook.publishedAt)}.
            </Muted>
            <Markdown text={vm.playbook.body} />
            {vm.playbook.gates.length > 0 ? (
              <ul aria-label="Gates" style={{ margin: 0 }}>
                {vm.playbook.gates.map((gate, index) => (
                  <li key={index}>{gateLine(gate)}</li>
                ))}
              </ul>
            ) : (
              <Muted>No gate: the session&apos;s own policy holds.</Muted>
            )}
            {vm.mayWrite ? (
              <div>
                <Button tone="plain" onClick={vm.startNext}>
                  Write the next version
                </Button>
              </div>
            ) : null}
          </div>
        </Card>
      ) : null}
      {vm.mayWrite ? (
        <Card title="Publish" id="publish">
          <form onSubmit={onPublish} style={grid} aria-label="Publish a playbook">
            <TextField label="Name" value={vm.draft.name} placeholder="release-notes" onChange={(name) => vm.setDraft({ ...vm.draft, name })} />
            <TextField label="Description" value={vm.draft.description} onChange={(description) => vm.setDraft({ ...vm.draft, description })} />
            <TextArea label="Steps (Markdown)" value={vm.draft.body} onChange={(body) => vm.setDraft({ ...vm.draft, body })} />
            <TextArea label="Gates, one a line" value={vm.draft.gates} onChange={(gates) => vm.setDraft({ ...vm.draft, gates })} />
            <Muted style={{ fontSize: tokens.font.size.sm }}>
              A gate reads &quot;approve tool git_push&quot; or &quot;deny class network&quot;. It only narrows the session&apos;s policy.
            </Muted>
            {vm.problem ? <ErrorText>{vm.problem}</ErrorText> : null}
            <div>
              <Button type="submit" disabled={vm.publishing}>
                {vm.publishing ? "Publishing" : "Publish"}
              </Button>
            </div>
          </form>
        </Card>
      ) : null}
    </Page>
  );
}
