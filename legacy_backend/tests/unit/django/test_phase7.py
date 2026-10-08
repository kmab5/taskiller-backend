from taskiller.django_operations.worker_service import worker_id


def test_django_worker_identity() -> None:
    assert worker_id().endswith(":django")
