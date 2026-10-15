"""The `files` toolset's tools, in a directory on this host, with real
files and real processes: a search of the code answers within its bound
and inside the workspace alone, and a pattern of more than one line is
refused before it runs."""

import json
from pathlib import Path

from unit.platform_tools import called, on_the_host

from acme.om import base
from acme.om.agent_steps.types.header import ToolFailure
from acme.om.base import new_id
from acme.om.context import Role, TenantContext
from acme.om.platform_agents.tools.files import MAX_MATCH_TEXT, SearchCodeImpl
from acme.om.tools.tool import ToolRuntime
from acme.om.tools.types.tool import ToolInput

from contracts.doubles import context
from contracts.factories import make_org
from contracts.tools import HOST_SPEC, failure_of, result_text


async def test_a_search_of_the_code_answers_within_its_bound(tmp_path: Path) -> None:
    ctx = context(Role.SERVICE, make_org())
    tools = on_the_host(tmp_path)
    workspace = await tools.manager.prepare_agent_workspace(ctx, new_id(), HOST_SPEC)
    root = Path(workspace.location)
    (root / "src").mkdir()
    for n in range(30):
        (root / "src" / f"m{n:02}.py").write_text(f"import os\nvalue = 'needle {n}'\n")
    (root / "src" / "long.py").write_text("needle " + "x" * 5_000 + "\n")
    (root / ".git").mkdir()
    (root / ".git" / "config").write_text("needle\n")
    (root / "blob.bin").write_bytes(b"needle\x00\n")
    search = SearchCodeImpl()
    response = await called(tools, search, ctx, workspace, pattern="needle", limit=5)
    answer = json.loads(result_text(response))
    assert len(answer["matches"]) == 5 and answer["more"] is True
    response = await called(tools, search, ctx, workspace, pattern="needle", path="src", limit=100)
    answer = json.loads(result_text(response))
    assert answer["more"] is False and len(answer["matches"]) == 31
    paths = {match["path"] for match in answer["matches"]}
    assert all(path.startswith("src/") for path in paths), "never .git, never a binary file"
    assert max(len(match["text"]) for match in answer["matches"]) == MAX_MATCH_TEXT
    response = await called(tools, search, ctx, workspace, pattern="needle 1[0-9]'$")
    answer = json.loads(result_text(response))
    assert sorted((m["path"], m["line"]) for m in answer["matches"]) == [
        (f"src/m{n}.py", 2) for n in range(10, 20)
    ]
    # The bound holds on bytes too: a flood of long lines is read only to
    # the output's bound, and the answer still holds its limit.
    for n in range(300):
        (root / "src" / f"wide{n:03}.py").write_text(("needle " + "y" * 2_000 + "\n") * 3)
    response = await called(tools, search, ctx, workspace, pattern="needle y", limit=100)
    answer = json.loads(result_text(response))
    assert len(answer["matches"]) == 100 and answer["more"] is True
    assert len(result_text(response)) < 50_000, "within what the model reads of one output"
    # No match is an empty answer; a pattern grep cannot read is the model's.
    response = await called(tools, search, ctx, workspace, pattern="haystack")
    assert json.loads(result_text(response)) == {"matches": [], "more": False}
    response = await called(tools, search, ctx, workspace, pattern="needle (")
    assert failure_of(response) is ToolFailure.PERMANENT


async def test_a_search_of_the_code_reads_inside_the_workspace_alone(tmp_path: Path) -> None:
    ctx = context(Role.SERVICE, make_org())
    tools = on_the_host(tmp_path)
    workspace = await tools.manager.prepare_agent_workspace(ctx, new_id(), HOST_SPEC)
    (Path(workspace.location) / "kept.py").write_text("needle inside\n")
    (tmp_path / "beside.txt").write_text("needle outside\n")
    search = SearchCodeImpl()
    for path in ("..", "../..", "../../beside.txt", "src/../..", "/", str(tmp_path), "a\x00b"):
        response = await called(tools, search, ctx, workspace, pattern="needle", path=path)
        assert failure_of(response) is ToolFailure.INVALID_INPUT, path
    response = await called(tools, search, ctx, workspace, pattern="needle")
    answer = json.loads(result_text(response))
    assert [m["path"] for m in answer["matches"]] == ["kept.py"]


async def test_a_search_of_one_file_answers_its_matching_line(tmp_path: Path) -> None:
    ctx = context(Role.SERVICE, make_org())
    tools = on_the_host(tmp_path)
    workspace = await tools.manager.prepare_agent_workspace(ctx, new_id(), HOST_SPEC)
    (Path(workspace.location) / "src").mkdir()
    (Path(workspace.location) / "src" / "cart.py").write_text("import os\nvalue = 'needle'\n")
    search = SearchCodeImpl()
    response = await called(tools, search, ctx, workspace, pattern="needle", path="src/cart.py")
    assert json.loads(result_text(response)) == {
        "matches": [{"path": "src/cart.py", "line": 2, "text": "value = 'needle'"}],
        "more": False,
    }


class WatchedSearch(SearchCodeImpl):
    """The search, counting the times it runs."""

    def __init__(self) -> None:
        self.runs = 0

    async def run(
        self, ctx: TenantContext, call_input: ToolInput, runtime: ToolRuntime
    ) -> base.Platform:
        self.runs += 1
        return await super().run(ctx, call_input, runtime)


async def test_a_pattern_of_more_than_one_line_is_refused_before_it_runs(
    tmp_path: Path,
) -> None:
    ctx = context(Role.SERVICE, make_org())
    tools = on_the_host(tmp_path)
    workspace = await tools.manager.prepare_agent_workspace(ctx, new_id(), HOST_SPEC)
    (Path(workspace.location) / "kept.py").write_text("needle\nhaystack\n")
    search = WatchedSearch()
    for pattern in ("needle\n", "needle\r", "\nneedle", "needle\r\nhay"):
        response = await called(tools, search, ctx, workspace, pattern=pattern)
        assert failure_of(response) is ToolFailure.INVALID_INPUT, pattern
    assert search.runs == 0
    response = await called(tools, search, ctx, workspace, pattern="needle")
    assert [m["text"] for m in json.loads(result_text(response))["matches"]] == ["needle"]
    assert search.runs == 1
