import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { runtimeConfig } from "../../app/config";
import { errorMessage } from "../../app/errorMessage";
import { useSlot } from "../../app/slot";
import { useSendMessage, useStartSession } from "../../queries/agentSessions";
import { useAgentProjects } from "../../queries/agentProjects";
import { useMe } from "../../queries/tenancy";
import { useNoticesStore } from "../../store/notices";
import { NO_AGENT_PROJECT, agentProjectRequired } from "../sessions/sessionsModel";
import { chosenAgent, chosenAgentProject, composerStart } from "./homeModel";

/** Home's composer: a prompt, the agent the slot offers (its first by
 * default), and the agent project it works in. Send starts the session, sends it
 * the prompt, and opens it. A member who may not write reads the prompt's
 * examples and starts nothing. */
export function useHomeVm(initialPrompt: string) {
  const slot = useSlot();
  const me = useMe();
  const mayWrite = me.data?.permissions.includes("write") ?? false;
  const agentProjects = useAgentProjects(mayWrite);
  const required = agentProjectRequired(runtimeConfig().environment);
  const start = useStartSession();
  const send = useSendMessage();
  const navigate = useNavigate();
  const notify = useNoticesStore((s) => s.notify);
  const [prompt, setPrompt] = useState(initialPrompt);
  const [kind, setKind] = useState<string | null>(null);
  const [agentProjectId, setAgentProjectId] = useState<string | null>(null);
  const [problem, setProblem] = useState<string | null>(null);

  const agent = chosenAgent(slot.agents, kind);
  const agentProject = chosenAgentProject(agentProjects.data ?? null, required, agentProjectId);
  const count = agentProjects.data?.length ?? 0;

  const submit = () => {
    if (start.isPending || send.isPending) return;
    const made = composerStart({ prompt, kind: agent?.kind ?? "", agentProjectId: agentProject?.id ?? "" }, { required, count });
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
    agentProjects: agentProjects.data ?? [],
    agentProject,
    setAgentProjectId,
    // What the composer says: the last start's problem, or why none can start.
    problem:
      problem ??
      (agentProjects.error
        ? errorMessage(agentProjects.error, "The agent projects could not be read.")
        : required && agentProjects.data !== undefined && count === 0
          ? NO_AGENT_PROJECT
          : null),
    submit,
    starting: start.isPending || send.isPending,
  };
}
