from app.data_sources.weather_providers import (
    OpenMeteoForecastProvider,
    WeatherForecastRequest,
    build_enabled_weather_providers,
    get_weather_forecast_with_enabled_provider_result,
)


class _FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self.payload


class _FakeOpenMeteoClient:
    def __init__(self, payload=None):
        self.calls = []
        self.payload = payload or _open_meteo_payload()

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return _FakeResponse(self.payload)


def test_open_meteo_forecast_maps_current_weather_response():
    client = _FakeOpenMeteoClient()
    provider = OpenMeteoForecastProvider(client=client, base_url="https://example.test")

    forecast = provider.get_forecast(WeatherForecastRequest(latitude=36.0662, longitude=120.3826, timezone="Asia/Shanghai"))

    assert client.calls[0][0] == "https://example.test/v1/forecast"
    assert client.calls[0][1]["params"]["latitude"] == 36.0662
    assert client.calls[0][1]["params"]["longitude"] == 120.3826
    assert client.calls[0][1]["params"]["timezone"] == "Asia/Shanghai"
    assert "temperature_2m" in client.calls[0][1]["params"]["current"]

    assert forecast.latitude == 36.0662
    assert forecast.longitude == 120.3826
    assert forecast.observed_at.isoformat() == "2026-06-04T14:15:00"
    assert forecast.temperature_celsius == 24.1
    assert forecast.apparent_temperature_celsius == 25.2
    assert forecast.precipitation_mm == 0.0
    assert forecast.rain_mm == 0.0
    assert forecast.weather_code == 1
    assert forecast.wind_speed_kmh == 13.4
    assert forecast.wind_gusts_kmh == 24.8
    assert forecast.source_timezone == "Asia/Shanghai"
    assert forecast.data_source.source_id == "open_meteo_forecast"
    assert forecast.data_source.source_type == "WEATHER"


def test_open_meteo_provider_is_enabled_by_default():
    providers = build_enabled_weather_providers("DEV")
    assert [provider.source_id for provider in providers] == ["open_meteo_forecast"]


def test_open_meteo_empty_current_weather_reports_failure(monkeypatch):
    class _EmptyProvider:
        source_id = "open_meteo_forecast"

        def get_forecast(self, request):
            raise ValueError("empty real response")

    monkeypatch.setattr("app.data_sources.weather_providers.build_enabled_weather_providers", lambda environment=None: [_EmptyProvider()])

    result = get_weather_forecast_with_enabled_provider_result(
        WeatherForecastRequest(latitude=36.0662, longitude=120.3826),
        "DEV",
    )

    assert result.forecasts == []
    assert result.attempted_source_ids == ["open_meteo_forecast"]
    assert result.failure_message == "open_meteo_forecast: empty real response"


def _open_meteo_payload():
    return {
        "latitude": 36.0662,
        "longitude": 120.3826,
        "timezone": "Asia/Shanghai",
        "current": {
            "time": "2026-06-04T14:15",
            "temperature_2m": 24.1,
            "apparent_temperature": 25.2,
            "precipitation": 0.0,
            "rain": 0.0,
            "weather_code": 1,
            "wind_speed_10m": 13.4,
            "wind_gusts_10m": 24.8,
        },
    }
