"""The connectors namespace's types: the views and requests its calls carry, as
consumers import them."""

from acme.client.schema.connectors import (
    ConnectorReviewRequest,
    ConnectorView,
    ListedToolView,
)

__all__ = [
    "ConnectorReviewRequest",
    "ConnectorView",
    "ListedToolView",
]
