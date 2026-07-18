from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Iterable, TypeVar

from app.data_sources.config_loader import (
    ADAPTER_SETTINGS_MODELS,
    CredentialedHttpSourceSettings,
    DataSourceConfigurationError,
    DataSourceSettings,
    FlightSourceSettings,
    HttpSourceSettings,
    NominatimSourceSettings,
    RailSourceSettings,
    RealLlmSourceSettings,
    load_data_source_settings,
    secret_value,
)
from app.data_sources.rate_limiter import RateLimitedHttpClient
from app.models.schemas import DataSourceMetadata, now_timepoint

ProviderFactory = Callable[[DataSourceSettings], object | None]
SettingsT = TypeVar("SettingsT", bound=DataSourceSettings)


@dataclass(frozen=True)
class AdapterRegistration:
    settings_model: type[DataSourceSettings]
    provider_factory: ProviderFactory


@dataclass(frozen=True)
class InternalSourceHandle:
    source_id: str


def _metadata(settings: DataSourceSettings) -> DataSourceMetadata:
    return DataSourceMetadata(
        source_id=settings.source_id,
        source_name=settings.source_name,
        source_type=settings.source_type,
        authority_level=settings.authority_level,
        license_status=settings.license_status,
        commercial_allowed=settings.commercial_allowed,
        fetched_at=now_timepoint(),
        cacheable=False,
    )


def _internal_factory(settings: DataSourceSettings) -> object:
    return InternalSourceHandle(settings.source_id)


def _amap_route_factory(settings: DataSourceSettings) -> object:
    from app.data_sources.map_providers import AmapRouteProvider

    typed = _require_type(settings, CredentialedHttpSourceSettings)
    return AmapRouteProvider(
        secret_value(typed.api_key) or "",
        client=_rate_limited_client(typed),
        base_url=typed.base_url or "",
        timeout_seconds=typed.timeout_seconds,
    )


def _baidu_route_factory(settings: DataSourceSettings) -> object:
    from app.data_sources.map_providers import BaiduDirectionLiteProvider

    typed = _require_type(settings, CredentialedHttpSourceSettings)
    return BaiduDirectionLiteProvider(
        secret_value(typed.api_key) or "",
        client=_rate_limited_client(typed),
        base_url=typed.base_url or "",
        timeout_seconds=typed.timeout_seconds,
    )


def _amap_geocode_factory(settings: DataSourceSettings) -> object:
    from app.data_sources.geocoding_providers import AmapAddressGeocodingProvider

    typed = _require_type(settings, CredentialedHttpSourceSettings)
    return AmapAddressGeocodingProvider(
        secret_value(typed.api_key) or "",
        client=_rate_limited_client(typed),
        base_url=typed.base_url or "",
        timeout_seconds=typed.timeout_seconds,
    )


def _amap_place_factory(settings: DataSourceSettings) -> object:
    from app.data_sources.geocoding_providers import AmapPlaceSearchProvider

    typed = _require_type(settings, CredentialedHttpSourceSettings)
    return AmapPlaceSearchProvider(
        secret_value(typed.api_key) or "",
        client=_rate_limited_client(typed),
        base_url=typed.base_url or "",
        timeout_seconds=typed.timeout_seconds,
    )


def _osrm_factory(settings: DataSourceSettings) -> object:
    from app.data_sources.map_providers import OsrmRouteProvider

    typed = _require_type(settings, HttpSourceSettings)
    return OsrmRouteProvider(
        client=_rate_limited_client(typed),
        base_url=typed.base_url or "",
        timeout_seconds=typed.timeout_seconds,
    )


def _nominatim_factory(settings: DataSourceSettings) -> object:
    from app.data_sources.geocoding_providers import NominatimGeocodingProvider

    typed = _require_type(settings, NominatimSourceSettings)
    return NominatimGeocodingProvider(
        client=_rate_limited_client(typed),
        base_url=typed.base_url or "",
        user_agent=typed.user_agent or "",
        timeout_seconds=typed.timeout_seconds,
    )


def _redirect_factory(settings: DataSourceSettings) -> object:
    from app.data_sources.redirect_providers import (
        AirlineOfficialRedirectProvider,
        AmapUriRedirectProvider,
        BaiduUriRedirectProvider,
        Rail12306RedirectProvider,
    )

    providers = {
        "amap_uri_redirect": AmapUriRedirectProvider,
        "baidu_uri_redirect": BaiduUriRedirectProvider,
        "airline_official_redirect": AirlineOfficialRedirectProvider,
        "rail_12306_redirect": Rail12306RedirectProvider,
    }
    provider = providers.get(settings.source_id)
    if provider is None:
        raise DataSourceConfigurationError(f"{settings.source_id}: adapter implementation is missing")
    return provider(_metadata(settings))


