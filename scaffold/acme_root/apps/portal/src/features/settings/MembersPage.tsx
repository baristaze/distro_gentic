import { Banner, Button, Card, ErrorText, LinkButton, Muted, Page, Select, Table, TextField } from "../../design/kit";
import { tokens } from "../../design/tokens";
import { RoleControl } from "./RoleControl";
import { useInvitationsVm } from "./useInvitationsVm";
import { useMembersVm } from "./useMembersVm";

/** Organization › Members: who is in the org, an invitation, and the ones waiting. */
export function MembersPage() {
  const vm = useMembersVm();
  const invites = useInvitationsVm(vm.me);
  return (
    <Page title="Members">
      {vm.error ? <Banner>{vm.error.message}</Banner> : null}
      <Card title="Members" id="members">
        {vm.loading ? (
          <Muted>Loading</Muted>
        ) : (
          <Table
            headers={["Name", "Email", "Role", "Joined"]}
            rows={vm.members.map((m) => [
              m.name,
              m.email,
              <RoleControl key={m.id} row={m} onChange={(id, role) => void vm.setRole(id, role)} busy={vm.changingRole} />,
              m.joined,
            ])}
          />
        )}
        {invites.mayManage ? (
          <form
            onSubmit={(event) => {
              event.preventDefault();
              void invites.send();
            }}
            aria-label="Invite"
            style={{ display: "flex", flexWrap: "wrap", gap: tokens.space.sm, alignItems: "end", marginTop: tokens.space.md }}
          >
            <TextField label="Invite by email" type="email" placeholder="teammate@example.com" value={invites.email} onChange={invites.setEmail} />
            <Select
              label="Role"
              value={invites.role}
              options={invites.roles.map((role) => ({ value: role, label: role }))}
              onChange={invites.setRole}
            />
            <Button type="submit" disabled={invites.sending}>
              {invites.sending ? "Sending…" : "Invite"}
            </Button>
          </form>
        ) : null}
        {invites.error ? <ErrorText>{invites.error}</ErrorText> : null}
      </Card>
      {invites.mayManage ? (
        <Card title="Pending invitations" id="invitations">
          {invites.loading ? (
            <Muted>Loading</Muted>
          ) : invites.rows.length === 0 ? (
            <Muted>No invitation is waiting.</Muted>
          ) : (
            <Table
              headers={["Email", "Role", "Expires", ""]}
              rows={invites.rows.map((row) => [
                row.email,
                row.role,
                row.expired ? `${row.expires} (expired)` : row.expires,
                <span key={row.id} style={{ display: "inline-flex", gap: tokens.space.sm }}>
                  <Button tone="plain" onClick={() => void invites.resend(row.id)}>
                    Resend
                  </Button>
                  <Button tone="danger" onClick={() => void invites.revoke(row.id)}>
                    Revoke
                  </Button>
                </span>,
              ])}
            />
          )}
          {invites.hasMore ? (
            <div style={{ paddingTop: tokens.space.md }}>
              {invites.loadingMore ? <Muted>Loading</Muted> : <LinkButton onClick={invites.showMore}>Show more</LinkButton>}
            </div>
          ) : null}
        </Card>
      ) : null}
    </Page>
  );
}
