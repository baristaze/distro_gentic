import { useState } from "react";
import { useSearchParams } from "react-router-dom";
import { errorMessage } from "../../app/errorMessage";
import { personName } from "../../app/recordModel";
import { usePlaybook, usePublishPlaybook } from "../../queries/playbooks";
import { useMe, useUsers } from "../../queries/tenancy";
import { draftOf, EMPTY_DRAFT, publishRequest, type PlaybookDraft } from "./playbooksModel";

/** A playbook by the name the address bar holds, at its latest version, and
 * a name's next version, published by a member who may write. */
export function usePlaybooksVm() {
  const [params, setParams] = useSearchParams();
  const name = params.get("name")?.trim() ?? "";
  const me = useMe();
  const users = useUsers();
  const playbook = usePlaybook(name);
  const publish = usePublishPlaybook();
  const [lookup, setLookup] = useState(name);
  const [draft, setDraft] = useState<PlaybookDraft>(EMPTY_DRAFT);
  const [problem, setProblem] = useState<string | null>(null);
  const submit = () => {
    const made = publishRequest(draft);
    if ("problem" in made) {
      setProblem(made.problem);
      return;
    }
    setProblem(null);
    publish.mutate(made.request, {
      onSuccess: (published) => {
        setDraft(EMPTY_DRAFT);
        setLookup(published.name);
        setParams({ name: published.name });
      },
      onError: (caught) => setProblem(errorMessage(caught, "The playbook was not published.")),
    });
  };
  const view = playbook.data;
  return {
    name,
    lookup,
    setLookup,
    find: () => setParams(lookup.trim() ? { name: lookup.trim() } : {}),
    loading: name !== "" && playbook.isPending,
    error: playbook.error,
    playbook: view
      ? {
          name: view.name,
          version: view.version,
          description: view.description,
          body: view.body,
          gates: view.gates,
          publishedBy: personName(users.data, view.published_by),
          publishedAt: view.created_at,
        }
      : view,
    mayWrite: me.data?.permissions.includes("write") ?? false,
    draft,
    setDraft,
    startNext: () => view && setDraft(draftOf(view)),
    problem,
    submit,
    publishing: publish.isPending,
  };
}
