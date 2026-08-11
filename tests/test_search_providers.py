import os
import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import unittest
from unittest import mock

from scanner.search.providers.tavily import TavilySearchProvider
from scanner.search.providers.brave import BraveSearchProvider
from scanner.search.providers.serpapi import SerpApiSearchProvider
from scanner.search.web_search import WebSearchSource


class TestProviderMissingCredentials(unittest.TestCase):
    def test_tavily_unconfigured_without_env_var(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            provider = TavilySearchProvider()
            self.assertFalse(provider.is_configured())
            self.assertEqual(provider.search("test query"), [])

    def test_brave_unconfigured_without_env_var(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            provider = BraveSearchProvider()
            self.assertFalse(provider.is_configured())
            self.assertEqual(provider.search("test query"), [])

    def test_tavily_configured_with_env_var(self):
        with mock.patch.dict(os.environ, {"TAVILY_API_KEY": "fake-key"}, clear=True):
            provider = TavilySearchProvider()
            self.assertTrue(provider.is_configured())


class TestWebSearchSourceProviderSelection(unittest.TestCase):
    def test_no_provider_env_var_unavailable(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            source = WebSearchSource()
            self.assertFalse(source.available)
            self.assertEqual(source.search("query"), [])

    def test_unknown_provider_name_unavailable(self):
        with mock.patch.dict(os.environ, {"WEB_SEARCH_PROVIDER": "not_a_real_provider"}, clear=True):
            source = WebSearchSource()
            self.assertFalse(source.available)

    def test_tavily_selected_and_configured(self):
        with mock.patch.dict(
            os.environ, {"WEB_SEARCH_PROVIDER": "tavily", "TAVILY_API_KEY": "fake-key"}, clear=True
        ):
            source = WebSearchSource()
            self.assertTrue(source.available)

    def test_tavily_selected_but_missing_key_unavailable(self):
        with mock.patch.dict(os.environ, {"WEB_SEARCH_PROVIDER": "tavily"}, clear=True):
            source = WebSearchSource()
            self.assertFalse(source.available)


class TestProviderRequestFailureHandling(unittest.TestCase):
    def test_tavily_request_exception_handled(self):
        import requests
        with mock.patch.dict(os.environ, {"TAVILY_API_KEY": "fake-key"}, clear=True):
            provider = TavilySearchProvider()
            with mock.patch(
                "scanner.search.providers.tavily.requests.post",
                side_effect=requests.RequestException("network error"),
            ):
                self.assertEqual(provider.search("query"), [])

    def test_tavily_provider_error_field_returns_empty(self):
        with mock.patch.dict(os.environ, {"TAVILY_API_KEY": "fake-key"}, clear=True):
            provider = TavilySearchProvider()
            mock_resp = mock.Mock()
            mock_resp.json.return_value = {"error": "invalid api key"}
            mock_resp.raise_for_status.return_value = None
            with mock.patch("scanner.search.providers.tavily.requests.post", return_value=mock_resp):
                self.assertEqual(provider.search("query"), [])

    def test_tavily_parses_results(self):
        with mock.patch.dict(os.environ, {"TAVILY_API_KEY": "fake-key"}, clear=True):
            provider = TavilySearchProvider()
            mock_resp = mock.Mock()
            mock_resp.json.return_value = {
                "results": [{"title": "Test listing", "url": "https://trademe.co.nz/x", "content": "desc"}]
            }
            mock_resp.raise_for_status.return_value = None
            with mock.patch("scanner.search.providers.tavily.requests.post", return_value=mock_resp):
                results = provider.search("query")
                self.assertEqual(len(results), 1)
                self.assertEqual(results[0].title, "Test listing")
                self.assertEqual(results[0].source, "web_search:tavily")


class TestTavilyAuthentication(unittest.TestCase):
    # Tavily's current API authenticates via `Authorization: Bearer <key>`,
    # not an `api_key` field in the JSON body (their OpenAPI spec declares
    # `security: bearerAuth` on /search with no api_key in the request
    # schema) -- sending it in the body gets silently rejected with a 403
    # at Tavily's edge, before it's even billed against the account. This
    # regression-tests the fix: the key goes out ONLY as a Bearer header,
    # never in the request body, so it can't leak into logs via the payload.
    _FAKE_KEY = "test-key-not-a-real-secret"

    def test_sends_bearer_authorization_header(self):
        with mock.patch.dict(os.environ, {"TAVILY_API_KEY": self._FAKE_KEY}, clear=True):
            provider = TavilySearchProvider()
            mock_resp = mock.Mock()
            mock_resp.json.return_value = {"results": []}
            mock_resp.raise_for_status.return_value = None
            with mock.patch(
                "scanner.search.providers.tavily.requests.post", return_value=mock_resp
            ) as mock_post:
                provider.search("query")

            self.assertEqual(mock_post.call_count, 1)
            _, kwargs = mock_post.call_args
            self.assertIn("headers", kwargs)
            self.assertEqual(kwargs["headers"].get("Authorization"), f"Bearer {self._FAKE_KEY}")

    def test_api_key_not_present_in_request_body(self):
        with mock.patch.dict(os.environ, {"TAVILY_API_KEY": self._FAKE_KEY}, clear=True):
            provider = TavilySearchProvider()
            mock_resp = mock.Mock()
            mock_resp.json.return_value = {"results": []}
            mock_resp.raise_for_status.return_value = None
            with mock.patch(
                "scanner.search.providers.tavily.requests.post", return_value=mock_resp
            ) as mock_post:
                provider.search("query")

            _, kwargs = mock_post.call_args
            self.assertIn("json", kwargs)
            self.assertNotIn("api_key", kwargs["json"])
            # The key must only ever travel via the header, never the body.
            self.assertNotIn(self._FAKE_KEY, kwargs["json"].values())

    def test_request_body_still_carries_query_params(self):
        with mock.patch.dict(os.environ, {"TAVILY_API_KEY": self._FAKE_KEY}, clear=True):
            provider = TavilySearchProvider()
            mock_resp = mock.Mock()
            mock_resp.json.return_value = {"results": []}
            mock_resp.raise_for_status.return_value = None
            with mock.patch(
                "scanner.search.providers.tavily.requests.post", return_value=mock_resp
            ) as mock_post:
                provider.search("query", max_results=5, include_domains=["trademe.co.nz"])

            _, kwargs = mock_post.call_args
            body = kwargs["json"]
            self.assertEqual(body["query"], "query")
            self.assertEqual(body["search_depth"], "basic")
            self.assertEqual(body["max_results"], 5)
            self.assertEqual(body["include_domains"], ["trademe.co.nz"])


class TestProvidersIgnoreUnsupportedKwargs(unittest.TestCase):
    """Phase 4A: discover.py now always passes include_domains to
    web_search.search(), which WebSearchSource forwards verbatim to
    whichever provider is configured. Only Tavily supports domain
    restriction -- Brave and SerpApi must not blow up with a TypeError
    when they receive it anyway."""

    def test_brave_ignores_include_domains(self):
        with mock.patch.dict(os.environ, {"BRAVE_API_KEY": "fake-key"}, clear=True):
            provider = BraveSearchProvider()
            mock_resp = mock.Mock()
            mock_resp.json.return_value = {"web": {"results": []}}
            mock_resp.raise_for_status.return_value = None
            with mock.patch("scanner.search.providers.brave.requests.get", return_value=mock_resp):
                # Must not raise TypeError for the unexpected kwarg.
                self.assertEqual(provider.search("query", include_domains=["trademe.co.nz"]), [])

    def test_serpapi_ignores_include_domains(self):
        with mock.patch.dict(os.environ, {"SERPAPI_API_KEY": "fake-key"}, clear=True):
            provider = SerpApiSearchProvider()
            mock_resp = mock.Mock()
            mock_resp.json.return_value = {"organic_results": []}
            mock_resp.raise_for_status.return_value = None
            with mock.patch("scanner.search.providers.serpapi.requests.get", return_value=mock_resp):
                self.assertEqual(provider.search("query", include_domains=["trademe.co.nz"]), [])


if __name__ == "__main__":
    unittest.main()
