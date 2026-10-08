from uuid import uuid4

import pytest

from taskiller.core.problems import ApiError
from taskiller.users.etag import make_etag, require_etag


def test_etag_encodes_resource_version() -> None:
    resource_id = uuid4()
    etag = make_etag("user", resource_id, 3)

    assert etag == f'"user:{resource_id}:v3"'
    require_etag(etag, etag)


def test_missing_or_stale_etag_fails() -> None:
    with pytest.raises(ApiError) as error:
        require_etag('"old"', '"new"')

    assert error.value.status_code == 412
