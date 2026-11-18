import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import requests

from sciencenet_bot.cli import deliver, main
from sciencenet_bot.crawler import CrawlError, fetch_articles, parse_page
from sciencenet_bot.models import Article
from sciencenet_bot.state import StateError, load_ids, save_ids
from sciencenet_bot.telegram import TelegramClient, TelegramError


def page(ids=("101",), category=7, next_page=None):
    rows = [
        "<tr><td>ID</td><td>文章标题</td><td>作者</td><td>点击</td><td>评论</td><td>日期</td></tr>"
    ]
    for article_id in ids:
        rows.append(
            f'<tr><td>{article_id}</td><td><a href="blog-42-{article_id}.html" '
            f'title="中文标题 {article_id}">中文标题 {article_id}</a></td>'
            "<td><a>作者甲</a></td><td>123</td><td>0</td><td>11-18</td></tr>"
        )
    html = '<meta charset="gbk"><table class="tablebox">' + "".join(rows) + "</table>"
    if next_page:
        html += f'<div class="pg"><a class="nxt" href="blog.php?mod=type&amp;type={category}&amp;page={next_page}">下一页</a></div>'
    return html.encode("gbk")


def response(html):
    result = Mock(content=html, encoding="gbk")
    result.raise_for_status.return_value = None
    return result


def article(article_id):
    return Article(
        article_id,
        "中文标题",
        "作者甲",
        f"https://blog.sciencenet.cn/blog-42-{article_id}.html",
        "科普集錦",
    )


class CrawlerTests(unittest.TestCase):
    def test_chinese_and_absolute_links(self):
        articles, next_url = parse_page(page(next_page=2), 7, "科普集錦")
        self.assertEqual(articles[0].title, "中文标题 101")
        self.assertEqual(articles[0].author, "作者甲")
        self.assertEqual(articles[0].url, "https://blog.sciencenet.cn/blog-42-101.html")
        self.assertTrue(next_url.endswith("page=2"))
        html = page().replace(b"blog-42-101.html", b"https://blog.sciencenet.cn/blog-42-101.html")
        self.assertEqual(parse_page(html, 7, "label")[0][0].url, articles[0].url)

    def test_blocked_and_changed_pages_fail(self):
        for html in (
            b"Access denied",
            b"<table><tr><td>oops</td></tr></table>",
            page().replace(b"blog-42-101.html", b"https://example.com/blog-42-101.html"),
            page().replace(b"blog-42-101.html", b"blog-42-999.html"),
        ):
            with self.subTest(html=html), self.assertRaises(CrawlError):
                parse_page(html, 7, "label")

    def test_pagination_and_cross_category_deduplication(self):
        session = Mock()
        session.get.side_effect = [
            response(page(("103", "102"), next_page=2)),
            response(page(("101",), next_page=3)),
            response(page(("103", "101"), category=3)),
        ]
        articles = fetch_articles(session, {"101"})
        self.assertEqual([item.id for item in articles], ["101", "102", "103"])
        self.assertEqual(session.get.call_count, 3)
        self.assertIn("page=2", session.get.call_args_list[1].args[0])
        self.assertIn("timeout", session.get.call_args.kwargs)

    def test_bad_pagination_and_recovery_limit_fail(self):
        with self.assertRaises(CrawlError):
            parse_page(page(next_page=1), 7, "label")
        session = Mock()
        session.get.return_value = response(page(("103",), next_page=2))
        with self.assertRaises(CrawlError):
            fetch_articles(session, {"101"}, max_pages=1)

    def test_http_failure_does_not_become_empty_success(self):
        session = Mock()
        session.get.side_effect = requests.Timeout("network failure")
        with self.assertRaises(CrawlError):
            fetch_articles(session, {"101"})


class StateAndDeliveryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "previous_articles.json"
        self.path.write_text('["100"]', encoding="utf-8")

    def test_legacy_state_and_deterministic_atomic_save(self):
        self.assertEqual(load_ids(self.path), {"100"})
        save_ids(self.path, {"101", "9", "100"})
        self.assertEqual(json.loads(self.path.read_text()), ["9", "100", "101"])
        self.assertEqual(list(self.path.parent.glob("*.tmp")), [])

    def test_missing_corrupt_or_wrong_state_is_rejected(self):
        with self.assertRaises(StateError):
            load_ids(self.path.parent / "missing.json")
        for content in ("", "{broken", '{"101": true}', "[101]", '["not-an-id"]'):
            self.path.write_text(content)
            with self.subTest(content=content), self.assertRaises(StateError):
                load_ids(self.path)

    def test_failed_delivery_is_not_recorded_and_success_is_checkpointed(self):
        client = Mock()
        client.send.side_effect = [None, TelegramError("rejected")]
        with self.assertRaises(TelegramError):
            deliver(
                [article("101"), article("102"), article("103")],
                {"100"},
                self.path,
                client,
                delay=0,
            )
        self.assertEqual(load_ids(self.path), {"100", "101"})
        retry_client = Mock()
        self.assertEqual(
            deliver([article("101"), article("102")], load_ids(self.path), self.path, retry_client),
            (1, 0),
        )
        retry_client.send.assert_called_once_with(article("102").message())

    def test_cap_does_not_mark_deferred_articles_sent(self):
        client = Mock()
        sent, remaining = deliver(
            [article("100"), article("101"), article("102")],
            {"100"},
            self.path,
            client,
            max_messages=1,
        )
        self.assertEqual((sent, remaining), (1, 1))
        self.assertEqual(load_ids(self.path), {"100", "101"})
        client.send.assert_called_once()

    def test_failed_atomic_replace_preserves_old_state(self):
        with patch("sciencenet_bot.state.os.replace", side_effect=OSError("locked")):
            with self.assertRaises(StateError):
                save_ids(self.path, {"100", "101"})
        self.assertEqual(load_ids(self.path), {"100"})
        self.assertEqual(list(self.path.parent.glob("*.tmp")), [])

    @patch("sciencenet_bot.cli.TelegramClient")
    @patch("sciencenet_bot.cli.fetch_articles", return_value=[article("101")])
    def test_dry_run_cannot_send_or_modify_state(self, fetch, client):
        before = self.path.read_bytes()
        self.assertEqual(main(["--dry-run", "--state-file", str(self.path)]), 0)
        client.assert_not_called()
        self.assertEqual(self.path.read_bytes(), before)

    @patch("sciencenet_bot.cli.TelegramClient")
    @patch("sciencenet_bot.cli.fetch_articles", return_value=[article("101")])
    def test_read_only_verification_never_sends(self, fetch, client):
        before = self.path.read_bytes()
        self.assertEqual(
            main(["--dry-run", "--verify-telegram", "--state-file", str(self.path)]), 0
        )
        instance = client.return_value.__enter__.return_value
        instance.verify.assert_called_once()
        instance.send.assert_not_called()
        self.assertEqual(self.path.read_bytes(), before)

    @patch("sciencenet_bot.cli.create_session")
    def test_empty_history_stops_before_any_network(self, session):
        self.path.write_text("[]")
        self.assertEqual(main(["--dry-run", "--state-file", str(self.path)]), 1)
        session.assert_not_called()

    @patch("sciencenet_bot.cli.TelegramClient")
    @patch("sciencenet_bot.cli.fetch_articles", return_value=[article("101")])
    def test_verify_flag_alone_is_read_only(self, fetch, client):
        before = self.path.read_bytes()
        self.assertEqual(main(["--verify-telegram", "--state-file", str(self.path)]), 0)
        self.assertTrue(client.call_args.kwargs["read_only"])
        instance = client.return_value.__enter__.return_value
        instance.verify.assert_called_once()
        instance.send.assert_not_called()
        self.assertEqual(self.path.read_bytes(), before)


class TelegramTests(unittest.TestCase):
    def setUp(self):
        self.client = TelegramClient("test-token", "test-chat")
        self.client._session = Mock()

    def api_response(self, result=None, status=200, data=None):
        return Mock(
            status_code=status,
            ok=status < 400,
            json=Mock(return_value=data if data is not None else {"ok": True, "result": result}),
        )

    def test_verification_uses_only_read_methods(self):
        self.client._session.post.side_effect = [
            self.api_response({"id": 42}),
            self.api_response({"type": "channel"}),
            self.api_response({"status": "administrator", "can_post_messages": True}),
        ]
        self.client.verify()
        methods = [
            call.args[0].rsplit("/", 1)[-1] for call in self.client._session.post.call_args_list
        ]
        self.assertEqual(methods, ["getMe", "getChat", "getChatMember"])

    def test_channel_post_permission_is_required(self):
        self.client._session.post.side_effect = [
            self.api_response({"id": 42}),
            self.api_response({"type": "channel"}),
            self.api_response({"status": "administrator", "can_post_messages": False}),
        ]
        with self.assertRaises(TelegramError):
            self.client.verify()

    @patch("sciencenet_bot.telegram.time.sleep")
    def test_rate_limit_respects_retry_after(self, sleep):
        self.client._session.post.side_effect = [
            self.api_response(
                status=429, data={"ok": False, "error_code": 429, "parameters": {"retry_after": 2}}
            ),
            self.api_response({"message_id": 123}),
        ]
        self.client.send("article text")
        sleep.assert_called_once_with(2)

    def test_timeout_is_not_immediately_retried_or_leaked(self):
        self.client._session.post.side_effect = requests.Timeout(
            "https://api.telegram.org/bottest-token/sendMessage"
        )
        with self.assertRaises(TelegramError) as caught:
            self.client.send("article text")
        self.assertNotIn("test-token", str(caught.exception))
        self.assertEqual(self.client._session.post.call_count, 1)

    def test_unacknowledged_or_invalid_api_response_fails(self):
        for result in (
            self.api_response({}),
            self.api_response(
                status=403, data={"ok": False, "error_code": 403, "description": "test-token"}
            ),
            self.api_response(data=[]),
            Mock(status_code=502, json=Mock(side_effect=ValueError())),
        ):
            self.client._session.post.return_value = result
            with self.subTest(result=result), self.assertRaises(TelegramError) as caught:
                self.client.send("article text")
            self.assertNotIn("test-token", str(caught.exception))

    def test_missing_configuration_and_oversized_message_fail(self):
        with self.assertRaises(TelegramError):
            TelegramClient("", "")
        with self.assertRaises(TelegramError):
            self.client.send("x" * 4097)
        self.client._session.post.assert_not_called()

    def test_read_only_client_blocks_send_at_transport_boundary(self):
        self.client._read_only = True
        with self.assertRaises(TelegramError):
            self.client.send("must never reach subscribers")
        self.client._session.post.assert_not_called()


if __name__ == "__main__":
    unittest.main()
