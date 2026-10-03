"""GitHub's side of the forge: the check of a delivery's signature, and the
reading of a delivery into the platform's terms. GitHub's own event names
stay here.

GitHub signs a delivery with HMAC-SHA256 of the body under the App's
webhook secret, sent as `sha256=<hex>` in `X-Hub-Signature-256`, and names
its event in `X-GitHub-Event`. It signs no time and no id, so no delivery
is stale, and a delivery's id is the digest of the body it signed: a
redelivery, or a replay of a captured one, is the same key, and no header
outside the signature mints a new one.

A person's account is named by its numeric id, which a rename never moves;
the login is the name it shows. The platform's own account is the App's bot
login, which the client is given. A pull request or an issue is named
`<owner>/<repo>#<number>`, as the platform opens it and as the `comment`
tool names it, and a branch by its bare name. The mark the platform gives
a comment rides in its body as an HTML comment, which GitHub does not
render, and is read back only from a comment the platform's account wrote.

What is read, each into one arrival:

| GitHub event | Arrival |
|---|---|
| `issue_comment` created, `pull_request_review` submitted, `pull_request_review_comment` created | a comment |
| `issues` reopened, or assigned to the platform's account | a ticket |
| `check_suite` completed, `status` finished | a check, passed or failed by the fold |
| `push` to a branch | a push |
| `ping` | acknowledged, never queued |

Any other delivery is refused, and nothing is queued for it."""

import hashlib
import hmac
import json
import re
from collections.abc import Iterable, Mapping
from datetime import datetime
from typing import Any

from pydantic import ValidationError

from acme.integrations.events import Acknowledged, ProvidedEvent, delivery_key
from acme.integrations.exceptions import DeliveryRefused

SIGNATURE_HEADER = "x-hub-signature-256"
EVENT_HEADER = "x-github-event"
FORGE = "forge"

MARK = re.compile(r"<!-- platform-act: ([A-Za-z0-9-]{1,100}) -->")
"""Where a comment the platform posted carries the platform's mark."""

FAILED = frozenset(
    {"failure", "error", "cancelled", "timed_out", "action_required", "stale", "startup_failure"}
)
PASSED = frozenset({"success", "neutral", "skipped"})


def sign(payload: bytes, secret: str) -> str:
    """The `X-Hub-Signature-256` GitHub sends with `payload`."""
    return "sha256=" + hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()


def marked(text: str, mark: str | None) -> str:
    """A comment's body, carrying the platform's mark where one is given."""
    return text if mark is None else f"{text}\n\n<!-- platform-act: {mark} -->"


def checks_state(outcomes: Iterable[str | None]) -> str | None:
    """The fold of GitHub's outcomes of checks on one commit, each a check
    run's or a suite's conclusion or a status's state, into the platform's
    two: `failed` when any failed, `passed` when every one passed, and None
    while one has not finished, or when there is none."""
    seen = list(outcomes)
    if any(outcome in FAILED for outcome in seen):
        return "failed"
    if seen and all(outcome in PASSED for outcome in seen):
        return "passed"
    return None


def verified(payload: bytes, signature: str | None, secret: str) -> dict[str, Any]:
    """The delivery's body, once its signature checks out; `DeliveryRefused`
    otherwise, naming what failed and never the secret."""
    if not signature:
        raise DeliveryRefused("no signature")
    if not signature.startswith("sha256="):
        raise DeliveryRefused("the signature is not sha256=...")
    given = signature.removeprefix("sha256=")
    expected = hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()
    if not given.isascii() or not hmac.compare_digest(given, expected):
        raise DeliveryRefused("the signature did not check out")
    try:
        body = json.loads(payload)
    except json.JSONDecodeError, UnicodeDecodeError:
        raise DeliveryRefused("the body is not JSON") from None
    if not isinstance(body, dict):
        raise DeliveryRefused("the body is not a delivery")
    return body


def read_delivery(
    payload: bytes, headers: Mapping[str, str], secret: str, account: str, now: datetime
) -> ProvidedEvent | Acknowledged:
    """A delivery GitHub sent, checked and read. `account` is the platform's
    own login; `now` dates an event whose body carries no time."""
    body = verified(payload, headers.get(SIGNATURE_HEADER), secret)
    kind = headers.get(EVENT_HEADER, "")
    if kind == "ping":
        return Acknowledged()
    reader = _READERS.get(kind)
    if reader is None:
        raise DeliveryRefused(f"the forge takes no {kind or 'unnamed'} event")
    try:
        fields = reader(body, account)
        installation = str(_obj(body, "installation")["id"])
    except KeyError, TypeError, ValueError, AttributeError:
        raise DeliveryRefused("the body is not an event") from None
    if fields is None:
        action = body.get("action")
        raise DeliveryRefused(f"the forge takes no {kind}{f'.{action}' if action else ''} event")
    delivery_id = "sha256:" + hashlib.sha256(payload).hexdigest()
    try:
        return ProvidedEvent.model_validate(
            {
                "key": delivery_key(FORGE, delivery_id),
                "delivery_id": delivery_id,
                "installation": installation,
                "occurred_at": fields.pop("occurred_at", None) or now,
                **fields,
            }
        )
    except ValidationError:
        raise DeliveryRefused("the body is not an event") from None


def _obj(body: Mapping[str, Any], key: str) -> dict[str, Any]:
    value = body.get(key)
    if not isinstance(value, dict):
        raise KeyError(key)
    return value


