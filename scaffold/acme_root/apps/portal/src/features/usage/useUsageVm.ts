import { personName } from "../../app/recordModel";
import { useProjects } from "../../queries/projects";
import { useUsage } from "../../queries/usage";
import { useUsers } from "../../queries/tenancy";
import { usageRow } from "./usageModel";

/** Each of the org's budgets with what its current window spent and holds,
 * a page at a time. */
export function useUsageVm() {
  const usage = useUsage();
  const users = useUsers();
  const projects = useProjects();
  const nameOf = {
    person: (id: string) => personName(users.data, id),
    project: (id: string) => projects.data?.find((project) => project.id === id)?.name ?? "no longer held",
  };
  return {
    rows: usage.data?.map((each) => usageRow(each, nameOf)) ?? null,
    error: usage.error,
    hasMore: usage.hasNextPage,
    loadingMore: usage.isFetchingNextPage,
    loadMore: () => void usage.fetchNextPage(),
  };
}
