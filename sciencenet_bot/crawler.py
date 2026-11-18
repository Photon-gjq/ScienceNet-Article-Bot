"""Read the two original categories, including a bounded recovery backlog."""

import logging
import re
from urllib.parse import parse_qs, urljoin, urlparse

import requests
from bs4 import BeautifulSoup
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from .models import Article

LOG = logging.getLogger(__name__)
BASE_URL = "https://blog.sciencenet.cn/"
CATEGORIES = ((7, "科普集錦"), (3, "觀點評述"))
TIMEOUT = (10, 30)


class CrawlError(RuntimeError):
    pass


def create_session() -> requests.Session:
    session = requests.Session()
    retries = Retry(
        total=3,
        backoff_factor=1,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset({"GET"}),
    )
    session.mount("https://", HTTPAdapter(max_retries=retries))
    session.headers["User-Agent"] = (
        "ScienceNet-Article-Bot/2.0 (+https://github.com/Photon-gjq/ScienceNet-Article-Bot)"
    )
    return session


def parse_page(
    html: bytes, category: int, label: str, page: int = 1, encoding: str = "gb18030"
) -> tuple[list[Article], str | None]:
    soup = BeautifulSoup(html, "html.parser", from_encoding=encoding)
    articles = []
    for row in soup.select("table.tablebox tr"):
        columns = row.find_all("td", recursive=False)
        if not columns or columns[0].get_text(strip=True).upper() == "ID":
            continue
        article_id = columns[0].get_text(strip=True)
        if len(columns) < 6 or not article_id.isascii() or not article_id.isdecimal():
            raise CrawlError(f"Category {category}: unexpected article row")
        link = columns[1].find("a", href=True)
        url = urljoin(BASE_URL, link["href"]) if link else ""
        parsed_url = urlparse(url)
        match = re.fullmatch(r"/blog-\d+-(\d+)\.html", parsed_url.path)
        if (
            parsed_url.scheme != "https"
            or parsed_url.netloc != "blog.sciencenet.cn"
            or not match
            or match[1] != article_id
        ):
            raise CrawlError(f"Category {category}: invalid link for article {article_id}")
        title = (link.get("title") or link.get_text(" ", strip=True)).strip()
        author = columns[2].get_text(" ", strip=True)
        if not title or not author:
            raise CrawlError(f"Category {category}: missing title/author for {article_id}")
        articles.append(Article(article_id, title, author, url, label))
    if not articles:
        raise CrawlError(
            f"Category {category}: no article rows; the site may have changed or blocked the request"
        )

    next_link = soup.select_one(".pg a.nxt[href]")
    next_url = urljoin(BASE_URL, next_link["href"]) if next_link else None
    if next_url:
        parsed_url = urlparse(next_url)
        query = parse_qs(parsed_url.query)
        if (
            parsed_url.scheme != "https"
            or parsed_url.netloc != "blog.sciencenet.cn"
            or parsed_url.path != "/blog.php"
            or query.get("mod") != ["type"]
            or query.get("type") != [str(category)]
            or query.get("page") != [str(page + 1)]
        ):
            raise CrawlError(f"Category {category}: unexpected next-page link")
    return articles, next_url


def fetch_articles(
    session: requests.Session, previous_ids: set[str], max_pages: int = 20
) -> list[Article]:
    # Deduplicate articles appearing in both categories before sending anything.
    articles_by_id = {}
    for category, label in CATEGORIES:
        url = f"{BASE_URL}blog.php?mod=type&type={category}"
        for page in range(1, max_pages + 1):
            try:
                response = session.get(url, timeout=TIMEOUT)
                response.raise_for_status()
            except requests.RequestException as exc:
                raise CrawlError(
                    f"Category {category}, page {page}: fetch failed ({type(exc).__name__})"
                ) from None
            articles, next_url = parse_page(
                response.content,
                category,
                label,
                page,
                encoding=response.encoding or "gb18030",
            )
            for article in articles:
                articles_by_id.setdefault(article.id, article)
            LOG.info("Fetched category=%s page=%d articles=%d", label, page, len(articles))
            if (
                not next_url
                or not previous_ids
                or all(article.id in previous_ids for article in articles)
            ):
                break
            if page == max_pages:
                raise CrawlError(f"Category {category}: reached {max_pages}-page recovery limit")
            url = next_url
    return sorted(articles_by_id.values(), key=lambda article: int(article.id))