def _opensky_factory(settings: DataSourceSettings) -> object:
    from app.data_sources.flight_providers import OpenSkyStatesProvider

    typed = _require_type(settings, HttpSourceSettings)
    return OpenSkyStatesProvider(
        client=_rate_limited_client(typed),
        base_url=typed.base_url or "",
        timeout_seconds=typed.timeout_seconds,
    )


def _spring_airlines_factory(settings: DataSourceSettings) -> object:
    from app.data_sources.flight_providers import SpringAirlinesPublicQueryProvider

    typed = _require_type(settings, FlightSourceSettings)
    return SpringAirlinesPublicQueryProvider(
        client=_rate_limited_client(typed),
        base_url=typed.base_url or "",
        user_agent=typed.user_agent or "",
        cache_ttl_seconds=typed.cache_ttl_seconds,
        allowed_hosts=typed.allowed_hosts,
        timeout_seconds=typed.timeout_seconds,
    )


def _hainan_airlines_factory(settings: DataSourceSettings) -> object:
    from app.data_sources.flight_providers import HainanAirlinesPublicQueryProvider

    typed = _require_type(settings, FlightSourceSettings)
    return HainanAirlinesPublicQueryProvider(
        client=_rate_limited_client(typed, follow_redirects=True),
        base_url=typed.base_url or "",
        user_agent=typed.user_agent or "",
        cache_ttl_seconds=typed.cache_ttl_seconds,
        allowed_hosts=typed.allowed_hosts,
        timeout_seconds=typed.timeout_seconds,
    )


def _qingdao_airlines_factory(settings: DataSourceSettings) -> object:
    from app.data_sources.flight_providers import QingdaoAirlinesPublicQueryProvider

    typed = _require_type(settings, FlightSourceSettings)
    return QingdaoAirlinesPublicQueryProvider(
        client=_rate_limited_client(typed),
        base_url=typed.base_url or "",
        user_agent=typed.user_agent or "",
        cache_ttl_seconds=typed.cache_ttl_seconds,
        allowed_hosts=typed.allowed_hosts,
        timeout_seconds=typed.timeout_seconds,
    )


def _weather_factory(settings: DataSourceSettings) -> object:
    from app.data_sources.weather_providers import OpenMeteoForecastProvider

    typed = _require_type(settings, HttpSourceSettings)
    return OpenMeteoForecastProvider(
        client=_rate_limited_client(typed),
        base_url=typed.base_url or "",
        timeout_seconds=typed.timeout_seconds,
    )


def _rail_factory(settings: DataSourceSettings) -> object:
    from app.data_sources.rail_providers import Official12306RailProvider

    typed = _require_type(settings, RailSourceSettings)
    return Official12306RailProvider(
        client=_rate_limited_client(
            typed,
            min_interval_seconds=typed.min_interval_seconds,
            follow_redirects=True,
        ),
        base_url=typed.base_url or "",
        user_agent=typed.user_agent or "",
        cache_ttl_seconds=typed.cache_ttl_seconds,
        timeout_seconds=typed.timeout_seconds,
    )


def _llm_factory(settings: DataSourceSettings) -> object:
    from app.data_sources.llm_providers import DEFAULT_REAL_LLM_MAX_TOKENS, OpenAICompatibleLLMProvider

    typed = _require_type(settings, RealLlmSourceSettings)
    return OpenAICompatibleLLMProvider(
        api_key=secret_value(typed.api_key) or "",
        model=typed.model or "",
        client=_rate_limited_client(typed),
        base_url=typed.base_url or "",
        timeout_seconds=typed.timeout_seconds,
        max_tokens=typed.max_tokens or DEFAULT_REAL_LLM_MAX_TOKENS,
        thinking_disabled=typed.thinking_disabled,
    )


