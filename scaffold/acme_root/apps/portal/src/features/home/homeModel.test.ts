import { describe, expect, it } from "vitest";
import { NO_PROJECT } from "../sessions/sessionsModel";
import { chosenAgent, chosenProject, composerStart, TITLE_CUT, titleFromPrompt } from "./homeModel";

const agents = [
  { kind: "engineer", label: "Engineer", about: "Changes code." },
  { kind: "analysis", label: "Analysis", about: "Reads." },
];

describe("home's composer", () => {
  it("titles a session by the prompt's first line, cut at 80 characters", () => {
    expect(titleFromPrompt("\n  Fix the failing test  \nThen open a pull request")).toBe("Fix the failing test");
    const long = titleFromPrompt("word ".repeat(40));
    expect(long.length).toBeLessThanOrEqual(TITLE_CUT);
    expect(long.endsWith("…")).toBe(true);
    expect(titleFromPrompt("x".repeat(TITLE_CUT))).toBe("x".repeat(TITLE_CUT));
  });

  it("starts the chosen agent on the prompt's title, and sends the whole prompt", () => {
    const draft = { prompt: " Fix the test\nwith care ", kind: "engineer", projectId: "p1" };
    expect(composerStart(draft, { required: true, count: 1 })).toEqual({
      request: { title: "Fix the test", kind: "engineer", project_id: "p1" },
      text: "Fix the test\nwith care",
    });
    expect(composerStart({ ...draft, projectId: "" }, { required: false, count: 0 })).toEqual({
      request: { title: "Fix the test", kind: "engineer" },
      text: "Fix the test\nwith care",
    });
  });

  it("says why it cannot start: no prompt, no agent, or no project where one is required", () => {
    expect(composerStart({ prompt: "  ", kind: "engineer", projectId: "" }, { required: false, count: 0 })).toEqual({
      problem: "Describe the task first.",
    });
    expect(composerStart({ prompt: "Fix it", kind: "", projectId: "" }, { required: false, count: 0 })).toEqual({
      problem: "Choose the agent that works on it.",
    });
    expect(composerStart({ prompt: "Fix it", kind: "engineer", projectId: "" }, { required: true, count: 0 })).toEqual({
      problem: NO_PROJECT,
    });
  });

  it("shows the chosen agent, else the slot's first, and none when the slot names none", () => {
    expect(chosenAgent(agents, "analysis")?.kind).toBe("analysis");
    expect(chosenAgent(agents, null)?.kind).toBe("engineer");
    expect(chosenAgent(agents, "gone")?.kind).toBe("engineer");
    expect(chosenAgent([], null)).toBeNull();
  });

  it("shows the chosen project, else the first where one is required, else none", () => {
    const projects = [
      { id: "p1", name: "Docs" },
      { id: "p2", name: "Site" },
    ];
    expect(chosenProject(projects, true, null)?.id).toBe("p1");
    expect(chosenProject(projects, false, null)).toBeNull();
    expect(chosenProject(projects, false, "p2")?.id).toBe("p2");
    expect(chosenProject(projects, true, "")).toBeNull();
    expect(chosenProject(null, true, null)).toBeNull();
  });
});
