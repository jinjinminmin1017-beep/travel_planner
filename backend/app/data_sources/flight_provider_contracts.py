from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class AirlinePublicQueryContract:
    """Technical evidence gate for one official-airline query system.

    License approval deliberately does not live in this contract. Once every
    technical prerequisite is verified, the only remaining runtime gate is the
    source ``LICENSE_STATUS`` from environment/configuration.
    """

    source_id: str
    source_name: str
    carrier_codes: tuple[str, ...]
    allowed_hosts: tuple[str, ...]
    contract_version: str
    browser_entry_url: str
    base_url: str
    anonymous_sample_status: str
    request_fields_confirmed: tuple[str, ...]
    response_fields_confirmed: tuple[str, ...]
    endpoint_method: str | None = None
    endpoint_path: str | None = None
    query_parameter_names: tuple[tuple[str, str], ...] = ()
    required_dynamic_material: tuple[str, ...] = ()
    captcha_observed: bool = False
    rate_limit_status: str = "NOT_VERIFIED"
    executable: bool = False
    technical_blocker: str | None = None

    def request_params(self, values: dict[str, object]) -> dict[str, object]:
        mapping = dict(self.query_parameter_names)
        return {wire_name: values[field_name] for field_name, wire_name in mapping.items() if field_name in values}

    @property
    def technical_ready(self) -> bool:
        return self.blocking_reason is None

    @property
    def blocking_reason(self) -> str | None:
        if self.technical_blocker:
            return self.technical_blocker
        if self.anonymous_sample_status != "PASS":
            return f"anonymous query sample status is {self.anonymous_sample_status}"
        if not self.endpoint_method or not self.endpoint_path:
            return "server endpoint method/path is not confirmed"
        if not self.query_parameter_names:
            return "request parameter mapping is not confirmed"
        if not self.response_fields_confirmed:
            return "fare/cabin/availability response fields are not confirmed"
        if self.required_dynamic_material:
            return "required dynamic session material is not reproducible"
        if self.captcha_observed:
            return "CAPTCHA was observed in the anonymous query path"
        if self.rate_limit_status != "VERIFIED":
            return f"rate-limit status is {self.rate_limit_status}"
        if not self.executable:
            return "contract is not marked executable"
        return None


