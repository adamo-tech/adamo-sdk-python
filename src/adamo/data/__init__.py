"""adamo.data — download and query recorded training data."""
from __future__ import annotations

from adamo._auth import API_BASE, STORE_BASE
from adamo.data.client import DataClient
from adamo.data.dataset import AdamoDataset
from adamo.data.models import Frame, Record, SessionMetadata, VideoIndex


def connect(
    *,
    api_key: str,
    api_url: str = API_BASE,
    store_url: str = STORE_BASE,
) -> DataClient:
    """Create a :class:`DataClient` for querying recorded session data.

    Args:
        api_key: An Adamo API key (``ak_...``).
        api_url: Override the Adamo API base URL (for token exchange).
        store_url: Override the Adamo store URL.

    Returns:
        A connected :class:`DataClient`.
    """
    return DataClient(api_key, api_url=api_url, store_url=store_url)


__all__ = [
    "AdamoDataset",
    "DataClient",
    "Frame",
    "Record",
    "SessionMetadata",
    "VideoIndex",
    "connect",
]
