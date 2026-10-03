import { Link } from "react-router-dom";
import { AppNav } from "../../app/AppNav";
import { Banner, Card, Muted, Page } from "../../design/kit";
import { tokens } from "../../design/tokens";
import { ProviderNotice } from "../providers/ProviderNotice";
import { useHomeVm } from "./useHomeVm";

/** The org's record and settings screens, each with what it holds. */
const PLACES: readonly { to: string; name: string; says: string }[] = [
  { to: "/projects", name: "Projects", says: "each bound to its repository, and the credential it is read with" },
  { to: "/models", name: "Models", says: "the org's own provider keys, and its model for each role" },
  { to: "/automations", name: "Automations", says: "what starts or messages a session on an event or a schedule" },
  { to: "/playbooks", name: "Playbooks", says: "the team's procedures, as versioned briefs" },
  { to: "/knowledge", name: "Knowledge", says: "what a session recalls, and the suggestions waiting on a review" },
  { to: "/approvals", name: "Approvals", says: "the calls waiting on a person" },
  { to: "/audit", name: "Audit", says: "what happened in the org, and who did it" },
  { to: "/usage", name: "Usage", says: "each budget and what its window spent" },
];

const label = { color: tokens.color.muted } as const;
const value = { margin: 0 } as const;

export function HomePage() {
  const vm = useHomeVm();
  return (
    <Page title="Home" nav={<AppNav />} notice={<ProviderNotice />}>
      {vm.error ? <Banner>{vm.error.message}</Banner> : null}
      {vm.card === null ? (
        <Card>
          <Muted>Loading</Muted>
        </Card>
      ) : (
        <Card title={vm.card.orgName} id="org">
          <dl
            data-home
            style={{
              display: "grid",
              gridTemplateColumns: "max-content 1fr",
              gap: `${tokens.space.sm} ${tokens.space.md}`,
              margin: 0,
            }}
          >
            <dt style={label}>You</dt>
            <dd style={value}>{vm.card.personName}</dd>
            <dt style={label}>Role</dt>
            <dd style={value}>{vm.card.role}</dd>
            <dt style={label}>Members</dt>
            <dd style={value}>{vm.card.members}</dd>
          </dl>
        </Card>
      )}
      <Card title="Sessions" id="sessions">
        <Link to="/sessions">The org&apos;s agent sessions</Link>
      </Card>
      <Card title="Records and settings" id="records">
        <ul aria-label="Records and settings" style={{ margin: 0, paddingLeft: tokens.space.lg, display: "grid", gap: tokens.space.sm }}>
          {PLACES.map((place) => (
            <li key={place.to}>
              <Link to={place.to}>{place.name}</Link>
              <Muted>: {place.says}</Muted>
            </li>
          ))}
        </ul>
      </Card>
      <Muted style={{ fontSize: tokens.font.size.sm }}>The product&apos;s own screens go here.</Muted>
    </Page>
  );
}
