import unittest

from playwright.sync_api import sync_playwright

import core.navigation as navigation


class TestBookmarkTravelLink(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        playwright = sync_playwright().start()
        cls.addClassCleanup(playwright.stop)
        cls.browser = playwright.chromium.launch(channel="chrome")
        cls.addClassCleanup(cls.browser.close)

    def setUp(self):
        self.page = self.browser.new_page()
        self.addCleanup(self.page.close)
        self.page.route("https://pond.test/**", lambda route: route.fulfill(body="pond"))
        self.page.goto("https://pond.test/start")

    def show_bookmarks(self, *numbers):
        rows = "".join(
            f'<li class="tile"><div class="info-meta"><div class="description">HO {n}</div></div>'
            f'<button class="remove-bookmark">Remove bookmark</button>'
            f'<a class="btn" href="/pond-{n}">Fast travel</a></li>' for n in numbers
        )
        self.page.set_content('<div class="modal-body"><li data-ui-tab="bookmarks" class="active">'
                              f'Bookmarks</li><div class="map"><ul class="tiles">{rows}</ul></div></div>')

    def test_selects_only_the_link_for_the_exact_lake(self):
        self.show_bookmarks(10, 11, 1)
        self.assertTrue(navigation._click_bookmark_link(self.page, 1))
        self.assertEqual(self.page.url, 'https://pond.test/pond-1')

    def test_refuses_duplicate_lake_descriptions(self):
        self.show_bookmarks(1, 1)
        self.assertIs(navigation._click_bookmark_link(self.page, 1), False)
        self.assertEqual(self.page.url, 'https://pond.test/start')

    def test_waits_for_the_target_row_when_bookmarks_load_in_stages(self):
        self.show_bookmarks(2)
        self.page.evaluate("""() => setTimeout(() => {
            const tile = document.querySelector('.tile').cloneNode(true);
            tile.querySelector('.description').textContent = 'HO 1';
            tile.querySelector('a').href = '/pond-1';
            document.querySelector('.tiles').append(tile);
        }, 350)""")
        self.assertTrue(navigation._click_bookmark_link(self.page, 1))
        self.assertEqual(self.page.url, 'https://pond.test/pond-1')

    def test_unrecognized_bookmarks_layout_allows_ocr_fallback(self):
        self.page.set_content('<div>Canvas-only UI</div>')
        self.assertIsNone(navigation._click_bookmark_link(self.page, 1))

    def test_blocked_travel_does_not_count_as_arrival(self):
        self.show_bookmarks(1)
        self.page.locator('a').evaluate("el => el.onclick = event => event.preventDefault()")
        self.assertIs(navigation._click_bookmark_link(self.page, 1), False)
        self.assertEqual(self.page.url, 'https://pond.test/start')