ADAPTER_REGISTRY: dict[str, AdapterRegistration] = {
    "internal_calculation": AdapterRegistration(ADAPTER_SETTINGS_MODELS["internal_calculation"], _internal_factory),
    "amap_route": AdapterRegistration(ADAPTER_SETTINGS_MODELS["amap_route"], _amap_route_factory),
    "baidu_map_route": AdapterRegistration(ADAPTER_SETTINGS_MODELS["baidu_map_route"], _baidu_route_factory),
    "amap_geocode": AdapterRegistration(ADAPTER_SETTINGS_MODELS["amap_geocode"], _amap_geocode_factory),
    "amap_place_search": AdapterRegistration(ADAPTER_SETTINGS_MODELS["amap_place_search"], _amap_place_factory),
    "osrm_route": AdapterRegistration(ADAPTER_SETTINGS_MODELS["osrm_route"], _osrm_factory),
    "nominatim_geocode": AdapterRegistration(ADAPTER_SETTINGS_MODELS["nominatim_geocode"], _nominatim_factory),
    "amap_uri_redirect": AdapterRegistration(ADAPTER_SETTINGS_MODELS["amap_uri_redirect"], _redirect_factory),
    "baidu_uri_redirect": AdapterRegistration(ADAPTER_SETTINGS_MODELS["baidu_uri_redirect"], _redirect_factory),
    "opensky_states": AdapterRegistration(ADAPTER_SETTINGS_MODELS["opensky_states"], _opensky_factory),
    "open_meteo_forecast": AdapterRegistration(ADAPTER_SETTINGS_MODELS["open_meteo_forecast"], _weather_factory),
    "airline_official_redirect": AdapterRegistration(
        ADAPTER_SETTINGS_MODELS["airline_official_redirect"], _redirect_factory
    ),
    "spring_airlines_public_query": AdapterRegistration(
        ADAPTER_SETTINGS_MODELS["spring_airlines_public_query"], _spring_airlines_factory
    ),
    "hainan_airlines_public_query": AdapterRegistration(
        ADAPTER_SETTINGS_MODELS["hainan_airlines_public_query"], _hainan_airlines_factory
    ),
    "qingdao_airlines_public_query": AdapterRegistration(
        ADAPTER_SETTINGS_MODELS["qingdao_airlines_public_query"], _qingdao_airlines_factory
    ),
    "rail_12306_redirect": AdapterRegistration(ADAPTER_SETTINGS_MODELS["rail_12306_redirect"], _redirect_factory),
    "rail_12306_public_query": AdapterRegistration(
        ADAPTER_SETTINGS_MODELS["rail_12306_public_query"], _rail_factory
    ),
    "real_llm": AdapterRegistration(ADAPTER_SETTINGS_MODELS["real_llm"], _llm_factory),
}


def _rate_limited_client(
    settings: HttpSourceSettings,
    *,
    min_interval_seconds: float | None = None,
    follow_redirects: bool = False,
) -> RateLimitedHttpClient:
    return RateLimitedHttpClient(
        source_id=settings.source_id,
        qps_limit=settings.qps_limit,
        min_interval_seconds=min_interval_seconds,
        timeout=settings.timeout_seconds,
        follow_redirects=follow_redirects,
    )


def build_provider(settings: DataSourceSettings) -> object | None:
    registration = ADAPTER_REGISTRY.get(settings.adapter)
    if registration is None:
        raise DataSourceConfigurationError(f"{settings.source_id}: unknown adapter")
    if not isinstance(settings, registration.settings_model):
        raise DataSourceConfigurationError(f"{settings.source_id}: adapter settings model mismatch")
    return registration.provider_factory(settings)


def build_enabled_providers(
    adapter_names: Iterable[str],
    environment: str | None = None,
) -> list[object]:
    allowed = set(adapter_names)
    providers: list[object] = []
    for settings in load_data_source_settings(environment).sources:
        if settings.adapter not in allowed or not settings.enabled or settings.license_status != "APPROVED":
            continue
        provider = build_provider(settings)
        if provider is not None:
            providers.append(provider)
    return providers


def validate_enabled_provider_factories(environment: str | None = None) -> None:
    for settings in load_data_source_settings(environment).sources:
        if settings.enabled and settings.license_status == "APPROVED":
            provider = build_provider(settings)
            client = getattr(provider, "client", None)
            close = getattr(client, "close", None)
            if callable(close):
                close()


def _require_type(
    settings: DataSourceSettings,
    expected_type: type[SettingsT],
) -> SettingsT:
    if not isinstance(settings, expected_type):
        raise DataSourceConfigurationError(f"{settings.source_id}: adapter settings model mismatch")
    return settings
