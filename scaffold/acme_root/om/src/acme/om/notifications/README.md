# Notifications

Who is told that a parked session waits on them. This is one of the kinds
of thing [Acme is made of](../../../../README.md).

## What it holds

- **Notification**: one person told, on one channel, that a session's
  park waits on them, with the one action that clears it and its link.
  A post through an integration names what served it, so a twin's post
  is never taken for the real system's.

## What can happen

- **Notify a park.** A run that parks on what only a person clears tells
  exactly the people who may clear it, once a park:

  | Park | Action | Who |
  |---|---|---|
  | A call held for approval | Decide the call | The members the tenant's policy lets decide its class |
  | A budget a person must raise | Raise the budget | The members who set budgets |
  | The account's funds | Top up | The members who set budgets |
  | A call far above its session's norm | Approve the call | The members who approve such calls |
  | A key the org holds none of | Save the key | The members who save the org's keys |
  | The org's own account at a model provider, or a permission its key lacks | Fix it at the provider | The members who manage the org |
  | A question the agent asks its person | Answer it with a message | Its requester, or the members who manage the tenant when the requester holds no place |
  | Any other park on a person | Answer the session | The same people |

  Each is told on every channel of theirs: the platform's own list, and
  each account of theirs an integration holds
  ([intake](../intake/README.md)). A park that clears by itself, at its
  retry time, tells nobody, and so does a price only the operator sets.
  A fix at a model provider is the one park with a retry time that
  tells: no try goes through until an admin of the org makes it.
- **Read** your own notifications, newest first, and **mark one read**.
  Nobody reads or marks another person's.

## The rules

- **Exactly the people who can clear it.** Nobody else hears of a park,
  and nobody who can clear it is left out.
- **One action, one link.** A notification names the one action that
  clears its park and links to its route in the API: the call's
  decision, the session's messages, the session's controls, the
  budget's amount, a call's approval past its norm, or the provider's
  key. Topping up and a fix at a model provider are made outside the
  API: their notifications name the park and carry no link.
- **A question is quoted, never a link in it.** A question's
  notification quotes it on one line, cut short and escaped. One that
  holds a URL, an image, or an element that loads one is not quoted: the
  person reads it in the session.
- **Once a park.** A park tells each person once on each channel, however
  often it is asked. A park that tries again by itself is one park across
  its tries, until a call is answered or its loop ends.
- **A channel that is down leaves the list.** A post an integration
  cannot make now is left out; the platform's own list still tells them.
- **Every row belongs to one org,** and goes with the org.

<!-- agents-only
The table of parks is `rules.py`. A notification's id is derived from the
`parked` step that wrote the park (for a park with a retry time, the one
that wrote its first try, `rules.first_try`), the action, the link, the
recipient, and the channel (`rules.notification_id`). The session runner calls
`notify_park` after each run that ends parked (`LoopHandlerImpl`).
-->

## How another namespace composes it

The session runner tells after each run that parks. It reads the
tenant's members from [tenancy](../tenancy/README.md), a held call's
approvers from the [tools](../tools/README.md) policy, and a person's
accounts from [intake](../intake/README.md).
