# pylint: disable=abstract-method
"""
An adapter for the Government Publishing Office GovInfo API.
"""
# TODO: refactor to use urllib.parse.urljoin

import re
import urllib.parse
from datetime import datetime
from typing import Any, Dict, Iterator, List, Optional, Tuple

import requests
import requests_cache

from shillelagh.adapters.base import Adapter
from shillelagh.exceptions import ProgrammingError
from shillelagh.fields import Field, Integer, ISODateTime, Order, String
from shillelagh.filters import Filter, Range
from shillelagh.typing import RequestedOrder, Row

COLLECTIONS = ("bills",)
DATE_PATTERN = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z")


class GovInfoAPI(Adapter):
    """
    An adapter for the Government Publishing Office GovInfo API.
    """

    # Set this to ``True`` if the adapter doesn't access the filesystem.
    safe = True

    # This method is used to determine which URIs your adapter will handle. For
    # example, if your adapter interfaces with an API at api.example.com you
    # can do:
    #
    #     parsed = urllib.parse.urlparse(uri)
    #     return parsed.netloc == "api.example.com"
    #
    # The method will be called 1 or 2 times. On the first call ``fast`` will be
    # true, and the adapter should return as soon as possible. This means that if
    # you need to do a network request to determine if the URI should be handled
    # by your adapter, when ``fast=True`` you should return ``None``.
    #
    # On the second call, ``fast`` will be false, and the adapter can make network
    # requests to introspect URIs. The adapter should then return either true or
    # false on the second request.
    @staticmethod
    def _supports_collections(
        split_path: List[str],
        query_string: Dict[str, List[str]],
    ) -> bool:
        # only support the endpoint if it includes a value for the `collection`
        # param and `lastModifiedStartDate` param
        if len(split_path) < 4:
            return False

        collection = split_path[2]
        start_date = urllib.parse.unquote(split_path[3])
        supported_collection = collection.lower() in COLLECTIONS
        valid_start_date = bool(DATE_PATTERN.fullmatch(start_date))
        valid_end_date = True

        if len(split_path) == 5:
            end_date = urllib.parse.unquote(split_path[4])
            valid_end_date = bool(DATE_PATTERN.fullmatch(end_date))

        return (
            supported_collection
            and valid_start_date
            and valid_end_date
            and "offset" in query_string
            and "pageSize" in query_string
        )

    @staticmethod
    def _supports_packages(
        split_path: List[str],
        query_string: Dict[str, List[str]],
    ) -> bool:
        raise NotImplementedError

    @staticmethod
    def _supports_published(
        split_path: List[str],
        query_string: Dict[str, List[str]],
    ) -> bool:
        raise NotImplementedError

    @staticmethod
    def _supports_related(
        split_path: List[str],
        query_string: Dict[str, List[str]],
    ) -> bool:
        raise NotImplementedError

    @staticmethod
    def supports(uri: str, fast: bool = True, **kwargs: Any) -> Optional[bool]:
        # TODO: check kwargs for api key
        parsed = urllib.parse.urlparse(uri)
        query_string = urllib.parse.parse_qs(parsed.query)

        # first part of path should be one of `collections`, `packages`, `published`, `related`
        # we ignore `search` TODO: explain why
        split_path = parsed.path.split("/")
        endpoint = split_path[1]
        supports_endpoint = False

        if endpoint == "collections":
            supports_endpoint = GovInfoAPI._supports_collections(
                split_path,
                query_string,
            )
        elif endpoint == "packages":
            supports_endpoint = GovInfoAPI._supports_packages(split_path, query_string)
        elif endpoint == "published":
            supports_endpoint = GovInfoAPI._supports_published(split_path, query_string)
        elif endpoint == "related":
            supports_endpoint = GovInfoAPI._supports_related(split_path, query_string)
        else:
            # TODO: expand on this exception
            raise ProgrammingError

        return (
            parsed.netloc == "api.govinfo.gov"
            and supports_endpoint
            and "api_key" in query_string
        )

    # This method parses the URI into arguments that are passed to initialize the
    # adapter class. The simplest implementation returns the URI unmodified.
    @staticmethod
    def parse_uri(uri: str) -> Tuple[str]:
        return (uri,)

    def __init__(self, uri: str):
        super().__init__()

        parsed = urllib.parse.urlparse(uri)
        query_string = urllib.parse.parse_qs(parsed.query)
        self.url = f"{parsed.scheme}://{parsed.netloc}"
        self.api_key = query_string["api_key"][0]

        split_path = parsed.path.split("/")
        self.endpoint = split_path[1]

        if self.endpoint == "collections":
            self.collection = split_path[2]
            self.start_date = split_path[3]
            self.end_date = split_path[4] if len(split_path) == 5 else None
            self.offset = query_string["offset"][0]
            self.page_size = query_string["pageSize"][0]

        # If the adapter needs to do API requests it's useful to use a cache for
        # the requests. If you're not doing network requests you get delete this
        # session object.
        self._session = requests_cache.CachedSession(
            cache_name="govinfo_cache",
            backend="sqlite",
            expore_after=180,
        )

        # For adapters with dynamic columns (ie, number, names, and types of
        # columns depend on the URI) it's good practice to set the columns when
        # the class is initialized.
        self._set_columns(self.endpoint)

    # When defining columns it's important to know which columns can be used to
    # filter the URI. For example, if the API accepts a time range the adapter
    # probably needs a temporal column that is filterable:
    #
    #     from shillelagh.fields import DateTime
    #     from shillelagh.filters import Range
    #
    #     self.columns["time"] = DateTime(filters=[Range])
    #
    # It's then up to the ``get_rows`` method to translate temporal filters into
    # the corresponding API calls.
    #
    # The column definition should also specify if the column has a natural order,
    # or if the adapter can handle any requested order (and the adapter will be
    # responsible for ordering the data):
    #
    #     from shillelagh.fields import Integer
    #     from shillelagh.fields import Order
    #
    #     self.columns["prime_numbers"] = Integer(
    #         filters=[Range],
    #         order=Order.ASCENDING,
    #     )
    #
    # Finally, columns can return data that is not filtered perfectly — eg, hourly
    # data filtered only down to the daily granularity. In that case the column
    # should be declared as inexact:
    #
    #     self.columns["time"] = DateTime(filters=[Range], exact=False)
    #

    # Column names are `packageId`, `lastModified`, `packageLink`
    # `docClass`, `title`, `congress`, `dateIssued`
    def _set_columns(self, endpoint: str) -> None:
        if endpoint == "collections":
            self.columns: Dict[str, Field] = {
                "package_id": String(order=Order.ANY),
                "last_modified": ISODateTime(filters=[Range], order=Order.ANY),
                "package_link": String(order=Order.ANY),
                "doc_class": String(order=Order.ANY),
                "title": String(order=Order.ANY),
                "congress": Integer(order=Order.ANY),
                "date_issued": String(filters=[Range], order=Order.ANY),
            }

    # If you have static columns you can get rid of the ``get_columns`` method,
    # get rid of ``_set_columns``, and simply define the columns as class
    # attributes:
    #
    # time = DateTime(filters=[Range])
    #
    # Then ``get_columns`` from the parent class will find these attributes and
    # use them as the dictionary of columns.
    def get_columns(self) -> Dict[str, Field]:
        return self.columns

    def _get_session(self):
        return self._session

    # This method is used to return any extra metadata associated with the URI.
    # You can delete it instead of returning an empty dictionary, since that's
    # the exact implementation of the parent method.

    # is this a good place to store the `count` part of the API response?
    def get_metadata(self) -> Dict[str, Any]:
        return {}

    # This method yields rows of data, each row a dictionary. If any columns are
    # declared as filterable there might be a corresponding ``Filter`` object in
    # the ``bounds`` argument that must be used to filter the column (unless the
    # column was declared as inexact).
    def get_rows(
        self,
        bounds: Dict[str, Filter],
        order: List[Tuple[str, RequestedOrder]],
        **kwargs,
    ) -> Iterator[Row]:
        base_url = f"{self.url}/{self.endpoint}"
        if self.endpoint == "collections":
            url = f"{base_url}/{self.collection}/{self.start_date}/"
            url += self.end_date if self.end_date else ""
            params = {
                "offset": self.offset,
                "pageSize": self.page_size,
                "api_key": self.api_key,
            }

        response = requests.get(url, params)
        payload = response.json()

        for record in payload["packages"]:
            yield {
                "package_id": record["packageId"],
                "last_modified": datetime.strptime(
                    record["lastModified"],
                    "%Y-%m-%dT%H:%M:%SZ",
                ),
                "package_link": record["packageLink"],
                "doc_class": record["docClass"],
                "title": record["title"],
                "congress": int(record["congress"]),
                # TODO: when I try to parse `dateIssued` as a date, no data is
                # returned. investigate why -- maybe sqlite3 docs on date type?
                "date_issued": record["dateIssued"],
            }
