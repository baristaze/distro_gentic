"""The `code` toolset's tools, in a directory on this host, with real
files and real processes: the software engineer's edit changes exactly
the one place it names, and an edit that is not one place is refused and
changes nothing."""

import json
from pathlib import Path

from contracts.doubles import context
from contracts.factories import make_org
from contracts.tools import HOST_SPEC, failure_of, result_text
from unit.platform_tools import called, on_the_host, unbound

from acme.om.base import new_id
from acme.om.context import Role
from acme.om.platform_agents.tools.code import MAX_EDIT, EditFileImpl
from acme.om.steps.types.header import ToolFailure

SOURCE = (
    "def total(cart):\n"
    "    tax = 0\n"
    "    return sum(cart) + tax\n"
    "\n"
    "\n"
    "def count(cart):\n"
    "    tax = 0\n"
    "    return len(cart)\n"
)


async def test_an_edit_changes_exactly_the_place_it_names(tmp_path: Path) -> None:
    ctx = context(Role.SERVICE, make_org())
    tools = on_the_host(tmp_path)
    workspace = await tools.manager.prepare_workspace(ctx, new_id(), HOST_SPEC)
    cart = Path(workspace.location) / "cart.py"
    cart.write_text(SOURCE)
    edit = EditFileImpl(unbound)  # pyright: ignore[reportArgumentType]
    # One exact match: that place changes, and every other byte stays.
    response = await called(
        tools,
        edit,
        ctx,
        workspace,
        path="cart.py",
        old_text="sum(cart) + tax",
        new_text="sum(cart) + tax + 1",
    )
    assert failure_of(response) is None, result_text(response)
    assert cart.read_text() == SOURCE.replace("sum(cart) + tax", "sum(cart) + tax + 1")
    assert json.loads(result_text(response))["line"] == 3
    # A line range: those lines and no other, the last one's end kept.
    before = cart.read_text().splitlines(keepends=True)
    response = await called(
        tools,
        edit,
        ctx,
        workspace,
        path="cart.py",
        start_line=7,
        end_line=8,
        new_text="    return len(cart) or 0",
    )
    assert failure_of(response) is None, result_text(response)
    assert cart.read_text() == "".join([*before[:6], "    return len(cart) or 0\n"])
    assert json.loads(result_text(response)) | {"size": 0} == {
        "path": "cart.py",
        "line": 7,
        "lines": 1,
        "size": 0,
    }
    # A file whose lines end in CRLF keeps them.
    windows = Path(workspace.location) / "notes.txt"
    windows.write_bytes(b"one\r\ntwo\r\nthree\r\n")
    response = await called(
        tools, edit, ctx, workspace, path="notes.txt", start_line=2, end_line=2, new_text="2"
    )
    assert failure_of(response) is None, result_text(response)
    assert windows.read_bytes() == b"one\r\n2\r\nthree\r\n"


async def test_an_edit_that_is_not_one_place_is_refused_and_changes_nothing(
    tmp_path: Path,
) -> None:
    ctx = context(Role.SERVICE, make_org())
    tools = on_the_host(tmp_path)
    workspace = await tools.manager.prepare_workspace(ctx, new_id(), HOST_SPEC)
    root = Path(workspace.location)
    (root / "cart.py").write_text(SOURCE)
    (root / "aaa.txt").write_text("aaa\n")
    (root / "blob.bin").write_bytes(b"\xff\xfe tax = 0\n")
    (root / "big.txt").write_text("tax = 0\n" + "x" * MAX_EDIT)
    outside = tmp_path / "outside.py"
    outside.write_text(SOURCE)
    names = ("cart.py", "aaa.txt", "blob.bin", "big.txt")
    files = {path: path.read_bytes() for path in (*(root / name for name in names), outside)}
    edit = EditFileImpl(unbound)  # pyright: ignore[reportArgumentType]
    refused = (
        # Two places, then two overlapping ones: the edit lands on neither.
        ({"path": "cart.py", "old_text": "    tax = 0\n"}, "matches 2 places"),
        ({"path": "aaa.txt", "old_text": "aa"}, "matches 2 places"),
        ({"path": "cart.py", "old_text": "    tax = 1\n"}, "matches no place"),
        ({"path": "cart.py", "start_line": 8, "end_line": 9}, "has 8 lines"),
        # Not text, or past the bound: never written back cut or mangled.
        ({"path": "blob.bin", "old_text": "tax = 0"}, "not UTF-8 text"),
        ({"path": "big.txt", "old_text": "tax = 0"}, "past the"),
    )
    for change, why in refused:
        response = await called(tools, edit, ctx, workspace, new_text="tax = 2", **change)
        assert failure_of(response) is ToolFailure.PERMANENT, change
        assert why in result_text(response), result_text(response)
    # A call that names both places, or neither, or a range backwards, and a
    # path out of the workspace, is refused before anything is read.
    for change in (
        {"path": "cart.py", "old_text": "tax", "start_line": 2, "end_line": 2},
        {"path": "cart.py"},
        {"path": "cart.py", "start_line": 3, "end_line": 2},
        {"path": "cart.py", "start_line": 3},
        {"path": "../../outside.py", "old_text": "    return len(cart)\n"},
        {"path": str(outside), "old_text": "    return len(cart)\n"},
    ):
        response = await called(tools, edit, ctx, workspace, new_text="tax = 2", **change)
        assert failure_of(response) is ToolFailure.INVALID_INPUT, change
    assert {path: path.read_bytes() for path in files} == files
