import { useState } from "react";
import type { ProviderName } from "@acme/client";
import { errorMessage } from "../../app/errorMessage";
import { personName } from "../../app/recordModel";
import { useChoose, useDropChoice, useMatrixChoices, useMatrixOptions } from "../../queries/matrix";
import { useProviderKeys, useSaveKey } from "../../queries/providerKeys";
import { useMe, useUsers } from "../../queries/tenancy";
import { canManageMembers } from "../settings/settingsModel";
import { shortTime } from "../sessions/sessionsModel";
import { keyRows, liveKeyLine, PROVIDERS, roleRows, saveKeyRequest } from "./modelsModel";

type ByProvider = Partial<Record<ProviderName, string>>;

/** The org's own keys and its models by role. A key typed into its field
 * stays in the form until it is sent, and the field is emptied when the save
 * lands; the page then shows the key's record alone. Only a member who
 * manages the org is offered a field, a choice, or a drop. */
export function useModelsVm() {
  const me = useMe();
  const users = useUsers();
  const keys = useProviderKeys();
  const save = useSaveKey();
  const options = useMatrixOptions();
  const choices = useMatrixChoices();
  const choose = useChoose();
  const drop = useDropChoice();
  const [drafts, setDrafts] = useState<ByProvider>({});
  const [keyProblems, setKeyProblems] = useState<ByProvider>({});
  const [picked, setPicked] = useState<Record<string, string>>({});
  const [roleProblem, setRoleProblem] = useState<string | null>(null);
  const nameOf = (id: string) => personName(users.data, id);
  const held = keys.data ?? [];
  const rows = options.data && choices.data ? roleRows(options.data, choices.data) : null;
  const saveKey = (provider: ProviderName) => {
    const made = saveKeyRequest(drafts[provider] ?? "");
    if ("problem" in made) {
      setKeyProblems({ ...keyProblems, [provider]: made.problem });
      return;
    }
    setKeyProblems({ ...keyProblems, [provider]: undefined });
    save.mutate(
      { provider, value: made.value },
      {
        onSuccess: () => setDrafts((current) => ({ ...current, [provider]: "" })),
        onError: (caught) => setKeyProblems((current) => ({ ...current, [provider]: errorMessage(caught, "The key was not saved.") })),
      },
    );
  };
  const chooseFor = (role: string) => {
    const row = rows?.find((each) => each.role === role);
    const fill = row?.options[Number(picked[role] ?? "-1")];
    if (!fill) {
      setRoleProblem("Pick one of the role's models first.");
      return;
    }
    setRoleProblem(null);
    choose.mutate({ name: role, fill }, { onError: (caught) => setRoleProblem(errorMessage(caught, "The choice was not saved.")) });
  };
  const dropFor = (role: string) => {
    setRoleProblem(null);
    drop.mutate(role, { onError: (caught) => setRoleProblem(errorMessage(caught, "The choice was not dropped.")) });
  };
  return {
    mayManage: canManageMembers(me.data),
    error: keys.error ?? options.error ?? choices.error,
    providers: PROVIDERS.map((provider) => ({
      provider,
      line: keys.data ? liveKeyLine(held, provider, nameOf, shortTime) : null,
      draft: drafts[provider] ?? "",
      problem: keyProblems[provider] ?? null,
    })),
    setDraft: (provider: ProviderName, value: string) => setDrafts({ ...drafts, [provider]: value }),
    saveKey,
    savingKey: save.isPending ? (save.variables?.provider ?? null) : null,
    keyRows: keys.data ? keyRows(held, nameOf) : null,
    roles: rows,
    picked,
    pick: (role: string, index: string) => setPicked({ ...picked, [role]: index }),
    chooseFor,
    dropFor,
    roleBusy: choose.isPending || drop.isPending,
    roleProblem,
  };
}
