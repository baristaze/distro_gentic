import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { runtimeConfig } from "../../app/config";
import { errorMessage } from "../../app/errorMessage";
import { useSlot } from "../../app/slot";
import { useSendMessage, useStartSession } from "../../queries/agentSessions";
import { useProjects } from "../../queries/projects";
import { useMe } from "../../queries/tenancy";
import { useNoticesStore } from "../../store/notices";
import { NO_PROJECT, projectRequired } from "../sessions/sessionsModel";
import { chosenAgent, chosenProject, composerStart } from "./homeModel";

/** Home's composer: a prompt, the agent the slot offers (its first by
 * default), and the project it works in. Send starts the session, sends it
 * the prompt, and opens it. A member who may not write reads the prompt's
 * examples and starts nothing. */
export function useHomeVm(initialPrompt: string) {
  const slot = useSlot();
  const me = useMe();
  const mayWrite = me.data?.permissions.includes("write") ?? false;
  const projects = useProjects(mayWrite);
  const required = projectRequired(runtimeConfig().environment);
  const start = useStartSession();
  const send = useSendMessage();
  const navigate = useNavigate();
  const notify = useNoticesStore((s) => s.notify);
  const [prompt, setPrompt] = useState(initialPrompt);
  const [kind, setKind] = useState<string | null>(null);
  const [projectId, setProjectId] = useState<string | null>(null);
  const [problem, setProblem] = useState<string | null>(null);

  const agent = chosenAgent(slot.agents, kind);
  const project = chosenProject(projects.data ?? null, required, projectId);
  const count = projects.data?.length ?? 0;

  const submit = () => {
    if (start.isPending || send.isPending) return;
    const made = composerStart({ prompt, kind: agent?.kind ?? "", projectId: project?.id ?? "" }, { required, count });
    if ("problem" in made) {
      setProblem(made.problem);
      return;
    }
    setProblem(null);
    start.mutate(made.request, {
      onSuccess: (session) =>
        send.mutate(
          { id: session.id, text: made.text },
          {
            onSuccess: () => navigate(`/sessions/${session.id}`),
            onError: (caught) => {
              notify(errorMessage(caught, "The session started, but its prompt was not sent."), { tone: "problem" });
              navigate(`/sessions/${session.id}`);
            },
          },
        ),
      onError: (caught) => setProblem(errorMessage(caught, "The session did not start.")),
    });
  };

  return {
    ready: me.data !== undefined,
    mayWrite,
    prompt,
    setPrompt,
    placeholder: slot.examples.composer ?? "Describe a task",
    starters: slot.examples.starters ?? [],
    agents: slot.agents,
    agent,
    setKind,
    required,
    projects: projects.data ?? [],
    project,
    setProjectId,
    // What the composer says: the last start's problem, or why none can start.
    problem:
      problem ??
      (projects.error
        ? errorMessage(projects.error, "The projects could not be read.")
        : required && projects.data !== undefined && count === 0
          ? NO_PROJECT
          : null),
    submit,
    starting: start.isPending || send.isPending,
  };
}