AIRLINE_PUBLIC_QUERY_CONTRACTS: dict[str, AirlinePublicQueryContract] = {
    "airline_mu_public_query": AirlinePublicQueryContract(
        source_id="airline_mu_public_query",
        source_name="China Eastern Official Public Flight Query",
        carrier_codes=("MU", "FM"),
        allowed_hosts=("ceair.com",),
        contract_version="mu-technical-evidence-2026-07-15",
        browser_entry_url="https://www.ceair.com/zh/cny/home",
        base_url="https://www.ceair.com",
        anonymous_sample_status="INCOMPLETE",
        request_fields_confirmed=("origin_iata", "destination_iata", "departure_date", "trip_type"),
        response_fields_confirmed=(),
        technical_blocker="anonymous result, endpoint contract, cabin inventory and rate-limit behavior are not confirmed",
    ),
    "airline_cz_public_query": AirlinePublicQueryContract(
        source_id="airline_cz_public_query",
        source_name="China Southern Official Public Flight Query",
        carrier_codes=("CZ", "OQ"),
        allowed_hosts=("csair.com",),
        contract_version="cz-technical-evidence-2026-07-15",
        browser_entry_url="https://www.csair.com/wa/zh/",
        base_url="https://www.csair.com",
        anonymous_sample_status="PARTIAL",
        request_fields_confirmed=("origin_iata", "destination_iata", "departure_date", "return_date", "adults"),
        response_fields_confirmed=("route", "departure_date", "currency", "calendar_lowest_price"),
        technical_blocker="calendar price was visible but flight-level cabin inventory and a replayable endpoint were not confirmed",
    ),
    "airline_sc_public_query": AirlinePublicQueryContract(
        source_id="airline_sc_public_query",
        source_name="Shandong Airlines Official Public Flight Query",
        carrier_codes=("SC",),
        allowed_hosts=("sda.cn",),
        contract_version="sc-resultsets-evidence-2026-07-15",
        browser_entry_url="https://flights.sda.cn/flight/search/SHA-TAO-260820-100",
        base_url="https://flights.sda.cn",
        anonymous_sample_status="BLOCKED",
        request_fields_confirmed=("cabinClass", "currencyCode", "bounds", "passengerCounts"),
        response_fields_confirmed=("flightSegments", "flightOptions", "fareFamilies", "totalResults"),
        endpoint_method="POST",
        endpoint_path="/tRtApi/flight/resultSets",
        required_dynamic_material=("Device-Id", "Finger_key", "mfaMeta"),
        captcha_observed=True,
        rate_limit_status="HTTP_429_FINGERPRINT_SIGNAL_IDENTIFIED_NOT_SAFELY_REPRODUCED",
        technical_blocker="anonymous browser query stayed loading; direct replay returned COMMON-01-0060 and the official bundle requires fingerprint/risk material",
    ),
    "airline_ca_public_query": AirlinePublicQueryContract(
        source_id="airline_ca_public_query",
        source_name="Air China Official Public Flight Query",
        carrier_codes=("CA",),
        allowed_hosts=("airchina.com.cn",),
        contract_version="ca-entry-evidence-2026-07-15",
        browser_entry_url="https://www.airchina.com.cn",
        base_url="https://www.airchina.com.cn",
        anonymous_sample_status="INCOMPLETE",
        request_fields_confirmed=("origin_iata", "destination_iata", "departure_date", "adults"),
        response_fields_confirmed=(),
        technical_blocker="official booking entry is reachable but the query endpoint and flight inventory response contract are not confirmed",
    ),
    "airline_hna_micro_public_query": AirlinePublicQueryContract(
        source_id="airline_hna_micro_public_query",
        source_name="HNA Micro Official Public Flight Query",
        carrier_codes=("JD", "8L", "UQ", "FU", "Y8"),
        allowed_hosts=("jdair.net",),
        contract_version="hna-micro-security-evidence-2026-07-15",
        browser_entry_url="https://jdair.net/micro/main/flight/search",
        base_url="https://jdair.net",
        anonymous_sample_status="BLOCKED",
        request_fields_confirmed=("origin_iata", "destination_iata", "departure_date", "passengers"),
        response_fields_confirmed=("sta",),
        endpoint_method="POST",
        endpoint_path="/api/flight/query/flight",
        required_dynamic_material=("desc", "PEkingBorn ciphertext"),
        captcha_observed=True,
        rate_limit_status="STA_10000_10001_CHALLENGE_SIGNALS_IDENTIFIED",
        technical_blocker="official security interceptor injects a dynamic desc ciphertext and escalates sta=10000/10001 to CAPTCHA/frequency blocking",
    ),
    "airline_zh_public_query": AirlinePublicQueryContract(
        source_id="airline_zh_public_query",
        source_name="Shenzhen Airlines Official Public Flight Query",
        carrier_codes=("ZH",),
        allowed_hosts=("shenzhenair.com",),
        contract_version="zh-entry-evidence-2026-07-15",
        browser_entry_url="https://www.shenzhenair.com/szair_B2C/",
        base_url="https://www.shenzhenair.com",
        anonymous_sample_status="INCOMPLETE",
        request_fields_confirmed=("origin_iata", "destination_iata", "departure_date", "adults"),
        response_fields_confirmed=(),
        technical_blocker="B2C entry and static assets are reachable but no replayable query/response contract is confirmed",
    ),
    "airline_3u_public_query": AirlinePublicQueryContract(
        source_id="airline_3u_public_query",
        source_name="Sichuan Airlines Official Public Flight Query",
        carrier_codes=("3U",),
        allowed_hosts=("sichuanair.com",),
        contract_version="3u-risk-evidence-2026-07-15",
        browser_entry_url="https://flights.sichuanair.com",
        base_url="https://flights.sichuanair.com",
        anonymous_sample_status="BLOCKED",
        request_fields_confirmed=("origin_iata", "destination_iata", "departure_date", "adults"),
        response_fields_confirmed=(),
        required_dynamic_material=("Dingxiang ConstID",),
        captcha_observed=True,
        rate_limit_status="NOT_VERIFIED",
        technical_blocker="the official flight entry loads Dingxiang CAPTCHA/ConstID before a stable anonymous inventory contract can be established",
    ),
    "airline_9c_public_query": AirlinePublicQueryContract(
        source_id="airline_9c_public_query",
        source_name="Spring Airlines Official Public Flight Query",
        carrier_codes=("9C",),
        allowed_hosts=("ch.com",),
        contract_version="9c-risk-evidence-2026-07-15",
        browser_entry_url="https://flights.ch.com",
        base_url="https://flights.ch.com",
        anonymous_sample_status="BLOCKED",
        request_fields_confirmed=("origin_iata", "destination_iata", "departure_date", "adults"),
        response_fields_confirmed=(),
        required_dynamic_material=("risk-control fingerprint",),
        captcha_observed=True,
        rate_limit_status="NOT_VERIFIED",
        technical_blocker="the official query shell loads Geetest and dedicated safety/risk scripts; an unchallenged inventory response was not confirmed",
    ),
    "airline_ho_public_query": AirlinePublicQueryContract(
        source_id="airline_ho_public_query",
        source_name="Juneyao Airlines Official Public Flight Query",
        carrier_codes=("HO",),
        allowed_hosts=("juneyaoair.com",),
        contract_version="ho-queryflight-evidence-2026-07-15",
        browser_entry_url="https://www.juneyaoair.com/home",
        base_url="https://www.juneyaoair.com",
        anonymous_sample_status="BLOCKED",
        request_fields_confirmed=("RouteType", "FlightDirection", "PassengerType", "SegCondList"),
        response_fields_confirmed=("FlightInfoCombList", "FlightInfoList", "CabinFareCombList", "LowestValueEconomy", "LowestValueFirst"),
        endpoint_method="POST",
        endpoint_path="/server/api/flightFares/queryFlightSimple",
        required_dynamic_material=("blackBox", "anonymous or login credential"),
        captcha_observed=True,
        rate_limit_status="NOT_VERIFIED",
        technical_blocker="two anonymous replays returned INVALID_TOKEN; official client injects blackBox and supports Geetest escalation",
    ),
    "airline_qw_public_query": AirlinePublicQueryContract(
        source_id="airline_qw_public_query",
        source_name="Qingdao Airlines Official Public Flight Query",
        carrier_codes=("QW",),
        allowed_hosts=("qdairlines.com",),
        contract_version="qw-airlist-evidence-2026-07-15",
        browser_entry_url="https://www.qdairlines.com",
        base_url="https://www.qdairlines.com",
        anonymous_sample_status="BLOCKED",
        request_fields_confirmed=("origCode3", "destCode3", "departureDate", "isReturn", "adultNum"),
        response_fields_confirmed=("departAVFS", "flightNo", "departTime", "destTime", "fares", "cabinClasses", "avTkt", "price_ad"),
        endpoint_method="POST",
        endpoint_path="/api/ewp/promotion/sales/v1/air/list",
        required_dynamic_material=("COOKIEID", "RANDOM", "trickToken", "rid", "deviceId"),
        captcha_observed=True,
        rate_limit_status="OFFICIAL_ASSET_TEMPORARILY_UNAVAILABLE_AFTER_REPEATED_ACCESS",
        technical_blocker="query construction requires session-derived trickToken and can require NECaptchaValidate/rid/deviceId; stable anonymous replay was not established",
    ),
}


def airline_public_query_contract(source_id: str) -> AirlinePublicQueryContract | None:
    return AIRLINE_PUBLIC_QUERY_CONTRACTS.get(source_id)


def public_airline_contract_ready(source_id: str) -> bool:
    contract = airline_public_query_contract(source_id)
    return bool(contract and contract.technical_ready)
