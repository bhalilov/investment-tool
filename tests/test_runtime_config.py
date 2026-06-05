import json
import os
import tempfile
import unittest
from unittest.mock import patch

from investment_tool.runtime.config import (
    ai_api_key,
    default_feed_config,
    load_model_registry,
    load_pipeline_config,
    load_pipeline_registry,
    load_prompt,
    load_feed_modules,
    load_feed_rules,
    load_workflow_stages,
    resolve_ai_model_config,
    resolve_ai_model,
    load_x_feed_profile,
    project_path,
    read_json,
    feed_label,
)


class RuntimeConfigTests(unittest.TestCase):
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
        self.assertIn("descriptions", modules)
        self.assertIn("raw_api_rebuild", modules["x-capture"].supports)
        self.assertEqual(default_feed_config("x-capture"), modules["x-capture"].feed_config)

    def test_workflow_stages_are_discoverable_from_feed_registry(self):
        stages = load_workflow_stages()

        self.assertEqual(stages["x-capture"].runner, "x_action")
        self.assertEqual(stages["x-capture"].action, "x-capture")
        self.assertEqual(stages["prices"].entrypoint, "investment_tool.context.prices")
        self.assertEqual(stages["descriptions"].feed_config, default_feed_config("x-capture"))

    def test_ai_models_resolve_from_pipeline_registry(self):
        pipeline = load_pipeline_config("media_description")
        registry = load_model_registry()
        expected = registry["model_profiles"][pipeline["model_profile"]]["model"]
        resolved = resolve_ai_model_config("media_description")

        self.assertEqual(resolve_ai_model("media_description"), expected)
        self.assertEqual(resolved.model, expected)
        self.assertEqual(resolved.model_profile, "media_description")
        self.assertEqual(resolved.provider, "openai")
        self.assertEqual(resolved.api_base, "https://api.openai.com/v1")
        self.assertEqual(resolved.api_key_env, "OPENAI_API_KEY")
        self.assertEqual(resolve_ai_model("media_description", "override-model"), "override-model")

    def test_ai_model_profile_can_override_provider_connection(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = project_path(tmp)
            models = root / "models.json"
            pipelines = root / "pipelines.json"
            models.write_text(
                json.dumps(
                    {
                        "version": 1,
                        "provider": "openai",
                        "api_base": "https://api.openai.com/v1",
                        "api_key_env": "OPENAI_API_KEY",
                        "model_profiles": {
                            "premium_reasoning": {
                                "model": "provider/model-a",
                                "provider": "custom_provider",
                                "api_base": "https://provider.example/v1",
                                "api_key_env": "CUSTOM_AI_KEY",
                            }
                        },
                    }
                ),
                encoding="utf-8",
            )
            pipelines.write_text(
                json.dumps({"version": 1, "pipelines": [{"pipeline_id": "thread_pass1", "model_profile": "premium_reasoning"}]}),
                encoding="utf-8",
            )

            resolved = resolve_ai_model_config(
                "thread_pass1",
                model_registry_path=models,
                pipeline_registry_path=pipelines,
            )

        self.assertEqual(resolved.model, "provider/model-a")
        self.assertEqual(resolved.provider, "custom_provider")
        self.assertEqual(resolved.api_base, "https://provider.example/v1")
        self.assertEqual(resolved.api_key_env, "CUSTOM_AI_KEY")

    def test_ai_api_key_uses_resolved_profile_env_name(self):
        resolved = resolve_ai_model_config("media_description")

        with patch.dict(os.environ, {resolved.api_key_env: "test-key"}):
            self.assertEqual(ai_api_key(resolved), "test-key")

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
