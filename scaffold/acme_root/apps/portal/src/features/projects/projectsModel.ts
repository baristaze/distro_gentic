// Pure: the tenant's projects as the screens show them, a new project's
// request from what a person typed, and the fetch credential's form, whose
// password goes out once and is never shown again. No React, no fetch.
import type { CreateProjectRequest, FetchCredentialRequest, FetchCredentialView, ProjectView, RepositoryView } from "@acme/client";

export const NAME_MAX = 200;

/** A host by its domain name and a path of an owner, any groups, and a
 * name, as the API holds them: lower case, no segment starting with a dot. */
const HOST = /^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?(\.[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?)+$/;
const PATH = /^[a-z0-9_][a-z0-9_.-]*(\/[a-z0-9_][a-z0-9_.-]*)+$/;

export function repositoryLine(repository: RepositoryView): string {
  return `${repository.host}/${repository.path}`;
}

export interface ProjectRow {
  id: string;
  name: string;
  repository: string;
  createdAt: string;
}

export function projectRow(project: ProjectView): ProjectRow {
  return { id: project.id, name: project.name, repository: repositoryLine(project.repository), createdAt: project.created_at };
}

/** A repository from its address as a person writes it: `host/owner/name`,
 * with or without `https://` before it and `.git` after it. */
export function repositoryOf(text: string): RepositoryView | { problem: string } {
  const address = text
    .trim()
    .toLowerCase()
    .replace(/^https:\/\//, "")
    .replace(/\.git$/, "")
    .replace(/\/$/, "");
  const slash = address.indexOf("/");
  const host = slash < 0 ? address : address.slice(0, slash);
  const path = slash < 0 ? "" : address.slice(slash + 1);
  if (!address) return { problem: "Name the repository, as host/owner/name." };
  if (host.length > 253 || !HOST.test(host)) return { problem: "The repository's host is a domain name, such as github.com." };
  if (path.length > 255 || !PATH.test(path)) return { problem: "Name the repository as host/owner/name." };
  return { host, path };
}

export interface NewProjectDraft {
  name: string;
  repository: string;
}

export function createRequest(draft: NewProjectDraft): { request: CreateProjectRequest } | { problem: string } {
  const name = draft.name.trim();
  if (!name) return { problem: "Give the project a name." };
  if (name.length > NAME_MAX) return { problem: `A name is at most ${NAME_MAX} characters.` };
  const repository = repositoryOf(draft.repository);
  if ("problem" in repository) return repository;
  return { request: { name, repository } };
}

export function renameRequest(name: string, current: string): { name: string } | { problem: string } | null {
  const trimmed = name.trim();
  if (trimmed === current) return null;
  if (!trimmed) return { problem: "Give the project a name." };
  if (trimmed.length > NAME_MAX) return { problem: `A name is at most ${NAME_MAX} characters.` };
  return { name: trimmed };
}

export const USERNAME_MAX = 200;
export const PASSWORD_MAX = 4096;

export interface CredentialDraft {
  username: string;
  password: string;
}

/** The credential's request. The password is sent as typed, never trimmed:
 * a token's every character is its own. */
export function credentialRequest(draft: CredentialDraft): { request: FetchCredentialRequest } | { problem: string } {
  const username = draft.username.trim();
  if (!username) return { problem: "Name the user the credential reads as." };
  if (username.length > USERNAME_MAX) return { problem: `A user name is at most ${USERNAME_MAX} characters.` };
  if (!draft.password) return { problem: "Enter the password or token." };
  if (draft.password.length > PASSWORD_MAX) return { problem: `A password is at most ${PASSWORD_MAX} characters.` };
  return { request: { username, password: draft.password } };
}

/** What the page says of the credential: only that one was set, by whom,
 * and when, from the write's answer. No read gives it back, so a page opened
 * later says only how it is kept. */
export function credentialLine(saved: Pick<FetchCredentialView, "updated_at"> | null, by: string, when: (iso: string) => string): string {
  if (saved === null) return "A credential, once set, is never shown again. Setting one replaces the last.";
  return `A credential is set: by ${by}, ${when(saved.updated_at)}. It is never shown again.`;
}
