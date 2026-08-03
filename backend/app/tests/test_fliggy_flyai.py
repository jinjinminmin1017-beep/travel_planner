from __future__ import annotations

import json
import os
import subprocess
from datetime import date, datetime, timezone
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
from app.data_sources.runtime_health import RuntimeCircuitOpenError, RuntimeHealthRegistry, runtime_health_registry
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
    runtime_health_registry.reset()
    yield
    _COMMAND_CACHE.clear()
    _IN_FLIGHT.clear()
    _LAST_CALL_AT.clear()
    runtime_health_registry.reset()


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


@pytest.mark.skipif(os.name != "nt", reason="Windows shim resolution is Windows-specific")
def test_cli_resolves_certified_windows_runtime_without_using_shell():
    project_root = Path(__file__).resolve().parents[3]
    shim = project_root / "node_modules" / ".bin" / "flyai.cmd"
    bundle = project_root / "node_modules" / "@fly-ai" / "flyai-cli" / "dist" / "flyai-bundle.cjs"
    calls: list[dict] = []

    def runner(argv, **kwargs):
        calls.append({"argv": argv, **kwargs})
        return subprocess.CompletedProcess(
            argv,
            0,
            stdout=json.dumps({"status": 0, "message": "success", "systemMessage": "", "data": {"itemList": []}}),
            stderr="",
        )

    client = FlyAIClient(
        api_key="secret",
        executable=str(shim.with_suffix("")),
        timeout_seconds=3,
        runner=runner,
    )
    client.search_train(origin="上海", destination="北京", departure_date=date(2026, 8, 20))

    assert client.executable == str(shim)
    assert calls[0]["argv"][1:3] == ["--single-threaded", str(bundle)]
    assert calls[0]["shell"] is False


def test_cli_rejects_uncertified_locked_bundle(tmp_path):
    node_modules = tmp_path / "node_modules"
    shim = node_modules / ".bin" / ("flyai.cmd" if os.name == "nt" else "flyai")
    shim.parent.mkdir(parents=True)
    shim.write_text("", encoding="utf-8")
    package_root = node_modules / "@fly-ai" / "flyai-cli"
    (package_root / "dist").mkdir(parents=True)
    (package_root / "package.json").write_text(json.dumps({"version": "1.0.16"}), encoding="utf-8")
    (package_root / "dist" / "flyai-bundle.cjs").write_text("uncertified", encoding="utf-8")

    with pytest.raises(FlyAIClientError) as error:
        FlyAIClient(api_key="secret", executable=str(shim), timeout_seconds=3)

    assert error.value.code == "FLIGGY_RUNTIME_NOT_CERTIFIED"


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


def test_cli_classifies_fatal_exit_and_short_circuits_cross_family_calls():
    monotonic_now = [0.0]
    wall_clock_now = [datetime(2026, 8, 3, tzinfo=timezone.utc)]
    registry = RuntimeHealthRegistry(
        monotonic=lambda: monotonic_now[0],
        wall_clock=lambda: wall_clock_now[0],
    )
    calls = 0
    success_payload = {"status": 0, "message": "success", "systemMessage": "", "data": {"itemList": []}}

    def runner(argv, **_kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            return subprocess.CompletedProcess(
                argv,
                3221226505,
                stdout=json.dumps(success_payload),
                stderr="Assertion failed: !(handle->flags & UV_HANDLE_CLOSING), file src\\win\\async.c",
            )
        return subprocess.CompletedProcess(argv, 0, stdout=json.dumps(success_payload), stderr="")

    client = FlyAIClient(
        api_key="secret",
        executable="flyai",
        timeout_seconds=3,
        runner=runner,
        runtime_registry=registry,
    )
    with pytest.raises(FlyAIClientError) as fatal_error:
        client.search_flight(origin="上海", destination="北京", departure_date=date(2026, 8, 20), non_stop=True)
    assert fatal_error.value.code == "FLIGGY_FATAL_PROCESS_EXIT"
    assert fatal_error.value.failure_kind == "FATAL_PROCESS_EXIT"

    with pytest.raises(FlyAIClientError) as circuit_error:
        client.search_train(origin="上海虹桥", destination="北京南", departure_date=date(2026, 8, 20))
    assert circuit_error.value.code == "FLIGGY_CIRCUIT_OPEN"
    assert calls == 1
    assert registry.snapshot("fliggy_flyai").circuit_state == "OPEN"  # type: ignore[union-attr]

    monotonic_now[0] = 31.0
    wall_clock_now[0] = datetime(2026, 8, 3, 0, 1, tzinfo=timezone.utc)
    client.search_train(origin="上海虹桥", destination="北京南", departure_date=date(2026, 8, 20))
    recovered = registry.snapshot("fliggy_flyai")
    assert calls == 2
    assert recovered is not None and recovered.circuit_state == "CLOSED"
    assert recovered.last_success_at == wall_clock_now[0]


def test_runtime_registry_allows_only_one_half_open_probe_and_uses_distinct_thresholds():
    monotonic_now = [0.0]
    registry = RuntimeHealthRegistry(monotonic=lambda: monotonic_now[0])
    registry.record_failure(
        "fliggy_flyai",
        failure_kind="FATAL_PROCESS_EXIT",
        error_code="FLIGGY_FATAL_PROCESS_EXIT",
        retryable=True,
        latency_ms=10,
    )
    monotonic_now[0] = 31.0
    registry.before_call("fliggy_flyai")
    with pytest.raises(RuntimeCircuitOpenError):
        registry.before_call("fliggy_flyai")

    timeout_registry = RuntimeHealthRegistry(monotonic=lambda: monotonic_now[0])
    for _ in range(2):
        timeout_registry.record_failure(
            "fliggy_flyai",
            failure_kind="TIMEOUT",
            error_code="FLIGGY_TIMEOUT",
            retryable=True,
            latency_ms=30_000,
        )
    assert timeout_registry.snapshot("fliggy_flyai").circuit_state == "CLOSED"  # type: ignore[union-attr]
    timeout_registry.record_failure(
        "fliggy_flyai",
        failure_kind="TIMEOUT",
        error_code="FLIGGY_TIMEOUT",
        retryable=True,
        latency_ms=30_000,
    )
    assert timeout_registry.snapshot("fliggy_flyai").circuit_state == "OPEN"  # type: ignore[union-attr]


def test_cli_classifies_timeout_and_invalid_json_without_exposing_output():
    def timeout_runner(argv, **_kwargs):
        raise subprocess.TimeoutExpired(argv, 3)

    timeout_client = FlyAIClient(api_key="secret", executable="flyai", timeout_seconds=3, runner=timeout_runner)
    with pytest.raises(FlyAIClientError) as timeout_error:
        timeout_client.search_train(origin="上海", destination="北京", departure_date=date(2026, 8, 20))
    assert timeout_error.value.code == "FLIGGY_TIMEOUT"
    assert timeout_error.value.failure_kind == "TIMEOUT"

    runtime_health_registry.reset()

    def invalid_runner(argv, **_kwargs):
        return subprocess.CompletedProcess(argv, 0, stdout="not-json-sensitive-output", stderr="")

    invalid_client = FlyAIClient(api_key="secret", executable="flyai", timeout_seconds=3, runner=invalid_runner)
    with pytest.raises(FlyAIClientError) as invalid_error:
        invalid_client.search_train(origin="上海", destination="北京", departure_date=date(2026, 8, 20))
    assert invalid_error.value.code == "FLIGGY_INVALID_JSON"
    assert "not-json-sensitive-output" not in str(invalid_error.value)


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
