from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from datetime import date
from typing import Callable, Literal

from app.data_sources.rail_providers import (
    RailOffer,
    RailProviderSearchResult,
    RailSearchRequest,
    search_rail_offers_with_enabled_provider_result,
)
from app.services.rail_route_search import RailScheduleCandidate, RailScheduleLeg
from app.services.observability import record_rail_inventory_metrics


logger = logging.getLogger("app.rail_inventory_verifier")

RailInventoryStatus = Literal[
    "SCHEDULE_CANDIDATE",
    "AVAILABLE",
    "SOLD_OUT",
    "NOT_ON_SALE",
    "PROVIDER_UNAVAILABLE",
]


@dataclass(frozen=True)
class RailInventoryCandidateResult:
    candidate: RailScheduleCandidate
    status: RailInventoryStatus
    offers: tuple[RailOffer, ...]
    reason_code: str


@dataclass(frozen=True)
class RailInventoryVerificationDiagnostics:
    elapsed_ms: float
    candidate_count: int
    unique_group_count: int
    queried_group_count: int
    external_call_count: int
    budget_exhausted: bool
    available_count: int
    sold_out_count: int
    provider_unavailable_count: int


@dataclass(frozen=True)
class RailInventoryVerificationResult:
    candidates: tuple[RailInventoryCandidateResult, ...]
    diagnostics: RailInventoryVerificationDiagnostics


SearchRailOffers = Callable[[RailSearchRequest, str | None], RailProviderSearchResult]


class RailInventoryVerifier:
    def __init__(
        self,
        search: SearchRailOffers = search_rail_offers_with_enabled_provider_result,
    ) -> None:
        self.search = search

    def verify(
        self,
        candidates: tuple[RailScheduleCandidate, ...],
        *,
        environment: str | None = None,
        max_groups: int = 3,
        total_budget_seconds: float = 90.0,
        departure_tolerance_minutes: int = 15,
    ) -> RailInventoryVerificationResult:
        started = time.monotonic()
        groups = _group_legs(candidates)
        group_results: dict[tuple[date, str, str], RailProviderSearchResult] = {}
        queried = 0
        budget_exhausted = False
        for group_key, _legs in groups.items():
            if queried >= max_groups or time.monotonic() - started >= total_budget_seconds:
                budget_exhausted = True
                break
            service_date, origin_station, destination_station = group_key
            group_results[group_key] = self.search(
                RailSearchRequest(
                    train_number="",
                    origin_station=origin_station,
                    destination_station=destination_station,
                    departure_date=service_date,
                ),
                environment,
            )
            queried += 1
        results: list[RailInventoryCandidateResult] = []
        for candidate in candidates:
            matched_offers: list[RailOffer] = []
            failure_status: RailInventoryStatus | None = None
            failure_code = "SCHEDULE_CANDIDATE"
            for leg in candidate.legs:
                group_key = _leg_group_key(leg)
                group_result = group_results.get(group_key)
                if group_result is None:
                    failure_status = "PROVIDER_UNAVAILABLE"
                    failure_code = "RAIL_INVENTORY_BUDGET_EXHAUSTED"
                    break
                matching = [
                    offer
                    for offer in group_result.offers
                    if _offer_matches_leg(offer, leg, departure_tolerance_minutes)
                ]
                if len(matching) > 1:
                    failure_status = "PROVIDER_UNAVAILABLE"
                    failure_code = "RAIL_INVENTORY_AMBIGUOUS_MATCH"
                    break
                if not matching:
                    if group_result.offers:
                        failure_status = "SOLD_OUT"
                        failure_code = "RAIL_CANDIDATE_NOT_RETURNED"
                    else:
                        failure_status, failure_code = _empty_group_status(group_result)
                    break
                offer = matching[0]
                if not _offer_is_publishable(offer):
                    failure_status = "PROVIDER_UNAVAILABLE"
                    failure_code = "RAIL_INVENTORY_FACT_INCOMPLETE"
                    break
                matched_offers.append(offer)
            if failure_status is None and len(matched_offers) == len(candidate.legs):
                results.append(RailInventoryCandidateResult(candidate, "AVAILABLE", tuple(matched_offers), "RAIL_INVENTORY_VERIFIED"))
            else:
                results.append(
                    RailInventoryCandidateResult(
                        candidate,
                        failure_status or "PROVIDER_UNAVAILABLE",
                        (),
                        failure_code,
                    )
                )
        elapsed_ms = round((time.monotonic() - started) * 1000, 3)
        diagnostics = RailInventoryVerificationDiagnostics(
            elapsed_ms=elapsed_ms,
            candidate_count=len(candidates),
            unique_group_count=len(groups),
            queried_group_count=queried,
            external_call_count=queried,
            budget_exhausted=budget_exhausted,
            available_count=sum(item.status == "AVAILABLE" for item in results),
            sold_out_count=sum(item.status in {"SOLD_OUT", "NOT_ON_SALE"} for item in results),
            provider_unavailable_count=sum(item.status == "PROVIDER_UNAVAILABLE" for item in results),
        )
        record_rail_inventory_metrics(
            elapsed_ms=elapsed_ms,
            queried_group_count=queried,
            external_call_count=queried,
            budget_exhausted=budget_exhausted,
        )
        logger.info(
            "rail_inventory_verification candidate_count=%s unique_group_count=%s queried_group_count=%s external_call_count=%s available_count=%s sold_out_count=%s provider_unavailable_count=%s budget_exhausted=%s elapsed_ms=%s",
            diagnostics.candidate_count,
            diagnostics.unique_group_count,
            diagnostics.queried_group_count,
            diagnostics.external_call_count,
            diagnostics.available_count,
            diagnostics.sold_out_count,
            diagnostics.provider_unavailable_count,
            diagnostics.budget_exhausted,
            diagnostics.elapsed_ms,
        )
        return RailInventoryVerificationResult(tuple(results), diagnostics)


