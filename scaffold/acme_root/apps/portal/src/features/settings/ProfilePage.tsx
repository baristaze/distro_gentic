import type { FormEvent } from "react";
import { Banner, Button, Card, ErrorText, Muted, Page, SegmentedControl, TextField } from "../../design/kit";
import { tokens } from "../../design/tokens";
import { DeleteAccountCard } from "./DeleteAccountCard";
import { useDeleteAccountVm } from "./useDeleteAccountVm";
import { useProfileVm } from "./useProfileVm";

const form = { display: "grid", gap: tokens.space.md, maxWidth: 420 } as const;

/** Personal › Profile: the person's name, the theme, and their account. */
export function ProfilePage() {
  const vm = useProfileVm();
  const leaving = useDeleteAccountVm(vm.me);
  const onSave = (event: FormEvent) => {
    event.preventDefault();
    void vm.save();
  };
  return (
    <Page title="Profile">
      {vm.error ? <Banner>{vm.error.message}</Banner> : null}
      <Card title="You" id="you">
        <form onSubmit={onSave} style={form} aria-label="Your name">
          <TextField label="Name" value={vm.name} onChange={vm.setName} autoComplete="name" placeholder="e.g. Ada Lovelace" />
          <Muted style={{ fontSize: tokens.font.size.sm }}>
            Every org you are in shows this name. You sign in as {vm.email || "…"}.
          </Muted>
          {vm.problem ? <ErrorText>{vm.problem}</ErrorText> : null}
          <div>
            <Button type="submit" disabled={!vm.changed || vm.saving}>
              {vm.saving ? "Saving" : "Save the name"}
            </Button>
          </div>
        </form>
      </Card>
      <Card title="Theme" id="theme">
        <SegmentedControl label="Theme" value={vm.theme} options={vm.themes} onChange={vm.setTheme} />
      </Card>
      <DeleteAccountCard vm={leaving} />
    </Page>
  );
}
