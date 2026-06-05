import unittest


class ImportCompatibilityTests(unittest.TestCase):
    def test_old_module_paths_still_import_during_transition(self):
        from investment_tool import capture_threads
        from investment_tool import hardcore_capture
        from investment_tool import manual_threads
        from investment_tool import market_prices
        from investment_tool import media_analysis
        from investment_tool import pipeline_orchestrator
        from investment_tool import vector_store_sync

        self.assertTrue(callable(capture_threads.main))
        self.assertTrue(callable(hardcore_capture.main))
        self.assertTrue(callable(manual_threads.main))
        self.assertTrue(callable(market_prices.main))
        self.assertTrue(callable(media_analysis.main))
        self.assertTrue(callable(pipeline_orchestrator.main))
        self.assertTrue(callable(vector_store_sync.main))

    def test_new_module_paths_import(self):
        from investment_tool.analysis import openai
        from investment_tool.context import descriptions, prices
        from investment_tool.presentation import indexes, threads
        from investment_tool.retrieval import legacy
        from investment_tool.rules import filters, tickers
        from investment_tool.runtime import paths
        from investment_tool.sources.articles import ingest
        from investment_tool.sources.screenshots import bundles, reconstruct
        from investment_tool.sources.x import api, capture, media, rebuild, store
        from investment_tool.workflow import storage

        self.assertTrue(hasattr(openai, "call_responses_json"))
        self.assertTrue(callable(paths.storage_paths))
        self.assertTrue(callable(prices.main))
        self.assertTrue(callable(descriptions.main))
        self.assertTrue(callable(indexes.render_all_indexes))
        self.assertTrue(callable(threads.render_thread_html))
        self.assertTrue(callable(legacy.main))
        self.assertTrue(callable(filters.primary_label))
        self.assertTrue(callable(tickers.extract_tickers))
        self.assertTrue(callable(ingest.main))
        self.assertTrue(callable(bundles.main))
        self.assertTrue(callable(reconstruct.build_reconstruction_prompt))
        self.assertTrue(callable(api.XClient))
        self.assertTrue(callable(capture.run_live_x_capture))
        self.assertTrue(callable(media.thread_local_media_paths))
        self.assertTrue(callable(rebuild.rebuild_from_raw_api))
        self.assertTrue(callable(store.rerender_cached_threads))
        self.assertTrue(callable(storage.main))


if __name__ == "__main__":
    unittest.main()