def _repository(body: Mapping[str, Any]) -> str:
    """The repository a delivery names, in lower case, as the platform keeps
    it: GitHub compares names without case and sends them as typed."""
    name = _obj(body, "repository")["full_name"]
    if not isinstance(name, str) or not name:
        raise ValueError("no repository")
    return name.lower()


def _author(user: Mapping[str, Any], account: str) -> dict[str, str]:
    """Who wrote it: the platform's account by its login, a bot as GitHub
    types it, and a person otherwise, each by its numeric id."""
    login = str(user["login"])
    if login == account:
        kind = "platform"
    elif user.get("type") == "Bot":
        kind = "bot"
    else:
        kind = "person"
    return {"author_kind": kind, "author_id": str(user["id"]), "author_name": login}


def _comment(
    body: Mapping[str, Any], comment: Mapping[str, Any], number: object, account: str
) -> dict[str, Any]:
    author = _author(_obj(comment, "user"), account)
    text = str(comment.get("body") or "")
    refs = [str(comment["id"])]
    if author["author_kind"] == "platform":
        refs += MARK.findall(text)
    return {
        "arrival": "comment",
        **author,
        "pull_request": f"{_repository(body)}#{int(str(number))}",
        "refs": tuple(refs),
        "text": MARK.sub("", text).strip(),
        "occurred_at": comment.get("created_at"),
    }


def _issue_comment(body: Mapping[str, Any], account: str) -> dict[str, Any] | None:
    if body.get("action") != "created":
        return None
    return _comment(body, _obj(body, "comment"), _obj(body, "issue")["number"], account)


def _review_comment(body: Mapping[str, Any], account: str) -> dict[str, Any] | None:
    if body.get("action") != "created":
        return None
    pull = _obj(body, "pull_request")
    fields = _comment(body, _obj(body, "comment"), pull["number"], account)
    return {**fields, "branch": _obj(pull, "head").get("ref")}


def _review(body: Mapping[str, Any], account: str) -> dict[str, Any] | None:
    if body.get("action") != "submitted":
        return None
    pull, review = _obj(body, "pull_request"), _obj(body, "review")
    text = str(review.get("body") or review.get("state") or "")
    return {
        **_comment(body, {**review, "body": text}, pull["number"], account),
        "branch": _obj(pull, "head").get("ref"),
        "occurred_at": review.get("submitted_at"),
    }


def _issue(body: Mapping[str, Any], account: str) -> dict[str, Any] | None:
    action = body.get("action")
    if action == "assigned":
        if str(_obj(body, "assignee").get("login")) != account:
            return None
    elif action != "reopened":
        return None
    issue = _obj(body, "issue")
    return {
        "arrival": "ticket",
        **_author(_obj(body, "sender"), account),
        "pull_request": f"{_repository(body)}#{int(str(issue['number']))}",
        "refs": (str(issue["id"]),),
        "text": str(issue.get("title") or ""),
        "occurred_at": issue.get("updated_at"),
    }


def _check_suite(body: Mapping[str, Any], account: str) -> dict[str, Any] | None:
    if body.get("action") != "completed":
        return None
    suite = _obj(body, "check_suite")
    state = checks_state([suite.get("conclusion")])
    if state is None:
        return None
    app = _obj(suite, "app")
    pulls = [pull for pull in suite.get("pull_requests") or () if isinstance(pull, dict)]
    return {
        "arrival": "check",
        "check": state,
        "author_kind": "bot",
        "author_id": str(app["id"]),
        "author_name": str(app.get("slug") or app["id"]),
        "pull_request": f"{_repository(body)}#{int(str(pulls[0]['number']))}" if pulls else None,
        "branch": suite.get("head_branch"),
        "refs": (str(suite["head_sha"]),),
        "text": f"{app.get('name') or app.get('slug') or 'a check'}: {suite.get('conclusion')}",
        "occurred_at": suite.get("updated_at"),
    }


def _status(body: Mapping[str, Any], account: str) -> dict[str, Any] | None:
    state = checks_state([body.get("state")])
    if state is None:
        return None
    branches = [b for b in body.get("branches") or () if isinstance(b, dict)]
    context = str(body.get("context") or "a status")
    return {
        "arrival": "check",
        "check": state,
        **_author(_obj(body, "sender"), account),
        "branch": branches[0].get("name") if len(branches) == 1 else None,
        "refs": (str(body["sha"]),),
        "text": f"{context}: {body.get('state')} {body.get('description') or ''}".strip(),
        "occurred_at": body.get("updated_at"),
    }


def _push(body: Mapping[str, Any], account: str) -> dict[str, Any] | None:
    ref = str(body["ref"])
    if not ref.startswith("refs/heads/") or body.get("deleted"):
        return None
    head = body.get("head_commit")
    head = head if isinstance(head, dict) else {}
    return {
        "arrival": "push",
        **_author(_obj(body, "sender"), account),
        "branch": ref.removeprefix("refs/heads/"),
        "refs": (str(body["after"]),),
        "text": str(head.get("message") or ""),
        "occurred_at": head.get("timestamp"),
    }


_READERS = {
    "issue_comment": _issue_comment,
    "pull_request_review_comment": _review_comment,
    "pull_request_review": _review,
    "issues": _issue,
    "check_suite": _check_suite,
    "status": _status,
    "push": _push,
}
