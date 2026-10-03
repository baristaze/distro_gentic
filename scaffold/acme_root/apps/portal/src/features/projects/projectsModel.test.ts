import { describe, expect, it } from "vitest";
import { createRequest, credentialLine, credentialRequest, renameRequest, repositoryOf } from "./projectsModel";

describe("repositoryOf", () => {
  it("reads host/owner/name, with or without a scheme and .git", () => {
    expect(repositoryOf("github.com/Octo/Reports")).toEqual({ host: "github.com", path: "octo/reports" });
    expect(repositoryOf(" https://gitlab.example.com/group/sub/repo.git ")).toEqual({ host: "gitlab.example.com", path: "group/sub/repo" });
  });
  it("refuses an address the API would refuse, saying why", () => {
    expect(repositoryOf("")).toEqual({ problem: "Name the repository, as host/owner/name." });
    expect(repositoryOf("localhost/a/b")).toEqual({ problem: "The repository's host is a domain name, such as github.com." });
    expect(repositoryOf("github.com/reports")).toEqual({ problem: "Name the repository as host/owner/name." });
    expect(repositoryOf("github.com/octo/../x")).toEqual({ problem: "Name the repository as host/owner/name." });
    expect(repositoryOf("http://github.com/octo/x")).toEqual({ problem: "The repository's host is a domain name, such as github.com." });
  });
});

describe("createRequest", () => {
  it("is a name and its repository", () => {
    expect(createRequest({ name: " Docs ", repository: "github.com/octo/docs" })).toEqual({
      request: { name: "Docs", repository: { host: "github.com", path: "octo/docs" } },
    });
  });
  it("asks for a name first", () => {
    expect(createRequest({ name: " ", repository: "github.com/octo/docs" })).toEqual({ problem: "Give the project a name." });
    expect(createRequest({ name: "x".repeat(201), repository: "github.com/octo/docs" })).toEqual({ problem: "A name is at most 200 characters." });
  });
});

it("renames only to a new name", () => {
  expect(renameRequest(" Docs ", "Docs")).toBeNull();
  expect(renameRequest("Guides", "Docs")).toEqual({ name: "Guides" });
  expect(renameRequest(" ", "Docs")).toEqual({ problem: "Give the project a name." });
});

describe("credentialRequest", () => {
  it("sends the password exactly as typed", () => {
    expect(credentialRequest({ username: " bot ", password: " s3cret " })).toEqual({ request: { username: "bot", password: " s3cret " } });
  });
  it("asks for both parts", () => {
    expect(credentialRequest({ username: "", password: "x" })).toEqual({ problem: "Name the user the credential reads as." });
    expect(credentialRequest({ username: "bot", password: "" })).toEqual({ problem: "Enter the password or token." });
    expect(credentialRequest({ username: "bot", password: "x".repeat(4097) })).toEqual({ problem: "A password is at most 4096 characters." });
  });
});

it("says a credential is set and when, never what it is", () => {
  const when = (iso: string) => iso.slice(0, 10);
  expect(credentialLine(null, "Ada", when)).toBe("A credential, once set, is never shown again. Setting one replaces the last.");
  expect(credentialLine({ updated_at: "2026-10-03T10:00:00Z" }, "Ada", when)).toBe("A credential is set: by Ada, 2026-10-03. It is never shown again.");
});
