import subprocess
import unittest
from unittest.mock import Mock, patch

from app.services.hma_vpn import rotate_hma_random_country


class HmaVpnRetryTests(unittest.TestCase):
    def test_rotate_hma_success_first_attempt(self):
        fake_proc = Mock(
            returncode=0,
            stdout="Quoc gia ngau nhien: Japan\nIP moi: 123.45.67.89\n",
            stderr="",
        )
        with patch("subprocess.run", return_value=fake_proc) as mock_run:
            result = rotate_hma_random_country(timeout=10, max_attempts=2)
            self.assertEqual(result["status"], "ok")
            self.assertEqual(result["ip"], "123.45.67.89")
            self.assertEqual(result["country"], "Japan")
            self.assertEqual(mock_run.call_count, 1)

    def test_rotate_hma_retries_on_first_failure_and_succeeds_on_second(self):
        fail_proc = Mock(
            returncode=1,
            stdout="Loi ket noi VPN\n",
            stderr="Error: connection failed",
        )
        success_proc = Mock(
            returncode=0,
            stdout="Quoc gia ngau nhien: Germany\nIP moi: 98.76.54.32\n",
            stderr="",
        )
        with patch("subprocess.run", side_effect=[fail_proc, success_proc]) as mock_run, \
             patch("time.sleep"):
            result = rotate_hma_random_country(timeout=10, max_attempts=2)
            self.assertEqual(result["status"], "ok")
            self.assertEqual(result["ip"], "98.76.54.32")
            self.assertEqual(result["country"], "Germany")
            self.assertEqual(mock_run.call_count, 2)

    def test_rotate_hma_retries_when_ip_unchanged_on_first_attempt(self):
        unchanged_proc = Mock(
            returncode=0,
            stdout="IP hien tai: 1.1.1.1 (doi xac nhan tren app hoac thu lai)\n",
            stderr="",
        )
        success_proc = Mock(
            returncode=0,
            stdout="Quoc gia ngau nhien: Singapore\nIP moi: 202.1.2.3\n",
            stderr="",
        )
        with patch("subprocess.run", side_effect=[unchanged_proc, success_proc]) as mock_run, \
             patch("time.sleep"):
            result = rotate_hma_random_country(timeout=10, max_attempts=2)
            self.assertEqual(result["status"], "ok")
            self.assertEqual(result["ip"], "202.1.2.3")
            self.assertEqual(result["country"], "Singapore")
            self.assertEqual(mock_run.call_count, 2)

    def test_rotate_hma_raises_after_two_failed_attempts(self):
        fail_proc = Mock(
            returncode=1,
            stdout="Loi ket noi\n",
            stderr="",
        )
        with patch("subprocess.run", side_effect=[fail_proc, fail_proc]) as mock_run, \
             patch("time.sleep"):
            with self.assertRaises(RuntimeError):
                rotate_hma_random_country(timeout=10, max_attempts=2)
            self.assertEqual(mock_run.call_count, 2)


if __name__ == "__main__":
    unittest.main()
