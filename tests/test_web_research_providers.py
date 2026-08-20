from ai_truck_radio_app.web_research import DuckDuckGoSearchParser, PageParser, SearchParser


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


def test_page_parser_extracts_publication_date_metadata() -> None:
    parser = PageParser()
    parser.feed(
        '<html><head><meta property="article:published_time" content="2026-08-03T06:30:00Z"></head>'
        '<body><article><h1>Новость</h1><p>Проверенный текст.</p></article></body></html>'
    )
    assert parser.published_at == "2026-08-03T06:30:00Z"


def test_page_parser_collects_article_links() -> None:
    parser = PageParser()
    parser.feed('<main><a href="/20260803/fresh-story-123.html">Свежая новость</a></main>')
    assert parser.links == ["/20260803/fresh-story-123.html"]
