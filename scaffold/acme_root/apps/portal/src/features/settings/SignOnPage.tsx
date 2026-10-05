import { Button, Card, Muted, Page } from "../../design/kit";
import { tokens } from "../../design/tokens";
import { useMe } from "../../queries/tenancy";
import { useSignOnVm } from "./useSignOnVm";

/** Security › Single sign-on: a team org's own identity provider, set up on
 * the identity provider's page by a member who manages members. */
export function SignOnPage() {
  const me = useMe();
  const vm = useSignOnVm(me.data);
  return (
    <Page title="Single sign-on">
      <Card title="Your identity provider" id="sign-on">
        {me.data === undefined ? (
          <Muted>Loading</Muted>
        ) : vm.available ? (
          <>
            <Muted>
              Your organization&apos;s admin connects its identity provider (Okta, Entra ID, Google Workspace, any SAML or OIDC
              one) on WorkOS&apos;s page, and people of your verified domain then sign in through it.
            </Muted>
            <div style={{ display: "flex", flexWrap: "wrap", gap: tokens.space.sm, marginTop: tokens.space.md }}>
              <Button onClick={() => void vm.open("sso")} disabled={vm.opening}>
                Set up single sign-on
              </Button>
              <Button tone="plain" onClick={() => void vm.open("domain_verification")} disabled={vm.opening}>
                Verify a domain
              </Button>
            </div>
          </>
        ) : (
          <Muted>
            Single sign-on is a team organization&apos;s, and a member who manages its members sets it up. Here, people sign
            in as they do now.
          </Muted>
        )}
      </Card>
    </Page>
  );
}
