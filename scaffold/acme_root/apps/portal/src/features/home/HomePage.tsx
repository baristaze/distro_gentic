// Home: one box and three starter prompts. Under the box, the agent chip
// (the slot's first is the default), the project chip, and Send (Cmd-Enter).
// Send starts the session, sends it the prompt, and opens it.
import type { FormEvent, KeyboardEvent } from "react";
import { Link, useLocation } from "react-router-dom";
import {
  BotIcon,
  ChevronIcon,
  ErrorText,
  InfoTip,
  Menu,
  MenuItemRadio,
  MenuText,
  Muted,
  ProjectIcon,
  SendIcon,
  TextArea,
  Tooltip,
} from "../../design/kit";
import { ProviderNotice } from "../providers/ProviderNotice";
import { useHomeVm } from "./useHomeVm";

/** A prompt handed over by the search ("Start a session: ‹text›") lands in
 * the box; each such visit starts the composer over. */
export function HomePage() {
  const location = useLocation();
  const handed = (location.state as { prompt?: unknown } | null)?.prompt;
  return <Composer key={location.key} initialPrompt={typeof handed === "string" ? handed : ""} />;
}

function Composer({ initialPrompt }: { initialPrompt: string }) {
  const vm = useHomeVm(initialPrompt);
  const onSubmit = (event: FormEvent) => {
    event.preventDefault();
    vm.submit();
  };
  const onKey = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    if (event.key !== "Enter" || !(event.metaKey || event.ctrlKey)) return;
    event.preventDefault();
    vm.submit();
  };
  const projectLabel = vm.project?.name ?? (vm.required ? "Choose a project" : "No project");
  return (
    <div className="acme-app">
      <main className="acme-home">
        <div className="acme-page-notice">
          <ProviderNotice />
        </div>
        <h1 className="acme-sr-only">Home</h1>
        <h2 className="acme-home-ask">What should we work on?</h2>
        <form className="acme-composer" aria-label="New session" onSubmit={onSubmit}>
          <TextArea
            label="Prompt"
            hideLabel
            rows={4}
            autoFocus
            placeholder={vm.placeholder}
            value={vm.prompt}
            disabled={!vm.mayWrite}
            onChange={vm.setPrompt}
            onKeyDown={onKey}
          />
          <div className="acme-composer-bar">
            <Menu
              label="Agents"
              triggerLabel={`Agent: ${vm.agent?.label ?? "none"}`}
              triggerClassName="acme-chip"
              minWidth={300}
              disabled={!vm.mayWrite || vm.agents.length === 0}
              trigger={
                <>
                  <BotIcon />
                  <span>{vm.agent?.label ?? "No agent"}</span>
                  <ChevronIcon />
                </>
              }
            >
              {vm.agents.map((agent) => (
                <MenuItemRadio key={agent.kind} checked={agent.kind === vm.agent?.kind} onSelect={() => vm.setKind(agent.kind)}>
                  <span className="acme-choice">
                    <span>{agent.label}</span>
                    <span className="acme-choice-about">{agent.about}</span>
                  </span>
                </MenuItemRadio>
              ))}
            </Menu>
            {vm.agent ? <InfoTip label={`About ${vm.agent.label}`}>{vm.agent.about}</InfoTip> : null}
            <Menu
              label="Projects"
              triggerLabel={`Project: ${projectLabel}`}
              triggerClassName="acme-chip"
              minWidth={240}
              disabled={!vm.mayWrite}
              trigger={
                <>
                  <ProjectIcon />
                  <span>{projectLabel}</span>
                  <ChevronIcon />
                </>
              }
            >
              {vm.required ? null : (
                <MenuItemRadio checked={vm.project === null} onSelect={() => vm.setProjectId("")}>
                  No project
                </MenuItemRadio>
              )}
              {vm.projects.map((project) => (
                <MenuItemRadio key={project.id} checked={project.id === vm.project?.id} onSelect={() => vm.setProjectId(project.id)}>
                  {project.name}
                </MenuItemRadio>
              ))}
              {vm.projects.length === 0 && vm.required ? <MenuText>No project yet</MenuText> : null}
            </Menu>
            <span className="acme-composer-gap" />
            <Tooltip tip="Send" shortcut="⌘↵" side="top">
              <button type="submit" className="acme-send" aria-label="Send" disabled={!vm.mayWrite || vm.starting}>
                <SendIcon />
              </button>
            </Tooltip>
          </div>
        </form>
        {vm.problem ? (
          <ErrorText>
            {vm.problem}{" "}
            {vm.required && vm.projects.length === 0 ? <Link to="/projects">Add a project</Link> : null}
          </ErrorText>
        ) : null}
        {vm.ready && !vm.mayWrite ? <Muted>You can read this org&apos;s sessions. Starting one needs the write permission.</Muted> : null}
        {vm.starters.length > 0 ? (
          <ul aria-label="Starter prompts" className="acme-starters">
            {vm.starters.map((starter) => (
              <li key={starter}>
                <button type="button" className="acme-starter" disabled={!vm.mayWrite} onClick={() => vm.setPrompt(starter)}>
                  {starter}
                </button>
              </li>
            ))}
          </ul>
        ) : null}
      </main>
    </div>
  );
}
