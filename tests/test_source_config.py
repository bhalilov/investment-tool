import unittest

from investment_tool.source_config import (
    load_model_registry,
    load_pipeline_registry,
    load_prompt,
    load_source_modules,
    load_source_rules,
    load_x_source_profile,
    project_path,
    read_json,
    source_label,
)


class SourceConfigTests(unittest.TestCase):
    def test_x_source_profile_loads_default_account(self):
        profile = load_x_source_profile()

        self.assertEqual(profile.platform, "x")
        self.assertEqual(profile.module, "x_capture")
        self.assertTrue(profile.username)
        self.assertTrue(profile.user_id)
        self.assertIn("@", source_label(profile))

    def test_source_rules_load_from_profile_paths(self):
        profile = load_x_source_profile()
        thread_rules, media_rules = load_source_rules(profile)

        self.assertIn("thread_type_labels", thread_rules)
        self.assertIn("placeholder_types", media_rules)
        self.assertIn("video", media_rules["placeholder_types"])

    def test_source_modules_are_discoverable(self):
        modules = load_source_modules()

        self.assertIn("x_capture", modules)
        self.assertIn("market_prices", modules)
        self.assertIn("raw_api_rebuild", modules["x_capture"].supports)

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
