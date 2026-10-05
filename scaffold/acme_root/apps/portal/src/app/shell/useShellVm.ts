import { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useHeldTools } from "../../queries/approvals";
import { useAgentSessions, useParkedSessions } from "../../queries/agentSessions";
import { useMe } from "../../queries/tenancy";
import { SIDEBAR, usePreferencesStore } from "../../store/preferences";
import { errorMessage } from "../errorMessage";
import { useSlot } from "../slot";
import { DEFAULT_FILTER, filtering, needsYou, shellGroups, type SessionFilter } from "./shellModel";

/** The clock the rows' times are read against, a minute at a time. */
function useMinute(): Date {
  const [now, setNow] = useState(() => new Date());
  useEffect(() => {
    const timer = window.setInterval(() => setNow(new Date()), 60_000);
    return () => window.clearInterval(timer);
  }, []);
  return now;
}

/** The left bar: the org's newest sessions and every parked one, grouped by
 * what they ask of a person, under the filter the person keeps; the
 * platform's and the product's entries; and the bar's width and fold. A push
 * about a session reads the lists again (the realtime router). */
export function useShellVm() {
  const navigate = useNavigate();
  const slot = useSlot();
  const me = useMe();
  const newest = useAgentSessions(null);
  const parked = useParkedSessions();
  const filter = usePreferencesStore((s) => s.sessionFilter);
  const setFilter = usePreferencesStore((s) => s.setSessionFilter);
  const width = usePreferencesStore((s) => s.sidebarWidth);
  const setWidth = usePreferencesStore((s) => s.setSidebarWidth);
  const folded = usePreferencesStore((s) => s.sidebarFolded);
  const toggle = usePreferencesStore((s) => s.toggleSidebar);
  const now = useMinute();

  const sessions = useMemo(() => [...(parked.data ?? []), ...(newest.data ?? [])], [parked.data, newest.data]);
  const deciding = sessions.filter((session) => needsYou(session) && session.park?.unlock === "approval").map((session) => session.id);
  const held = useHeldTools(deciding);
  const meId = me.data?.user.id ?? null;
  const groups = useMemo(
    () => shellGroups(sessions, { filter, me: meId, held: held.data }),
    [sessions, filter, meId, held.data],
  );
  const kinds = useMemo(() => {
    const named = slot.agents.map((agent) => ({ value: agent.kind, label: agent.label }));
    const seen = [...new Set(sessions.map((session) => session.kind))]
      .filter((kind) => !named.some((agent) => agent.value === kind))
      .map((kind) => ({ value: kind, label: kind }));
    return [...named, ...seen];
  }, [slot.agents, sessions]);
  const error = newest.error ?? parked.error;

  return {
    nav: slot.nav,
    groups,
    now,
    loading: newest.isPending || parked.isPending,
    error: error ? errorMessage(error, "The sessions could not be read.") : null,
    empty: groups.needsYou.length + groups.running.length + groups.recent.length === 0,
    filter,
    filtered: filtering(filter),
    setFilter: (next: SessionFilter) => setFilter(next),
    clearFilter: () => setFilter(DEFAULT_FILTER),
    kinds,
    width,
    setWidth,
    bounds: SIDEBAR,
    folded,
    toggle,
    goHome: () => navigate("/"),
  };
}

export type ShellVm = ReturnType<typeof useShellVm>;
