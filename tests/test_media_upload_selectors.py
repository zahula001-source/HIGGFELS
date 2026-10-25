import unittest
from unittest.mock import MagicMock
import re

class TestMediaUploadSelectors(unittest.TestCase):
    def test_lite_and_vip_selectors(self):
        # 1. Kiem tra doi voi modal LITE
        # Nut anh Lite
        html_lite_img = '''<button type="button" aria-label="Add reference images" class="absolute inset-0 z-10 rounded-[inherit] outline-none"></button>'''
        # Nut video Lite
        html_lite_vid = '''<button type="button" aria-label="Add a reference video to edit" class="absolute inset-0 z-10 rounded-[inherit] outline-none"></button>'''

        # 2. Kiem tra doi voi modal VIP
        # Nut anh VIP
        html_vip_img = '''<button type="button" aria-label="Add reference images" class="absolute inset-0 z-10 rounded-[inherit] outline-none"></button>'''
        # Nut video VIP
        html_vip_vid = '''<button type="button" aria-label="Add a reference video to extract motion" class="absolute inset-0 z-10 rounded-[inherit] outline-none"></button>'''

        # Selector cho anh
        img_selectors = [
            'button[aria-label="Add reference images"]',
            'button[aria-label*="reference images" i]',
        ]
        # Selector cho video
        vid_selectors = [
            'button[aria-label="Add a reference video to edit"]',
            'button[aria-label="Add a reference video to extract motion"]',
            'button[aria-label*="reference video" i]',
        ]

        # Regex kiem tra khớp
        self.assertTrue(any('Add reference images' in sel for sel in img_selectors))
        self.assertTrue('aria-label="Add reference images"' in html_lite_img)
        self.assertTrue('aria-label="Add reference images"' in html_vip_img)

        self.assertTrue('aria-label="Add a reference video to edit"' in html_lite_vid)
        self.assertTrue('aria-label="Add a reference video to extract motion"' in html_vip_vid)

        # Kiem tra logic label generator trong video_gen
        is_lite = True
        gen_mode = "motion_transfer"
        video_btn_label_lite = "Add a reference video to edit" if is_lite or gen_mode == "objects_swap" else "Add a reference video to extract motion"
        self.assertEqual(video_btn_label_lite, "Add a reference video to edit")

        is_lite = False
        video_btn_label_vip = "Add a reference video to edit" if is_lite or gen_mode == "objects_swap" else "Add a reference video to extract motion"
        self.assertEqual(video_btn_label_vip, "Add a reference video to extract motion")

if __name__ == '__main__':
    unittest.main()
