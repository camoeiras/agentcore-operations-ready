import unittest
from app import environment


class EnvironmentTest(unittest.TestCase):
    def setUp(self):
        environment.reset()

    def test_restart_and_verify(self):
        self.assertEqual(environment.snapshot("checkout-api")["status"], "DOWN")
        self.assertEqual(environment.restart("checkout-api")["action"], "restarted")
        self.assertEqual(environment.snapshot("checkout-api")["status"], "HEALTHY")
        self.assertEqual(environment.restart("checkout-api")["action"], "skipped")

    def test_unknown_service(self):
        self.assertIn("error", environment.restart("unknown"))


if __name__ == "__main__":
    unittest.main()
