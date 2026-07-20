from ai_truck_radio_app.web_research import DuckDuckGoSearchParser, SearchParser


def test_yahoo_search_parser_extracts_redirect_target() -> None:
    parser = SearchParser()
    parser.feed(
        '<a href="https://r.search.yahoo.com/_ylt=x/RU=https%3A%2F%2Fexample.org%2Fstory/RK=2/RS=x">Story</a>'
    )
    assert parser.results == [{"url": "https://example.org/story", "title": "Story"}]


def test_duckduckgo_parser_extracts_safe_result_url() -> None:
    parser = DuckDuckGoSearchParser()
    parser.feed(
        '<a class="result__a" href="/l/?uddg=https%3A%2F%2Fexample.net%2Fnews">Fresh news</a>'
    )
    assert parser.results == [{"url": "https://example.net/news", "title": "Fresh news"}]
