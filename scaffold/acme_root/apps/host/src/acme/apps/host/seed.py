"""The seed of a machine of the platform's cloud pool: the one file the pool
hands the machine as it starts, which the host alone reads. It says where
the platform answers, and holds the one-use key the host trades for its
credential; once traded, the key goes from it."""

import json
import os
from pathlib import Path

from acme.client.claimant.credential import BadSetting


def read_seed(path: Path) -> tuple[str, str | None] | None:
    """Where the platform answers, and the key the machine was handed, from
    the seed the pool wrote; the key is None once the host traded it. None
    when no seed stands there."""
    try:
        raw = json.loads(path.read_text())
    except FileNotFoundError:
        return None
    except (OSError, ValueError) as error:
        raise BadSetting(f"the machine's seed at {path} cannot be read: {error}") from None
    api_url = raw.get("api_url") if isinstance(raw, dict) else None
    key = raw.get("key") if isinstance(raw, dict) else None
    if not isinstance(api_url, str) or not api_url:
        raise BadSetting(f"the machine's seed at {path} names no platform")
    if key is not None and not isinstance(key, str):
        raise BadSetting(f"the machine's seed at {path} holds no key")
    return api_url.rstrip("/"), key or None


def forget_key(path: Path) -> None:
    """The seed without its key, once the host traded it: a key is spent
    once, and the seed still says where the platform answers, for the next
    start of the host in the same boot."""
    seeded = read_seed(path)
    if seeded is None or seeded[1] is None:
        return
    partial = path.with_name(path.name + ".partial")
    partial.write_text(json.dumps({"api_url": seeded[0]}, sort_keys=True))
    os.chmod(partial, 0o600)
    os.replace(partial, path)
