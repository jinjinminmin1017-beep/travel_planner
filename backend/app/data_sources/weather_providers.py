from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol, cast

import httpx

from app.models.schemas import DataSourceMetadata, DataSourceType, now_timepoint


class WeatherProviderError(RuntimeError):
    pass


@dataclass(frozen=True)
class WeatherForecastRequest:
    latitude: float
    longitude: float
    timezone: str = "auto"
    forecast_days: int = 1


@dataclass(frozen=True)
class WeatherForecast:
    latitude: float
    longitude: float
    observed_at: datetime
    temperature_celsius: float | None
    apparent_temperature_celsius: float | None
    precipitation_mm: float | None
    rain_mm: float | None
    weather_code: int | None
    wind_speed_kmh: float | None
    wind_gusts_kmh: float | None
    source_timezone: str
    data_source: DataSourceMetadata


@dataclass(frozen=True)
class WeatherProviderSearchResult:
    forecasts: list[WeatherForecast]
    attempted_source_ids: list[str]
    failure_message: str | None = None


class WeatherForecastProvider(Protocol):
    source_id: str

    def get_forecast(self, request: WeatherForecastRequest) -> WeatherForecast:
        ...


class OpenMeteoForecastProvider:
    source_id = "open_meteo_forecast"

    def __init__(
        self,
        client: httpx.Client | None = None,
        base_url: str = "https://api.open-meteo.com",
        timeout_seconds: float = 10.0,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.client = client or httpx.Client(timeout=timeout_seconds)

    def get_forecast(self, request: WeatherForecastRequest) -> WeatherForecast:
        response = self.client.get(
            f"{self.base_url}/v1/forecast",
            params={
                "latitude": request.latitude,
                "longitude": request.longitude,
                "current": ",".join(
                    [
                        "temperature_2m",
                        "apparent_temperature",
                        "precipitation",
                        "rain",
                        "weather_code",
                        "wind_speed_10m",
                        "wind_gusts_10m",
                    ]
                ),
                "forecast_days": max(1, min(request.forecast_days, 3)),
                "timezone": request.timezone,
            },
        )
        response.raise_for_status()
        payload = response.json()
        return self._parse_forecast(payload)

    def _parse_forecast(self, payload: dict[str, Any]) -> WeatherForecast:
        current = payload.get("current") or {}
        if not current:
            raise WeatherProviderError("Open-Meteo response has no current weather")
        observed_at_raw = current.get("time")
        if not observed_at_raw:
            raise WeatherProviderError("Open-Meteo current weather has no time")
        return WeatherForecast(
            latitude=float(payload.get("latitude")),
            longitude=float(payload.get("longitude")),
            observed_at=datetime.fromisoformat(str(observed_at_raw)),
            temperature_celsius=_optional_float(current.get("temperature_2m")),
            apparent_temperature_celsius=_optional_float(current.get("apparent_temperature")),
            precipitation_mm=_optional_float(current.get("precipitation")),
            rain_mm=_optional_float(current.get("rain")),
            weather_code=_optional_int(current.get("weather_code")),
            wind_speed_kmh=_optional_float(current.get("wind_speed_10m")),
            wind_gusts_kmh=_optional_float(current.get("wind_gusts_10m")),
            source_timezone=str(payload.get("timezone") or "UTC"),
            data_source=weather_data_source_metadata(self.source_id, "Open-Meteo Forecast API"),
        )


def weather_data_source_metadata(source_id: str, source_name: str) -> DataSourceMetadata:
    return DataSourceMetadata(
        source_id=source_id,
        source_name=source_name,
        source_type=DataSourceType.WEATHER,
        authority_level="B",
        license_status="APPROVED",
        commercial_allowed=False,
        fetched_at=now_timepoint(),
        cacheable=True,
    )


def build_enabled_weather_providers(environment: str | None = None) -> list[WeatherForecastProvider]:
    from app.data_sources.provider_registry import build_enabled_providers

    return [
        cast(WeatherForecastProvider, provider)
        for provider in build_enabled_providers({"open_meteo_forecast"}, environment)
    ]


def get_weather_forecast_with_enabled_provider_result(request: WeatherForecastRequest, environment: str | None = None) -> WeatherProviderSearchResult:
    attempted_source_ids: list[str] = []
    failure_messages: list[str] = []
    for provider in build_enabled_weather_providers(environment):
        attempted_source_ids.append(provider.source_id)
        try:
            return WeatherProviderSearchResult(forecasts=[provider.get_forecast(request)], attempted_source_ids=attempted_source_ids)
        except (httpx.HTTPError, WeatherProviderError, ValueError) as exc:
            failure_messages.append(f"{provider.source_id}: {exc}")
    return WeatherProviderSearchResult(forecasts=[], attempted_source_ids=attempted_source_ids, failure_message="; ".join(failure_messages) or None)


def _optional_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    return float(value)


def _optional_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    return int(value)
