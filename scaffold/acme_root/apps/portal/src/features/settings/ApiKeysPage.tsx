import type { FormEvent } from "react";
import { Banner, Button, Card, LinkButton, Muted, Page, Table, TextField } from "../../design/kit";
import { tokens } from "../../design/tokens";
import { useApiKeysVm } from "./useApiKeysVm";

/** Security › API keys: the keys a program calls the API with, as the org.
 * A new key's secret shows once, until "Done"; no screen shows it again. */
export function ApiKeysPage() {
  const vm = useApiKeysVm();
  const onCreate = (event: FormEvent) => {
    event.preventDefault();
    void vm.createApiKey();
  };
  return (
    <Page title="API keys">
      {vm.error ? <Banner>{vm.error.message}</Banner> : null}
      {vm.loading ? (
        <Muted>Loading</Muted>
      ) : !vm.canManageKeys ? (
        <Card>
          <Muted>Your role does not manage the org&apos;s API keys. An owner or an admin can give you a role that does.</Muted>
        </Card>
      ) : (
        <Card title="The org's keys" id="keys">
          {vm.issuedKey ? (
            <Banner>
              Copy this key now; it is shown once: <code data-issued-key>{vm.issuedKey}</code>{" "}
              <Button tone="plain" onClick={vm.dismissIssuedKey}>
                Done
              </Button>
            </Banner>
          ) : null}
          <form onSubmit={onCreate} aria-label="New key" style={{ display: "flex", gap: tokens.space.sm, alignItems: "end", margin: `${tokens.space.md} 0` }}>
            <TextField label="New key name" placeholder="e.g. ci-pipeline" value={vm.newKeyName} onChange={vm.setNewKeyName} />
            <Button type="submit" disabled={vm.creating}>
              Create key
            </Button>
          </form>
          <Table
            headers={["Name", "Role", "State", "Expires", ""]}
            rows={vm.keys.map((k) => [
              k.name,
              k.role,
              k.state,
              k.expires,
              k.state === "active" ? (
                <Button tone="danger" onClick={() => void vm.revokeApiKey(k.id)}>
                  Revoke
                </Button>
              ) : (
                ""
              ),
            ])}
          />
          {vm.hasMoreKeys ? (
            <div style={{ paddingTop: tokens.space.md }}>
              {vm.loadingMoreKeys ? <Muted>Loading</Muted> : <LinkButton onClick={vm.showMoreKeys}>Show more</LinkButton>}
            </div>
          ) : null}
        </Card>
      )}
    </Page>
  );
}
