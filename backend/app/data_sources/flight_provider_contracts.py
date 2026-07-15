from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class AirlinePublicQueryContract:
    """Source-specific evidence gate for an official-airline query adapter.

    A browser-visible result is evidence that the public journey works.  It is
    not evidence that an undocumented HTTP endpoint may be called by a server.
    ``executable`` therefore remains false until both the transport contract and
    the terms approval are recorded for the individual airline.
    """

    source_id: str
    contract_version: str
    browser_entry_url: str
    browser_sample_status: str
    request_fields_confirmed: tuple[str, ...]
    response_fields_confirmed: tuple[str, ...]
    endpoint_method: str | None = None
    endpoint_path: str | None = None
    query_parameter_names: tuple[tuple[str, str], ...] = ()
    captcha_observed: bool = False
    rate_limit_verified: bool = False
    terms_status: str = "PENDING_REVIEW"
    executable: bool = False

    def request_params(self, values: dict[str, object]) -> dict[str, object]:
        mapping = dict(self.query_parameter_names)
        return {wire_name: values[field_name] for field_name, wire_name in mapping.items() if field_name in values}

    @property
    def blocking_reason(self) -> str | None:
        if self.terms_status != "APPROVED":
            return f"terms status is {self.terms_status}"
        if not self.endpoint_method or not self.endpoint_path:
            return "server endpoint method/path is not confirmed"
        if not self.query_parameter_names:
            return "request parameter mapping is not confirmed"
        if not self.rate_limit_verified:
            return "rate-limit behavior is not verified"
        if not self.executable:
            return "contract is not marked executable"
        return None


AIRLINE_PUBLIC_QUERY_CONTRACTS: dict[str, AirlinePublicQueryContract] = {
    "airline_mu_public_query": AirlinePublicQueryContract(
        source_id="airline_mu_public_query",
        contract_version="mu-browser-evidence-2026-07-15",
        browser_entry_url="https://www.ceair.com/zh/cny/home",
        browser_sample_status="FORM_REACHABLE_SUBMIT_NO_RESULT",
        request_fields_confirmed=("origin_iata", "destination_iata", "departure_date", "trip_type"),
        response_fields_confirmed=(),
    ),
    "airline_cz_public_query": AirlinePublicQueryContract(
        source_id="airline_cz_public_query",
        contract_version="cz-browser-evidence-2026-07-15",
        browser_entry_url="https://www.csair.com/wa/zh/",
        browser_sample_status="VISIBLE_CALENDAR_LOWEST_PRICE",
        request_fields_confirmed=("origin_iata", "destination_iata", "departure_date", "return_date", "adults"),
        response_fields_confirmed=("route", "departure_date", "currency", "calendar_lowest_price"),
    ),
    "airline_sc_public_query": AirlinePublicQueryContract(
        source_id="airline_sc_public_query",
        contract_version="sc-browser-evidence-2026-07-15",
        browser_entry_url="https://flights.sda.cn/flight/lowPrice",
        browser_sample_status="VISIBLE_LOW_PRICE_LIST",
        request_fields_confirmed=("origin_city", "destination_city", "date_range"),
        response_fields_confirmed=("origin_city", "destination_city", "departure_date", "currency", "price", "discount"),
    ),
}


def airline_public_query_contract(source_id: str) -> AirlinePublicQueryContract | None:
    return AIRLINE_PUBLIC_QUERY_CONTRACTS.get(source_id)


def public_airline_contract_ready(source_id: str) -> bool:
    contract = airline_public_query_contract(source_id)
    return bool(contract and contract.blocking_reason is None)
