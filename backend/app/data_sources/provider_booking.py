from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class ProviderBookingReference:
    source_id: str
    redirect_url: str
    item_fingerprint: str
    fetched_at: datetime
