from taskiller.core.config import Environment, Settings


def test_settings_defaults_are_local_safe() -> None:
    settings = Settings(_env_file=None)

    assert settings.env is Environment.LOCAL
    assert settings.api_prefix == "/api/v1"
    assert settings.is_production is False
