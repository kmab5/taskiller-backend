from datetime import UTC, datetime

from taskiller.core.config import Settings
from taskiller.main import create_app


def _settings() -> Settings:
    return Settings(
        _env_file=None,
        env="test",
        database_url="postgresql+psycopg://unused:unused@localhost/unused",
        jwt_secret="test-jwt-secret-" + "x" * 48,
        token_hash_secret="test-token-secret-" + "y" * 48,
    )


def test_openapi_exposes_round_6_analytics_contract() -> None:
    app = create_app(_settings())
    schema = app.openapi()
    expected = {
        "/api/v1/analytics/summary": "getAnalyticsSummary",
        "/api/v1/analytics/work-types": "getWorkTypeAnalytics",
        "/api/v1/analytics/work-items/{workItemId}": "getWorkItemAnalytics",
        "/api/v1/analytics/timeseries": "getAnalyticsTimeseries",
        "/api/v1/analytics/focus-patterns": "getFocusPatterns",
    }
    for path, operation_id in expected.items():
        assert schema["paths"][path]["get"]["operationId"] == operation_id


def test_personalization_threshold_is_conservative() -> None:
    from taskiller.analytics.service import AnalyticsService

    assert not AnalyticsService._personalization_eligible(
        sample_size=4,
        interval_count=8,
        median_focus_score=5.0,
        focus_review_count=4,
    )
    assert not AnalyticsService._personalization_eligible(
        sample_size=5,
        interval_count=8,
        median_focus_score=2.0,
        focus_review_count=4,
    )
    assert AnalyticsService._personalization_eligible(
        sample_size=5,
        interval_count=8,
        median_focus_score=4.0,
        focus_review_count=3,
    )
    assert AnalyticsService._personalization_eligible(
        sample_size=8,
        interval_count=8,
        median_focus_score=None,
        focus_review_count=0,
    )


def test_range_requires_offsets() -> None:
    from taskiller.analytics.service import AnalyticsService
    from taskiller.core.problems import ApiError

    try:
        AnalyticsService._validate_range(
            datetime(2026, 9, 1),
            datetime(2026, 10, 1, tzinfo=UTC),
        )
    except ApiError as exc:
        assert exc.code == "invalid_datetime_timezone"
    else:
        raise AssertionError("naive datetime was accepted")


def test_week_bucket_uses_public_sunday_zero_weekday_numbering() -> None:
    from zoneinfo import ZoneInfo

    from taskiller.analytics.schemas import AnalyticsBucket
    from taskiller.analytics.service import AnalyticsService

    wednesday = datetime(2026, 9, 30, 12, tzinfo=UTC)
    monday = AnalyticsService._bucket_start(wednesday, AnalyticsBucket.WEEK, ZoneInfo("UTC"), 1)
    sunday = AnalyticsService._bucket_start(wednesday, AnalyticsBucket.WEEK, ZoneInfo("UTC"), 0)
    assert monday == datetime(2026, 9, 28, tzinfo=UTC)
    assert sunday == datetime(2026, 9, 27, tzinfo=UTC)
