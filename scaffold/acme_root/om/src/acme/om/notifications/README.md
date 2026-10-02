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
  | Any other park on a person | Answer the session | Its requester, or the members who manage the tenant when the requester holds no place |

  Each is told on every channel of theirs: the platform's own list, and
  each account of theirs an integration holds
  ([intake](../intake/README.md)). A park that clears by itself, at its
  retry time, tells nobody, and so does a price only the operator sets.
- **Read** your own notifications, newest first.

## The rules

- **Exactly the people who can clear it.** Nobody else hears of a park,
  and nobody who can clear it is left out.
- **One action, one link.** A notification names the one action that
  clears its park and links to it.
- **Once a park.** A park tells each person once on each channel, however
  often it is asked.
- **A channel that is down leaves the list.** A post an integration
  cannot make now is left out; the platform's own list still tells them.
- **Every row belongs to one org,** and goes with the org.

<!-- agents-only
The table of parks is `rules.py`. A notification's id is derived from the
`parked` step that wrote the park, the action, the link, the recipient,
and the channel (`rules.notification_id`). The session runner calls
`notify_park` after each run that ends parked (`LoopHandlerImpl`).
-->

## How another namespace composes it

The session runner tells after each run that parks. It reads the
tenant's members from [tenancy](../tenancy/README.md), a held call's
approvers from the [tools](../tools/README.md) policy, and a person's
accounts from [intake](../intake/README.md).
