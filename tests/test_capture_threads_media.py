import unittest

from investment_tool import capture_threads


class CaptureThreadMediaTests(unittest.TestCase):
    def test_thread_local_media_paths_keeps_only_referenced_media(self):
        tweets = [
            {"attachments": {"media_keys": ["img_1"]}},
            {"attachments": {"media_keys": ["img_2"]}},
            {"attachments": {"media_keys": []}},
        ]
        global_media_paths = {
            "img_1": "/media/img_1.jpg",
            "img_2": "/media/img_2.jpg",
            "img_3": "/media/img_3.jpg",
        }

        self.assertEqual(
            capture_threads.thread_local_media_paths(global_media_paths, tweets),
            {
                "img_1": "/media/img_1.jpg",
                "img_2": "/media/img_2.jpg",
            },
        )

    def test_thread_local_media_paths_empty_for_thread_without_media(self):
        tweets = [{"text": "No images here."}]
        global_media_paths = {"img_1": "/media/img_1.jpg"}

        self.assertEqual(capture_threads.thread_local_media_paths(global_media_paths, tweets), {})

    def test_thread_local_media_filters_metadata_too(self):
        tweets = [{"attachments": {"media_keys": ["img_2"]}}]
        global_media = {
            "img_1": {"type": "photo", "url": "wrong"},
            "img_2": {"type": "photo", "url": "right"},
        }

        self.assertEqual(
            capture_threads.thread_local_media(global_media, tweets),
            {"img_2": {"type": "photo", "url": "right"}},
        )

    def test_non_photo_media_gets_placeholder_tags(self):
        tweets = [{"attachments": {"media_keys": ["13_v", "13_g", "3_p"]}}]
        media = {
            "13_v": {"type": "video"},
            "13_g": {"type": "animated_gif"},
            "3_p": {"type": "photo"},
        }

        placeholders = capture_threads.non_photo_media_placeholders(tweets, media)
        tags = capture_threads.media_placeholder_tags(tweets, media)

        self.assertEqual([item["type"] for item in placeholders], ["animated_gif", "video"])
        self.assertEqual(tags, ["VIDEO_PRESENT", "ANIMATED_GIF_PRESENT"])


if __name__ == "__main__":
    unittest.main()
