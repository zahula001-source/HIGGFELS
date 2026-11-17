import sys
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.services import video_history


class VideoHistoryZoomTests(unittest.TestCase):
    def test_sets_chrome_zoom_to_80_percent(self):
        page = Mock()

        video_history.set_status_zoom_80(page)

        self.assertEqual(
            [call.args[0] for call in page.keyboard.press.call_args_list],
            ["Control+0", "Control+-", "Control+-"],
        )

    def test_confirm_generation_uses_80_percent_zoom_only_after_status_is_missing(self):
        page = Mock()
        with patch.object(video_history, "wait_for_generation", side_effect=[Exception(), Exception(), None]), \
                patch.object(video_history, "refresh_video_history") as refresh, \
                patch.object(video_history, "set_status_zoom_80") as set_zoom:
            video_history.confirm_generation(page)

        refresh.assert_called_once_with(page)
        set_zoom.assert_called_once_with(page)

        with patch.object(video_history, "wait_for_generation") as wait, \
                patch.object(video_history, "set_status_zoom_80") as set_zoom:
            video_history.confirm_generation(page)

        wait.assert_called_once_with(page)
        set_zoom.assert_not_called()


if __name__ == "__main__":
    unittest.main()
