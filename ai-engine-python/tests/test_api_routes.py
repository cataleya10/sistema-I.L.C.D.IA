import unittest
import asyncio
from unittest.mock import patch

from app.api.routes import online_learning_stats_endpoint


class ApiRoutesTests(unittest.TestCase):
    def test_online_learning_stats_endpoint_returns_payload(self):
        expected = {
            "totals": {"attempted": 7, "trained": 5, "skipped": 2},
            "recent_events": [],
        }
        with patch("app.api.routes.get_online_learning_stats", return_value=expected) as stats_mock:
            response = asyncio.run(online_learning_stats_endpoint(recent=3))

        self.assertEqual(response, expected)
        stats_mock.assert_called_once_with(recent=3)


if __name__ == "__main__":
    unittest.main()
