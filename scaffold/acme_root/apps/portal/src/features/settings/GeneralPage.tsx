import { Banner, Card, Muted, Page } from "../../design/kit";
import { tokens } from "../../design/tokens";
import { useMe, useUsers } from "../../queries/tenancy";
import { DeleteOrgCard } from "./DeleteOrgCard";
import { orgLines } from "./settingsModel";
import { StorageCard } from "./StorageCard";
import { useDeleteOrgVm } from "./useDeleteOrgVm";

const label = { color: tokens.color.muted } as const;
const value = { margin: 0 } as const;

/** Organization › General: the org the tab is in, its storage, and its end. */
export function GeneralPage() {
  const me = useMe();
  const users = useUsers();
  const closing = useDeleteOrgVm(me.data);
  const lines = me.data ? orgLines(me.data, users.data?.length ?? null) : null;
  return (
    <Page title="General">
      {me.error ? <Banner>{me.error.message}</Banner> : null}
      <Card title="Organization" id="organization">
        {lines === null ? (
          <Muted>Loading</Muted>
        ) : (
          <dl
            data-org
            style={{ display: "grid", gridTemplateColumns: "max-content 1fr", gap: `${tokens.space.sm} ${tokens.space.md}`, margin: 0 }}
          >
            <dt style={label}>Name</dt>
            <dd style={value}>{lines.name}</dd>
            <dt style={label}>Short name</dt>
            <dd style={value}>
              <code>{lines.slug}</code>
            </dd>
            <dt style={label}>Kind</dt>
            <dd style={value}>{lines.kind}</dd>
            <dt style={label}>Your role</dt>
            <dd style={value}>{lines.role}</dd>
            <dt style={label}>Members</dt>
            <dd style={value}>{lines.members ?? "Loading"}</dd>
          </dl>
        )}
      </Card>
      <StorageCard />
      <DeleteOrgCard vm={closing} />
    </Page>
  );
}
