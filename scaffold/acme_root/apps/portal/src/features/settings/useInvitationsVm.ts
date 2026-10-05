import type { MeView, Role } from "@acme/client";
import { useMemo, useState } from "react";
import { errorMessage } from "../../app/errorMessage";
import {
  useInvitations,
  useInviteMember,
  useResendInvitation,
  useRevokeInvitation,
} from "../../queries/tenancy";
import { useNoticesStore } from "../../store/notices";
import { canManageMembers, checkInvite, invitableRoles, invitationRows } from "./settingsModel";

/** Inviting people, for a member who manages members. The identity provider
 * sends the invitation's email. */
export function useInvitationsVm(me: MeView | undefined) {
  const mayManage = canManageMembers(me);
  const invitations = useInvitations(mayManage);
  const invite = useInviteMember();
  const resend = useResendInvitation();
  const revoke = useRevokeInvitation();
  const notify = useNoticesStore((s) => s.notify);
  const roles = invitableRoles(me);
  const [email, setEmail] = useState("");
  const [role, setRole] = useState<Role>("member");
  const [error, setError] = useState<string | null>(null);

  const rows = useMemo(() => invitationRows(invitations.data ?? [], new Date()), [invitations.data]);

  const send = async () => {
    setError(null);
    const refused = checkInvite(email);
    if (refused) {
      setError(refused);
      return;
    }
    try {
      await invite.mutateAsync({ email: email.trim(), role: roles.includes(role) ? role : "member" });
      setEmail("");
    } catch (caught) {
      notify(errorMessage(caught, "The invitation was not sent."));
    }
  };

  const resendOne = async (id: string) => {
    try {
      await resend.mutateAsync(id);
    } catch (caught) {
      notify(errorMessage(caught, "The invitation was not sent again."));
    }
  };

  const revokeOne = async (id: string) => {
    try {
      await revoke.mutateAsync(id);
    } catch (caught) {
      notify(errorMessage(caught, "The invitation was not revoked."));
    }
  };

  return {
    mayManage,
    roles,
    email,
    role,
    error,
    rows,
    loading: mayManage && invitations.isPending,
    sending: invite.isPending,
    hasMore: invitations.hasNextPage,
    loadingMore: invitations.isFetchingNextPage,
    showMore: () => void invitations.fetchNextPage(),
    setEmail,
    setRole: (value: string) => setRole(value as Role),
    send,
    resend: resendOne,
    revoke: revokeOne,
  };
}
