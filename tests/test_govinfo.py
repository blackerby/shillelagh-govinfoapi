"""
Tests for the GovInfo adapter.
"""
from datetime import datetime

import pytest
from pytest_mock import MockerFixture
import requests

from shillelagh_govinfo.govinfo import GovInfoAPI
from shillelagh.backends.apsw.db import connect

from .fakes import govinfo_empty_response, govinfo_response

FAKE_API_KEY = "44a3270074f30ea5a8f0051941fb6528"


@pytest.mark.parametrize(
    "input, expected",
    [
        ("https://api.govinfo.gov/collections", False),
        (f"https://api.govinfo.gov/collections?api_key={FAKE_API_KEY}", False),
        (
            f"https://api.govinfo.gov/collections/BILLS/2018-01-28T20%3A18%3A10Z?api_key={FAKE_API_KEY}",
            False,
        ),
        (
            f"https://api.govinfo.gov/collections/BILLS/2018-01-28T20%3A18%3A10Z?offset=0&api_key={FAKE_API_KEY}",
            False,
        ),
        (
            f"https://api.govinfo.gov/collections/BILLS/2018-01-28T20%3A18%3A10Z?offset=0&pageSize=1000&api_key={FAKE_API_KEY}",
            True,
        ),
        (
            f"https://api.govinfo.gov/collections/BILLS/2018-01-28T20%3A18%3A10Z/2018-01-29T20%3A18%3A10Z?offset=0&pageSize=1000&api_key={FAKE_API_KEY}",
            True,
        ),
        (
            f"https://api.govinfo.gov/collections/BILLS/2018-01-28T20%3A18%3A10Z/2018-10-21T13:31:42.363926?offset=0&pageSize=1000&api_key={FAKE_API_KEY}",
            False,
        ),
    ],
)
def test_supports(input, expected) -> None:
    """
    Test the ``supports`` method.
    """

    assert GovInfoAPI.supports(input) == expected


def test_govinfo_with_data(mocker: MockerFixture, requests_mock):
    """
    Run SQL against the adapter.
    """

    mocker.patch(
        "shillelagh_govinfo.govinfo.requests_cache.CachedSession",
        return_value=requests.Session(),
    )

    url = f"https://api.govinfo.gov/collections/BILLS/2023-02-28T20%3A18%3A10Z/2023-03-01T20%3A18%3A10Z?offset=0&pageSize=1&api_key={FAKE_API_KEY}"
    requests_mock.get(url, json=govinfo_response)

    connection = connect(":memory:")
    cursor = connection.cursor()
    sql = f"""
        SELECT * FROM "{url}"
    """

    data = list(cursor.execute(sql))
    assert data == [
        (
            "BILLS-118hr796ih",
            datetime(2023, 3, 1, 10, 29, 21),
            "https://api.govinfo.gov/packages/BILLS-118hr796ih/summary",
            "hr",
            "Supply Chain Mapping and Monitoring Act",
            118,
            "2023-02-02",
        ),
    ]


def test_govinfo_no_data(mocker, requests_mock):
    mocker.patch(
        "shillelagh_govinfo.govinfo.requests_cache.CachedSession",
        return_value=requests.Session(),
    )

    url = f"https://api.govinfo.gov/collections/BILLS/2018-01-28T20%3A18%3A10Z/2018-01-29T20%3A18%3A10Z?offset=0&pageSize=1000&api_key={FAKE_API_KEY}"
    requests_mock.get(url, json=govinfo_empty_response)

    connection = connect(":memory:")
    cursor = connection.cursor()
    sql = f"""
        SELECT * FROM "{url}"
    """

    data = list(cursor.execute(sql))
    assert data == []
