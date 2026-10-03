// The tenant's projects: what a new session may start in. The list is read
// whole, a page at a time, each page after the last id the one before held.
import { useQuery } from "@tanstack/react-query";
import type { ProjectView } from "@acme/client";
import { api } from "../app/api";
import { keys } from "./keys";

/** The largest page the server gives. */
const PAGE_SIZE = 200;

export function useProjects(enabled = true) {
  return useQuery({
    queryKey: keys.projects.list(PAGE_SIZE),
    queryFn: async ({ signal }) => {
      const read: ProjectView[] = [];
      for (let after: string | null = null; ; ) {
        const cursor: string = after ? `&after=${encodeURIComponent(after)}` : "";
        const page = await api.get<ProjectView[]>(`/v1/projects?limit=${PAGE_SIZE}${cursor}`, { signal });
        read.push(...page);
        const last = page[page.length - 1];
        if (page.length < PAGE_SIZE || last === undefined) return read;
        after = last.id;
      }
    },
    enabled,
  });
}
