from __future__ import annotations

import json
import subprocess
from datetime import date
from pathlib import Path

import pytest

from app.data_sources.flight_providers import FlightSearchRequest
from app.data_sources.fliggy_flyai_provider import (
    FliggyFlyAIProvider,
    FliggyFlyAIProviderError,
    _COMMAND_CACHE,
    _IN_FLIGHT,
    _LAST_CALL_AT,
)
from app.data_sources.flyai_cli_client import FlyAIClient, FlyAIClientError, FlyAICommandResult
from app.data_sources.rail_providers import RailSearchRequest, _rail_provider_failure_outcome
from app.data_sources.redirect_providers import create_booking_redirect
from app.models.schemas import (
    BookingRedirectRequest,
    PlanType,
    RiskLevel,
    TravelHardConstraints,
    TravelRequest,
)
from app.services.plan_variant_materializer import materialize_rail_plan_variant
from app.services.planner import _attach_offer_redirects, _plan, _rail_segment_from_offer

FIXTURES = Path(__file__).parent / "fixtures"


def _payload(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


class _FixtureClient:
    timeout_seconds = 1.0

    def __init__(self, payload: dict) -> None:
        self.payload = payload
        self.calls = 0

    def _result(self) -> FlyAICommandResult:
        self.calls += 1
        return FlyAICommandResult(
            payload=self.payload,
            response_hash="a" * 64,
            item_count=len(self.payload["data"]["itemList"]),
            elapsed_ms=12,
        )

    def search_flight(self, **_kwargs) -> FlyAICommandResult:
        return self._result()

    def search_train(self, **_kwargs) -> FlyAICommandResult:
        return self._result()


@pytest.fixture(autouse=True)
def _clear_provider_state():
    _COMMAND_CACHE.clear()
    _IN_FLIGHT.clear()
    _LAST_CALL_AT.clear()
    yield
    _COMMAND_CACHE.clear()
    _IN_FLIGHT.clear()
    _LAST_CALL_AT.clear()


def _provider(payload: dict, *, cache_ttl_seconds: int = 60) -> tuple[FliggyFlyAIProvider, _FixtureClient]:
    client = _FixtureClient(payload)
    return (
        FliggyFlyAIProvider(
            client=client,  # type: ignore[arg-type]
            qps_limit=1000,
            cache_ttl_seconds=cache_ttl_seconds,
            redirect_allowed_hosts=("router.feizhu.com", "fliggy.com"),
        ),
        client,
    )


def test_cli_uses_argument_vector_and_child_environment_without_secret_leakage():
    calls: list[dict] = []

    def runner(argv, **kwargs):
        calls.append({"argv": argv, **kwargs})
        stdout = json.dumps({"status": 0, "message": "success", "systemMessage": "", "data": {"itemList": []}})
        return subprocess.CompletedProcess(argv, 0, stdout=stdout, stderr="")

    client = FlyAIClient(
        api_key="formal-test-secret",
        executable="flyai",
        timeout_seconds=3,
        runner=runner,
        base_environment={"PATH": "test-path"},
    )
    client.search_flight(
        origin="Shanghai",
        destination="Qingdao",
        departure_date=date(2026, 8, 20),
        non_stop=True,
    )

    call = calls[0]
    assert call["argv"][:2] == ["flyai", "search-flight"]
    assert "formal-test-secret" not in call["argv"]
    assert call["env"]["FLYAI_API_KEY"] == "formal-test-secret"
    assert call["shell"] is False
    assert call["timeout"] == 3


@pytest.mark.parametrize(
    ("returncode", "stderr", "message", "system_message", "expected_code"),
    [
        (1, "", "success", "", "FLIGGY_NON_ZERO_EXIT"),
        (0, "warning", "success", "", "FLIGGY_STDERR"),
        (0, "", "success", "FlyAI experience mode is active / \u4f53\u9a8c\u6a21\u5f0f", "FLIGGY_EXPERIENCE_MODE"),
        (0, "", "rate limit reached", "", "FLIGGY_RATE_LIMITED"),
    ],
)
def test_cli_fails_closed_on_process_and_experience_mode_signals(returncode, stderr, message, system_message, expected_code):
    payload = {"status": 0, "message": message, "systemMessage": system_message, "data": {"itemList": []}}

    def runner(argv, **_kwargs):
        return subprocess.CompletedProcess(argv, returncode, stdout=json.dumps(payload), stderr=stderr)

    client = FlyAIClient(api_key="secret", executable="flyai", timeout_seconds=3, runner=runner)
    with pytest.raises(FlyAIClientError) as error:
        client.search_train(origin="Shanghai", destination="Beijing", departure_date=date(2026, 8, 20))
    assert error.value.code == expected_code
    assert "secret" not in str(error.value)


def test_flight_provider_parses_direct_and_connecting_items_and_reuses_cache():
    provider, client = _provider(_payload("flyai_flight_success.json"))
    request = FlightSearchRequest(
        origin_iata="SHA",
        destination_iata="TAO",
        origin_city_name="Shanghai",
        destination_city_name="Qingdao",
        departure_date=date(2026, 8, 20),
        max_results=5,
    )

    first = provider.search_offers(request)
    second = provider.search_offers(request)

    assert [offer.total_price.amount_minor for offer in first] == [42050, 53000]
    assert [len(offer.segments) for offer in first] == [1, 2]
    assert first[1].segments[0].destination_iata == first[1].segments[1].origin_iata == "WUH"
    assert first[0].booking_reference and first[0].booking_reference.redirect_url.startswith("https://router.feizhu.com/")
    assert first[0].data_source.source_type == "OTA"
    assert second[0].data_source.cache_metadata and second[0].data_source.cache_metadata.cache_hit is True
    assert client.calls == 1


def test_rail_provider_materializes_only_exact_price_and_returned_seat():
    provider, _client = _provider(_payload("flyai_train_success.json"), cache_ttl_seconds=0)
    offers = provider.search_offers(
        RailSearchRequest(
            train_number="G105",
            origin_station="Shanghai",
            destination_station="Beijing",
            departure_date=date(2026, 8, 20),
        )
    )

    assert len(offers) == 1
    assert offers[0].seat_options[0].price.amount_minor == 33600
    assert offers[0].seat_options[0].seat_type == "Second Class"
    assert offers[0].booking_reference is not None


def test_rail_provider_rejects_masked_price():
    provider, _client = _provider(_payload("flyai_train_masked_price.json"), cache_ttl_seconds=0)
    with pytest.raises(FliggyFlyAIProviderError, match="FLIGGY_PRICE_NOT_EXACT"):
        provider.search_offers(
            RailSearchRequest(
                train_number="G105",
                origin_station="Shanghai",
                destination_station="Beijing",
                departure_date=date(2026, 8, 20),
            )
        )

    outcome = _rail_provider_failure_outcome("fliggy_flyai", FliggyFlyAIProviderError("FLIGGY_PRICE_NOT_EXACT: masked"))
    assert outcome.status == "PRICE_NOT_EXACT"
    assert outcome.error_code == "FLIGGY_PRICE_NOT_EXACT"
    assert outcome.retryable is False


def test_provider_rejects_jump_url_outside_allowlist():
    payload = _payload("flyai_train_success.json")
    payload["data"]["itemList"][0]["jumpUrl"] = "https://evil.example/order"
    provider, _client = _provider(payload, cache_ttl_seconds=0)
    with pytest.raises(FliggyFlyAIProviderError, match="FLIGGY_INVALID_RESPONSE"):
        provider.search_offers(
            RailSearchRequest(
                train_number="G105",
                origin_station="Shanghai",
                destination_station="Beijing",
                departure_date=date(2026, 8, 20),
            )
        )


def test_planner_materializes_plan_bound_fliggy_redirect_from_offer_reference():
    provider, _client = _provider(_payload("flyai_train_success.json"), cache_ttl_seconds=0)
    offer = provider.search_offers(
        RailSearchRequest(
            train_number="G105",
            origin_station="Shanghai",
            destination_station="Beijing",
            departure_date=date(2026, 8, 20),
        )
    )[0]
    segment = _rail_segment_from_offer("seg_flyai_train", offer)
    plan = _plan(
        "plan_flyai_train",
        "FlyAI train",
        PlanType.DIRECT_RAIL,
        [segment],
        8.0,
        RiskLevel.LOW,
        "FlyAI fixture",
        "FlyAI fixture",
    )

    _attach_offer_redirects(plan, [(offer, [segment])])

    assert len(plan.booking_redirects) == 1
    assert plan.booking_redirects[0].redirect_type == "FLIGGY"
    redirect = create_booking_redirect(
        BookingRedirectRequest(
            request_id="req_flyai_redirect",
            idempotency_key="idem_flyai_redirect",
            plan_id=plan.plan_id,
            segment_id=segment.segment_id,
            redirect_type="FLIGGY",
        ),
        plan,
        environment="DEV",
    )
    assert redirect.redirect_id == plan.booking_redirects[0].redirect_id
    assert redirect.url == "https://router.feizhu.com/train/item-001"

    variant = materialize_rail_plan_variant(
        plan,
        TravelRequest.model_construct(preferred_rail_seat=None, hard_constraints=TravelHardConstraints()),
    )[0]
    variant_redirect = create_booking_redirect(
        BookingRedirectRequest(
            request_id="req_flyai_variant_redirect",
            idempotency_key="idem_flyai_variant_redirect",
            plan_id=variant.plan_id,
            segment_id=segment.segment_id,
            redirect_type="FLIGGY",
        ),
        variant,
        environment="DEV",
    )
    assert variant.plan_id != plan.plan_id
    assert variant_redirect.url == "https://router.feizhu.com/train/item-001"
