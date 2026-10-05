import { useMemo } from "react";
import type { Role } from "@acme/client";
import { errorMessage } from "../../app/errorMessage";
import { useMe, useMemberships, useUpdateMemberRole, useUsers } from "../../queries/tenancy";
import { useNoticesStore } from "../../store/notices";
import { memberRows } from "./settingsModel";

/** Organization › Members: who is in the org, and each one's role. */
export function useMembersVm() {
  const me = useMe();
  const users = useUsers();
  const memberships = useMemberships();
  const changeRole = useUpdateMemberRole();
  const notify = useNoticesStore((s) => s.notify);

  const members = useMemo(
    () => memberRows(users.data ?? [], memberships.data ?? [], me.data),
    [users.data, memberships.data, me.data],
  );

  // A refusal is said in the server's words: the rules are the server's.
  const setRole = async (userId: string, role: Role) => {
    try {
      await changeRole.mutateAsync({ userId, body: { role } });
    } catch (caught) {
      notify(errorMessage(caught, "The role was not changed."));
    }
  };

  return {
    me: me.data,
    loading: me.isPending || users.isPending,
    error: me.error ?? users.error,
    members,
    setRole,
    changingRole: changeRole.isPending,
  };
}

export type MembersVm = ReturnType<typeof useMembersVm>;
