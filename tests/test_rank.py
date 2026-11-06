"""Offline checks for the ranking window hint and tie handling."""
from contextlib import redirect_stdout
from io import StringIO
import unittest

import rank


class FakeGitHub:
    def __init__(self, stars):
        self.items = [dict(full_name=f"owner/repo{i:04d}", stargazers_count=stars[i])
                      for i in range(len(stars))]
        self.calls = 0

    def search_repos(self, q, page=1, per_page=100):
        self.calls += 1
        if q.startswith("stars:>="):
            floor = int(q[8:])
            matches = [x for x in self.items if x["stargazers_count"] >= floor]
        elif q.startswith("stars:>"):
            floor = int(q[7:])
            matches = [x for x in self.items if x["stargazers_count"] > floor]
        else:
            floor, ceiling = map(int, q[6:].split(".."))
            matches = [x for x in self.items if floor <= x["stargazers_count"] <= ceiling]
        matches.sort(key=lambda x: (-x["stargazers_count"], x["full_name"]))
        start = (page - 1) * per_page
        return {"incomplete_results": False, "total_count": len(matches),
                "items": matches[start:start + per_page]}


class RankingWindowTests(unittest.TestCase):
    def test_concurrent_pages_are_reassembled_and_missing_pages_fail(self):
        stars = [100000 - i * 10 for i in range(250)]
        gh = FakeGitHub(stars)
        items = rank.fetch_window(gh, 1, None)
        self.assertEqual([x['full_name'] for x in items],
                         [f'owner/repo{i:04d}' for i in range(250)])

        class MissingPage(FakeGitHub):
            def search_repos(self, q, page=1, per_page=100):
                result = super().search_repos(q, page, per_page)
                if page == 2:
                    result['items'] = []
                return result

        with self.assertRaisesRegex(RuntimeError, '分页缺项'):
            rank.fetch_window(MissingPage(stars), 1, None)

    def test_previous_snapshot_hint_reduces_requests_without_changing_top_k(self):
        stars = [100000 - i * 10 for i in range(2400)]
        previous = [dict(stars=s - 50) for s in stars]
        plain, hinted = FakeGitHub(stars), FakeGitHub(stars)
        with redirect_stdout(StringIO()):
            expected = rank.fetch_top(plain, 2000)
            actual = rank.fetch_top(hinted, 2000, previous)
        self.assertEqual(actual, expected)
        self.assertLess(hinted.calls, plain.calls)

    def test_stale_hints_and_equal_stars_still_yield_unique_ranked_repos(self):
        stars = [100000 - (i // 3) * 20 for i in range(2400)]
        with redirect_stdout(StringIO()):
            expected = rank.fetch_top(FakeGitHub(stars), 2000)
        for offset in (-10000, 10000):
            previous = [dict(stars=s + offset) for s in stars]
            with redirect_stdout(StringIO()):
                actual = rank.fetch_top(FakeGitHub(stars), 2000, previous)
            self.assertEqual(actual, expected)
            self.assertEqual(len({x["name"] for x in actual}), 2000)


if __name__ == "__main__":
    unittest.main()
