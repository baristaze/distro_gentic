"""The recorder: the portal of a copy of the scaffold, driven through the
scene (`scene.py`) in headless Chromium, and recorded into tree.gif.

    make demo-gif DEMO_COPY=<copy>

It starts the scene's processes on the copy (`stack.py`), writes the
scene's repository, and has the copy's `portal_check.py scene` write its
agent project's policy. It then acts as the person does: it signs in
from the local mint, types the prompt, opens the sub-agent that asks and
answers it, folds the tree in the left bar, and approves what the lead
holds. It writes nothing through the platform's storage.

Every request the page makes must stay on the portal's own origin, which
forwards the API: any other is aborted. A page error, a console error,
or a request off the origin fails the recording, and so does a GIF of 6
MB or more; the GIF is written only when none happened. Each beat's time
in the GIF is printed, so a frame can be cut at each.
"""

import argparse
import asyncio
import contextlib
import json
import re
import shutil
import sys
import tempfile
from pathlib import Path
from urllib.parse import urlparse

from playwright.async_api import (
    BrowserContext,
    ConsoleMessage,
    Locator,
    Page,
    Route,
    async_playwright,
    expect,
)
from playwright.async_api import TimeoutError as PlaywrightTimeout

import scene
from film import VIEW, Film, join
from stack import Copy, Stack, owner_address

HERE = Path(__file__).resolve().parent
GIF = HERE / "tree.gif"
LIMIT = 6_000_000
"""Bytes the GIF stays under, so the front page loads it at once."""
WAIT = 120_000
"""Milliseconds a state may take to show: the runner takes one loop at a time."""
TYPING = 70
"""Milliseconds between the keys the person types."""
READ = 900
"""Milliseconds the person reads a beat before they act on it."""
BAR = 380
"""The left bar's width, wide enough that a sub-agent's row reads whole."""


async def signed_in(stack: Stack, context: BrowserContext, email: str, org: str) -> None:
    """The owner's auth session, from a login the local mint issues, put
    where the portal keeps it before the page loads."""
    kebab = stack.copy.kebab
    printed = stack.run("uv", "run", "--package", f"{kebab}-api", f"{kebab}-api", "mint-local-login", "--email", email)
    login = next(line for line in printed.splitlines() if line.startswith("lgn_"))
    headers = {"Authorization": f"Bearer {login}", "X-App": "portal", "X-App-Version": "portal@demo"}
    places = await context.request.get("/v1/auth/memberships?limit=100", headers=headers)
    place = next(item for item in (await places.json())["items"] if item["org"]["name"] == org)
    issued = await context.request.post("/v1/auth/sessions", headers=headers, data={"org_id": place["org"]["id"]})
    session = await issued.json()
    sessions = await context.request.get(
        "/v1/agent-sessions?among=mine&limit=1", headers={"Authorization": f"Bearer {session['token']}", "X-App": "portal"}
    )
    if not sessions.ok:
        raise SystemExit(f"the API refused to list the sessions: {sessions.status}")
    if (await sessions.json()).get("items"):
        raise SystemExit(f"{org} holds a session already: the demo plays on a fresh seed (README.md, Run)")
    stored = json.dumps({"state": {"token": session["token"], "orgSlug": session["org"]["slug"]}, "version": 0})
    key = f"{kebab}.portal.authSession"
    await context.add_init_script(
        f"try {{ if (sessionStorage.getItem({json.dumps(key)}) === null) "
        f"sessionStorage.setItem({json.dumps(key)}, {json.dumps(stored)}); }} catch (e) {{}}"
    )


