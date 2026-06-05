import unittest

from investment_tool.runtime.config import (
    load_model_registry,
    load_pipeline_registry,
    load_prompt,
    load_feed_modules,
    load_feed_rules,
    load_x_feed_profile,
    project_path,
    read_json,
    feed_label,
)


class FeedConfigTests(unittest.TestCase):
    def test_x_feed_profile_loads_default_account(self):
        profile = load_x_feed_profile()

        self.assertEqual(profile.platform, "x")
        self.assertEqual(profile.module, "x-capture")
        self.assertTrue(profile.username)
        self.assertTrue(profile.user_id)
        self.assertIn("@", feed_label(profile))

    def test_feed_rules_load_from_profile_paths(self):
        profile = load_x_feed_profile()
        thread_rules, media_rules = load_feed_rules(profile)

        self.assertIn("thread_type_labels", thread_rules)
        self.assertIn("placeholder_types", media_rules)
        self.assertIn("video", media_rules["placeholder_types"])

    def test_feed_modules_are_discoverable(self):
        modules = load_feed_modules()

        self.assertIn("x-capture", modules)
        self.assertIn("prices", modules)
        self.assertIn("raw_api_rebuild", modules["x-capture"].supports)

    def test_configured_pipeline_prompts_and_schemas_exist(self):
        registry = load_pipeline_registry()
        load_model_registry()

        for pipeline in registry["pipelines"]:
            for prompt_key in ("prompt", "system_prompt", "user_prompt"):
                if prompt_key in pipeline:
                    prompt = load_prompt(pipeline[prompt_key])
                    self.assertTrue(prompt["text"].strip(), pipeline[prompt_key])
            if "schema" in pipeline:
                schema_path = project_path(pipeline["schema"])
                self.assertTrue(schema_path.exists(), pipeline["schema"])
                schema = read_json(schema_path)
                self.assertEqual(schema.get("type"), "object")


if __name__ == "__main__":
    unittest.main()
