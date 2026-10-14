"""The `files` toolset: list, read, and search the files of a session's
workspace. Each reaches the workspace only through the call's runtime, and
a search of the code runs there, bounded in its matches and its bytes,
never in the platform's process."""

from datetime import timedelta
from pathlib import PurePosixPath

from pydantic import Field, field_validator

from acme.om.base import Platform
from acme.om.context import TenantContext
from acme.om.exceptions import (
    ToolFailed,
)
from acme.om.platform_agents import kinds, rules
from acme.om.platform_agents.tools.base import (
    MAX_PATH,
    MAX_READ,
    NO_NUL,
    ONE_LINE,
    NativeToolImpl,
    Text,
)
from acme.om.steps.types.header import ToolFailure
from acme.om.tools.tool import ToolRuntime
from acme.om.tools.types.tool import Effect, ToolClass, ToolInput, ToolMode, ToolSpec

# The most matches one search of the code answers, each cut at its width:
# the whole answer stays inside what the model reads of one output.
MAX_MATCHES = 100
MAX_MATCH_TEXT = 200
MAX_SEARCH_OUTPUT = 400_000  # characters of the search's output it reads, at most


class PathInput(ToolInput):
    path: str = Field(default=".", min_length=1, max_length=MAX_PATH)


class Entry(Platform):
    path: str
    is_dir: bool
    size: int


class Entries(Platform):
    entries: tuple[Entry, ...]


class ListFilesImpl(NativeToolImpl):
    SPEC = ToolSpec(
        name=kinds.LIST_FILES,
        description="Lists the files under a path of the workspace, at most 500.",
        input_model=PathInput,
        output_model=Entries,
        timeout=timedelta(seconds=30),
        authorization_class=ToolClass.READ,
        effect=Effect.READ_ONLY,
        interruptible=True,
        mode=ToolMode.SYNC,
    )

    async def run(
        self, ctx: TenantContext, call_input: ToolInput, runtime: ToolRuntime
    ) -> Platform:
        assert isinstance(call_input, PathInput)
        found = await runtime.list_files(call_input.path, 500)
        return Entries(
            entries=tuple(Entry(path=e.path, is_dir=e.is_dir, size=e.size) for e in found)
        )


class ReadFileImpl(NativeToolImpl):
    SPEC = ToolSpec(
        name=kinds.READ_FILE,
        description="Reads a text file of the workspace, its first 200,000 bytes.",
        input_model=PathInput,
        output_model=Text,
        timeout=timedelta(seconds=30),
        authorization_class=ToolClass.READ,
        effect=Effect.READ_ONLY,
        interruptible=True,
        mode=ToolMode.SYNC,
    )

    async def run(
        self, ctx: TenantContext, call_input: ToolInput, runtime: ToolRuntime
    ) -> Platform:
        assert isinstance(call_input, PathInput)
        data = await runtime.read_file(call_input.path, MAX_READ)
        return Text(text=data.decode(errors="replace"))


class SearchCodeInput(ToolInput):
    pattern: str = Field(min_length=1, max_length=500, pattern=ONE_LINE)
    path: str = Field(default=".", min_length=1, max_length=MAX_PATH, pattern=NO_NUL)
    limit: int = Field(default=50, ge=1, le=MAX_MATCHES)

    @field_validator("path")
    @classmethod
    def _inside(cls, path: str) -> str:
        relative = PurePosixPath(path)
        if relative.is_absolute() or ".." in relative.parts:
            raise ValueError("a path inside the workspace: never absolute, never through ..")
        return path


class Match(Platform):
    path: str
    line: int
    text: str


class Matches(Platform):
    matches: tuple[Match, ...]
    more: bool  # matches past the bound were left out


class SearchCodeImpl(NativeToolImpl):
    """Searches the files under a path of the workspace for a pattern, with
    the workspace's own grep, through the transport: wherever the session's
    workspace runs, never in the platform's process. Each file answers at
    most the limit, the answer at most the limit in all, each line cut at
    its width, and the output read at most its bound, so a search never
    floods the model's window. A path is the workspace's, never absolute
    and never climbing out."""

    SPEC = ToolSpec(
        name=kinds.SEARCH_CODE,
        description=(
            "Searches the text files under a path of the workspace, the whole of it by "
            "default, for an extended regular expression. Answers each matching line with "
            "its file and its line number, at most limit of them, each cut at 200 "
            "characters, and whether more were left out: narrow the pattern or the path "
            "when they were."
        ),
        input_model=SearchCodeInput,
        output_model=Matches,
        timeout=timedelta(seconds=60),
        authorization_class=ToolClass.READ,
        effect=Effect.READ_ONLY,
        interruptible=True,
        mode=ToolMode.SYNC,
    )

    async def run(
        self, ctx: TenantContext, call_input: ToolInput, runtime: ToolRuntime
    ) -> Platform:
        assert isinstance(call_input, SearchCodeInput)
        argv = (
            "grep",
            "-r",
            "-n",
            "-I",
            "-E",
            "--null",
            # Named on every match: grep names none when its path is one file.
            "--with-filename",
            f"--max-count={call_input.limit}",
            "--exclude-dir=.git",
            "-e",
            call_input.pattern,
            "--",
            call_input.path,
        )
        result = await runtime.run(argv, max_output=MAX_SEARCH_OUTPUT)
        found, more = rules.matches_of(result.stdout, call_input.limit, MAX_MATCH_TEXT)
        if result.exit_code not in (0, 1) and not found:
            # Two: a pattern grep cannot read, or a path that is not there.
            said = result.stderr.strip()[:500] or f"the search ended with {result.exit_code}"
            raise ToolFailed(ToolFailure.PERMANENT, said)
        return Matches(
            matches=tuple(Match(path=p, line=n, text=t) for p, n, t in found),
            more=more or result.truncated,
        )