async def chat_wide(page: Page, film: Film) -> None:
    """The session's pane hidden for this session, so the chat and the
    left bar fill the frame: the person setting out their view, which the
    film leaves out. A pane the person hid stays hidden when a tab would
    open itself."""
    film.pause()
    try:
        hide = page.get_by_role("button", name="Hide the panel")
        show = page.get_by_role("button", name="Show the panel")
        # The pane may open itself at any moment: whichever button shows
        # is the one to press, until the person has hidden it once.
        for _ in range(20):
            if await hide.is_visible():
                await hide.click()
                break
            with contextlib.suppress(PlaywrightTimeout):
                await show.click(timeout=1_000)
        else:
            raise RuntimeError("the session's pane would not hide")
        await expect(hide).to_have_count(0)
        await page.mouse.move(VIEW["width"] - 4, VIEW["height"] // 2)
        await page.wait_for_timeout(400)
    finally:
        film.resume()


async def into_view(target: Locator) -> None:
    """The person scrolls the chat until `target` heads it."""
    await target.evaluate("element => element.scrollIntoView({block: 'start'})")


async def to_end(chat: Locator) -> None:
    """The person scrolls the chat to its latest entry, where it follows
    what comes."""
    await chat.evaluate("list => { const box = list.parentElement; box.scrollTop = box.scrollHeight; }")


async def drive(page: Page, film: Film) -> None:
    """The scene, as the person plays it. Each beat waits for the state the
    stack wrote; the runner takes one loop at a time, so the script's turns
    go where the scene wrote them."""

    async def beat(name: str) -> None:
        # The person reads before they act, so the beat's pause shows it.
        await film.beat(page, name)
        await page.wait_for_timeout(READ)

    def session(title: str) -> Locator:
        return page.get_by_role("heading", level=1, name=title)

    def row_in_bar(title: str) -> Locator:
        return bar.get_by_role("link", name=re.compile(re.escape(title))).first

    bar = page.get_by_role("complementary", name="Sidebar")
    chat = page.get_by_role("list", name="Timeline")
    toasts = page.get_by_role("region", name="Sessions that need you")
    await expect(page.get_by_role("heading", level=1, name="Home")).to_be_attached(timeout=WAIT)
    # A wider left bar, so a sub-agent's row reads whole.
    film.pause()
    splitter = await page.get_by_label("Resize the sidebar").bounding_box()
    assert splitter is not None
    middle = splitter["y"] + splitter["height"] / 2
    await page.mouse.move(splitter["x"] + splitter["width"] / 2, middle)
    await page.mouse.down()
    await page.mouse.move(BAR, middle, steps=8)
    await page.mouse.up()
    await page.mouse.move(VIEW["width"] - 4, VIEW["height"] // 2)
    await page.wait_for_timeout(400)
    film.resume()

    # 1. On Home, the person asks the software engineer.
    await page.get_by_role("button", name=re.compile("^Agent project:")).click()
    await page.get_by_role("menuitemradio", name="First agent project").click()
    await page.keyboard.press("Escape")
    prompt = page.get_by_role("textbox", name="Prompt")
    await prompt.click()
    await prompt.press_sequentially(scene.PROMPT, delay=TYPING)
    await page.get_by_role("button", name="Send", exact=True).click()
    await expect(session(scene.PROMPT)).to_be_visible(timeout=WAIT)
    await chat_wide(page, film)
    await beat("the prompt sent")

    # 2. One answer starts four: a card with a row for each, which follows
    # its sub-agent, and the four nested under the lead in the left bar.
    card = chat.get_by_role("region", name="Started 4 sub-agents")

    def row(title: str) -> Locator:
        return card.get_by_role("listitem").filter(has_text=title)

    await expect(card.get_by_role("listitem")).to_have_count(4, timeout=WAIT)
    # The last two start once the first two have run: each says so on its
    # row and in the left bar before the card is read.
    for title in (scene.AGREE, scene.INVOICE):
        await expect(row(title)).to_have_attribute("data-phase", "working", timeout=WAIT)
        await expect(row_in_bar(title)).to_contain_text("Starting", timeout=WAIT)
    await into_view(card)
    await beat("the card with four rows")

    await expect(row(scene.CALLERS)).to_have_attribute("data-phase", "needs_you", timeout=WAIT)
    await expect(toasts).to_contain_text(scene.CALLERS, timeout=WAIT)
    await into_view(card)
    await beat("a sub-agent needs its person")

    # 3. The third starts a sub-agent of its own: the person opens it and
    # watches its own report come in.
    await expect(bar.get_by_role("list", name=f"Sub-agents of {scene.AGREE}")).to_contain_text(scene.TEST, timeout=WAIT)
    await row_in_bar(scene.AGREE).click()
    await expect(session(scene.AGREE)).to_be_visible(timeout=WAIT)
    await chat_wide(page, film)
    await expect(chat.get_by_role("region", name="Started a sub-agent")).to_be_visible(timeout=WAIT)
    await beat("a sub-agent starts its own")
    await expect(chat.get_by_role("region", name=f"Report from {scene.TEST}")).to_be_visible(timeout=WAIT)
    await expect(chat).to_contain_text("They agree", timeout=WAIT)
    await to_end(chat)
    await beat("its own reports to it, and it reports")

    # 4. Back to the lead, which waits on the one that asks; the person
    # opens it from its toast and answers in its chat.
    await row_in_bar(scene.PROMPT).click()
    await expect(session(scene.PROMPT)).to_be_visible(timeout=WAIT)
    await expect(chat).to_contain_text("I wait on the caller check", timeout=WAIT)
    await to_end(chat)
    await beat("the lead waits on the one that asks")
    await toasts.get_by_role("button", name="Open", exact=True).click()
    await expect(session(scene.CALLERS)).to_be_visible(timeout=WAIT)
    await chat_wide(page, film)
    answer = page.get_by_role("textbox", name="Answer")
    await answer.click()
    await answer.press_sequentially(scene.ANSWER, delay=TYPING)
    await page.get_by_role("button", name="Send", exact=True).click()
    await expect(chat).to_contain_text(scene.ANSWER, timeout=WAIT)
    await beat("the person answers")
    await expect(chat).to_contain_text("as you said", timeout=WAIT)
    await to_end(chat)
    await beat("it reports")

    # 5. The lead: every row closed, its roll-up, the tree folded, its own
    # work approved, and its result.
    await row_in_bar(scene.PROMPT).click()
    await expect(session(scene.PROMPT)).to_be_visible(timeout=WAIT)
    for title in (scene.PARSE, scene.CALLERS, scene.AGREE, scene.INVOICE):
        await expect(row(title)).to_have_attribute("data-phase", "done", timeout=WAIT)
    await into_view(card)
    await beat("every row closed")
    rollup = chat.get_by_role("listitem").filter(has_text="All four reported").last
    await expect(rollup).to_be_visible(timeout=WAIT)
    await into_view(rollup)
    await beat("the roll-up")

    async def approve() -> None:
        held = chat.get_by_role("region", name="Action required")
        await expect(held).to_be_visible(timeout=WAIT)
        await to_end(chat)
        await beat("an approval")
        await held.get_by_role("button", name="Approve", exact=True).click()
        await expect(held).to_have_count(0, timeout=WAIT)
        await page.mouse.move(VIEW["width"] - 4, VIEW["height"] // 2)

    await approve()
    # The left bar reads a tree's sub-agents while it works or waits, so the
    # person folds them now, before the lead's own work ends the tree.
    await bar.get_by_role("button", name=f"Fold the sub-agents of {scene.PROMPT}").click()
    await expect(bar.get_by_role("list", name=f"Sub-agents of {scene.PROMPT}")).to_have_count(0)
    await expect(row_in_bar(scene.PROMPT)).to_contain_text("4 sub-agents")
    await page.mouse.move(VIEW["width"] - 4, VIEW["height"] // 2)
    await to_end(chat)
    await beat("the left bar folded")
    await approve()
    result = chat.get_by_role("region", name="Result")
    await expect(result).to_contain_text("claims succeeded", timeout=WAIT)
    await expect(chat.get_by_role("status")).to_have_text("Done", timeout=WAIT)
    await to_end(chat)
    await beat("the result")
    await page.wait_for_timeout(1000)


async def record(stack: Stack, frames: Path) -> tuple[Film, list[str]]:
    copy = stack.copy
    faults: list[str] = []
    origin = urlparse(stack.portal).netloc

    def inside(url: str) -> bool:
        parts = urlparse(url)
        return parts.scheme in ("http", "https", "ws", "wss") and parts.netloc == origin

    async def guard(route: Route) -> None:
        if inside(route.request.url):
            await route.continue_()
        else:
            faults.append(f"a request off the portal's origin: {route.request.url}")
            await route.abort()

    def console(message: ConsoleMessage) -> None:
        if message.type == "error":
            faults.append(f"a console error: {message.text}")

    film = Film(frames)
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch()
        context = await browser.new_context(viewport=VIEW, device_scale_factor=1, base_url=stack.portal, color_scheme="light")
        await context.route("**/*", guard)
        await signed_in(stack, context, owner_address(copy), copy.setting("SEED_ORG", "Ajax"))
        page = await context.new_page()
        page.on("console", console)
        page.on("pageerror", lambda error: faults.append(f"a page error: {error}"))
        page.on(
            "websocket", lambda socket: None if inside(socket.url) else faults.append(f"a socket off the origin: {socket.url}")
        )
        await page.goto("/")
        await film.roll(page)
        try:
            await drive(page, film)
        except Exception as error:
            faults.append(f"the drive stopped: {error}")
            await page.screenshot(path=str(stack.folder / "stopped.png"))
        await film.cut()
        await browser.close()
    return film, list(dict.fromkeys(faults))


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else None)
    parser.add_argument("--copy", type=Path, required=True, help="a rendered copy whose stack is up")
    parser.add_argument("--portal-port", type=int, default=5173, help="the port the portal's dev server takes")
    parser.add_argument("--keep", type=Path, help="a folder to keep the run in: its logs, script, and frames")
    args = parser.parse_args(argv)
    copy = Copy(args.copy.resolve())
    with tempfile.TemporaryDirectory() as temporary:
        folder = args.keep.resolve() if args.keep else Path(temporary)
        frames = folder / "frames"
        frames.mkdir(parents=True, exist_ok=True)
        stack = Stack(copy, folder, args.portal_port)
        try:
            stack.prepare(copy.setting("SEED_SLUG", "ajax"))
            stack.start()
            film, faults = asyncio.run(record(stack, frames))
        finally:
            stack.stop()
        film.log(folder / "film.tsv")
        for fault in faults:
            print(f"failed: {fault}")
        if faults:
            print(f"the run's logs: {folder}" if args.keep else "keep the run's logs with --keep <folder>")
            return 1
        timeline, marks = film.timeline()
        made = folder / "tree.gif"
        join(timeline, made)
        size = made.stat().st_size
        length = sum(seconds for _, seconds in timeline)
        print(f"{len(film.frames)} frames taken, {len(timeline)} shown: {length:.1f} s, {size / 1e6:.2f} MB")
        for at, name in marks:
            print(f"beat at {at:5.1f} s: {name}")
        if size >= LIMIT:
            print(f"failed: the GIF weighs {size / 1e6:.2f} MB, at or above {LIMIT / 1e6:.0f} MB")
            return 1
        shutil.copyfile(made, GIF)
    print(f"wrote {GIF}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
