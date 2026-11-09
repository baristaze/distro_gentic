"""The film: the page's frames as the run goes, and the GIF made of
them.

The run is long where the stack works and short where the person acts,
so the GIF does not play it at its own pace. Where the screen changes it
plays faster than the run did; a screen that does not change stays a
moment at most; and each beat the drive marks holds long enough to read.
"""

from __future__ import annotations

import asyncio
import subprocess
import time
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from playwright.async_api import Page

VIEW = {"width": 1280, "height": 800}
"""The page's size: the chat and the left bar both read at a scale of 1."""
FPS = 10
"""Frames a second of the GIF."""
SPEED = 2.5
"""How much faster than the run the GIF plays where the screen changes."""
IDLE = 0.4
"""The longest a screen that does not change stays, in seconds of the GIF."""
HOLD = 1.6
"""The pause on each beat, in seconds of the GIF, so a reader reads it."""
EVERY = 0.1
"""Seconds between two frames taken, at least."""
SETTLE = 0.4
"""Seconds a beat waits for what just changed to ease in before its frame."""


class Film:
    """The page's frames, each taken by the drive's side as the run goes
    and stamped with when it was taken, and the beats the drive marks, on
    the same clock. A frame the same as the one before is not kept, so a
    still screen leaves a gap the GIF cuts short. A frame taken while the
    film is paused is left out: the person setting out their view, such as
    hiding a pane, is no part of the scene."""

    def __init__(self, folder: Path) -> None:
        self.folder = folder
        self.frames: list[tuple[float, Path]] = []
        self.beats: list[tuple[float, str]] = []
        self.paused: list[tuple[float, float]] = []
        self.rolling = False
        self.camera: asyncio.Task[None] | None = None

    async def roll(self, page: Page) -> None:
        self.rolling = True
        self.camera = asyncio.create_task(self.shoot(page))

    async def shoot(self, page: Page) -> None:
        """A frame every EVERY seconds at most, until the film is cut."""
        last = b""
        while self.rolling:
            at = time.time()
            try:
                shot = await page.screenshot(type="png")
            except Exception:
                # A page between two documents has no frame to give.
                shot = last
            if shot != last:
                path = self.folder / f"{len(self.frames):05d}.png"
                path.write_bytes(shot)
                # Stamped when it came back: what it shows was on screen by
                # then, and a beat's pause never shows what came after it.
                self.frames.append((time.time(), path))
                last = shot
            await asyncio.sleep(max(0.0, EVERY - (time.time() - at)))

    async def beat(self, page: Page, name: str) -> None:
        """A beat, its pause held on a frame taken now: the state the drive
        just saw, whatever the camera last kept."""
        # What just changed eases in first, such as a toast.
        await page.wait_for_timeout(SETTLE * 1000)
        shot = await page.screenshot(type="png")
        at = time.time()
        path = self.folder / f"beat-{len(self.beats):02d}.png"
        path.write_bytes(shot)
        self.frames.append((at, path))
        self.beats.append((at, name))

    def pause(self) -> None:
        self.paused.append((time.time(), float("inf")))

    def resume(self) -> None:
        began, _ = self.paused[-1]
        self.paused[-1] = (began, time.time())

    async def cut(self) -> None:
        self.rolling = False
        if self.camera is not None:
            await self.camera

    def log(self, path: Path) -> None:
        """Each frame and each beat, on the one clock, in order."""
        rows = [(at, path.name) for at, path in self.frames] + [(at, f"beat: {name}") for at, name in self.beats]
        path.write_text("".join(f"{at:.3f}\t{what}\n" for at, what in sorted(rows)))

    def timeline(self) -> tuple[list[tuple[Path, float]], list[tuple[float, str]]]:
        """Each frame the GIF shows and for how long, and when each beat
        comes in it: the run played SPEED times faster, a still screen cut
        to IDLE, and a pause of HOLD on each beat."""
        holds = sorted(self.beats)
        frames = sorted((at, path) for at, path in self.frames if not any(began <= at < ended for began, ended in self.paused))
        shown: list[tuple[float, Path]] = []
        now = 0.0
        marks: list[tuple[float, str]] = []
        last = holds[-1][0] if holds else 0.0
        for (at, path), following in zip(frames, [*frames[1:], None], strict=True):
            shown.append((now, path))
            # The last frame stays past the last beat, so its pause is kept.
            until = following[0] if following else max(at + IDLE * SPEED, last + 0.01)
            now += min((until - at) / SPEED, IDLE)
            # A beat pauses on the frame taken for it.
            while holds and holds[0][0] < until:
                marks.append((now, holds.pop(0)[1]))
                now += HOLD
        sampled: list[tuple[Path, float]] = []
        step = 1 / FPS
        at = 0
        for n in range(round(now * FPS) + 1):
            when = n * step
            while at + 1 < len(shown) and shown[at + 1][0] <= when:
                at += 1
            path = shown[at][1]
            if sampled and sampled[-1][0] == path:
                sampled[-1] = (path, sampled[-1][1] + step)
            else:
                sampled.append((path, step))
        return sampled, marks


def join(timeline: list[tuple[Path, float]], gif: Path) -> None:
    """The frames as one looping GIF, on a palette made for them."""
    listing = gif.with_suffix(".txt")
    lines = [f"file '{path}'\nduration {seconds:.2f}" for path, seconds in timeline]
    listing.write_text("\n".join([*lines, f"file '{timeline[-1][0]}'"]) + "\n")
    graph = (
        "split[a][b];[a]palettegen=max_colors=128:stats_mode=diff[p];"
        "[b][p]paletteuse=dither=bayer:bayer_scale=4:diff_mode=rectangle"
    )
    command = ["ffmpeg", "-v", "error", "-y", "-f", "concat", "-safe", "0", "-i", str(listing)]
    subprocess.run([*command, "-vf", graph, "-fps_mode", "vfr", "-loop", "0", str(gif)], check=True)
