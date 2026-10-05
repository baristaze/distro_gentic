import { useMemo, useState } from "react";
import { errorMessage } from "../../app/errorMessage";
import { useApiKeys, useCreateApiKey, useMe, useRevokeApiKey } from "../../queries/tenancy";
import { useNoticesStore } from "../../store/notices";
import { apiKeyRows, canManageKeys } from "./settingsModel";

/** Security › API keys: the org's keys, a new one, and a revoke. A new key's
 * secret is held here until the person says they copied it, and nowhere else:
 * it is never stored, and no read brings it back. */
export function useApiKeysVm() {
  const me = useMe();
  const mayManageKeys = canManageKeys(me.data);
  const apiKeys = useApiKeys(mayManageKeys);
  const createKey = useCreateApiKey();
  const revokeKey = useRevokeApiKey();
  const notify = useNoticesStore((s) => s.notify);
  const [newKeyName, setNewKeyName] = useState("");
  const [issuedKey, setIssuedKey] = useState<string | null>(null);

  const keys = useMemo(() => apiKeyRows(apiKeys.data ?? [], new Date()), [apiKeys.data]);

  // A write that fails is said, not swallowed: the notice names the refusal
  // and its request id, and the key list refetches on its own.
  const createApiKey = async () => {
    if (!newKeyName.trim()) return;
    try {
      const issued = await createKey.mutateAsync({ name: newKeyName.trim(), role: "member" });
      // A retried create the server answers from its record carries no
      // secret: the first answer, the only one that had it, was lost. The key
      // exists and nobody can use it, which is said, not shown as success.
      if (issued.key === null) {
        setIssuedKey(null);
        notify(`The key "${issued.api_key.name}" was created, but its secret was lost on the way back; revoke it and create another.`);
      } else {
        setIssuedKey(issued.key);
      }
      setNewKeyName("");
    } catch (caught) {
      notify(errorMessage(caught, "The key was not created."));
    }
  };

  // Awaited, not handed to `mutate` as per-call callbacks: one hook holds one
  // mutation observer, and a second revoke started before the first answers
  // drops the first call's callbacks, so its refusal would go unsaid.
  const revokeApiKey = async (id: string) => {
    try {
      await revokeKey.mutateAsync(id);
    } catch (caught) {
      notify(errorMessage(caught, "The key was not revoked."));
    }
  };

  return {
    loading: me.isPending || (mayManageKeys && apiKeys.isPending),
    error: me.error ?? (mayManageKeys ? apiKeys.error : null),
    keys,
    canManageKeys: mayManageKeys,
    // The key list is paged: the screen shows a page and asks for the next,
    // so a key past the first page is still there to revoke.
    hasMoreKeys: apiKeys.hasNextPage,
    loadingMoreKeys: apiKeys.isFetchingNextPage,
    showMoreKeys: () => void apiKeys.fetchNextPage(),
    newKeyName,
    setNewKeyName,
    issuedKey,
    dismissIssuedKey: () => setIssuedKey(null),
    createApiKey,
    creating: createKey.isPending,
    revokeApiKey,
  };
}

export type ApiKeysVm = ReturnType<typeof useApiKeysVm>;
