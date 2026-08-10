import os
import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import unittest
from unittest import mock

from scanner.search.providers.tavily import TavilySearchProvider
from scanner.search.providers.brave import BraveSearchProvider
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


if __name__ == "__main__":
    unittest.main()