def _group_legs(candidates: tuple[RailScheduleCandidate, ...]) -> dict[tuple[date, str, str], list[RailScheduleLeg]]:
    groups: dict[tuple[date, str, str], list[RailScheduleLeg]] = {}
    seen: set[tuple[str, str, str]] = set()
    for candidate in candidates:
        for leg in candidate.legs:
            identity = (leg.service_id, leg.origin_station_code, leg.destination_station_code)
            if identity in seen:
                continue
            seen.add(identity)
            groups.setdefault(_leg_group_key(leg), []).append(leg)
    return groups


def _leg_group_key(leg: RailScheduleLeg) -> tuple[date, str, str]:
    return (leg.service_date, leg.origin_station_name, leg.destination_station_name)


def _offer_matches_leg(offer: RailOffer, leg: RailScheduleLeg, tolerance_minutes: int) -> bool:
    if offer.train_number.strip().upper() != leg.train_number.strip().upper():
        return False
    if _normalize_station(offer.origin_station) != _normalize_station(leg.origin_station_name):
        return False
    if _normalize_station(offer.destination_station) != _normalize_station(leg.destination_station_name):
        return False
    if offer.departure_at.date() != leg.departure_at.date():
        return False
    difference = abs(int((offer.departure_at - leg.departure_at).total_seconds() // 60))
    return difference <= tolerance_minutes


def _offer_is_publishable(offer: RailOffer) -> bool:
    if offer.booking_reference is None:
        return False
    if not offer.seat_options:
        return False
    return any(
        seat.availability in {"AVAILABLE", "LIMITED"}
        and seat.price.amount_minor > 0
        and not seat.price.is_estimated
        for seat in offer.seat_options
    )


def _empty_group_status(result: RailProviderSearchResult) -> tuple[RailInventoryStatus, str]:
    if any(outcome.status == "EMPTY" and "sale" in outcome.message.lower() for outcome in result.outcomes):
        return "NOT_ON_SALE", "RAIL_INVENTORY_NOT_ON_SALE"
    if result.outcomes and all(outcome.status == "EMPTY" for outcome in result.outcomes):
        return "SOLD_OUT", "RAIL_INVENTORY_EMPTY"
    return "PROVIDER_UNAVAILABLE", "RAIL_INVENTORY_PROVIDER_UNAVAILABLE"


def _normalize_station(value: str) -> str:
    return value.strip().removesuffix("站").replace(" ", "").lower()
