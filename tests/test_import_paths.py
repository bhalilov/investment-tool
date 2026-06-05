import unittest


class ImportPathsTests(unittest.TestCase):
    def test_current_module_paths_import(self):
        from investment_tool.analysis import openai
        from investment_tool.context import descriptions, prices
        from investment_tool.presentation import indexes, threads
        from investment_tool.rules import filters, tickers
        from investment_tool.runtime import paths
        from investment_tool.feeds.articles import ingest
        from investment_tool.feeds.screenshots import bundles, reconstruct
        from investment_tool.feeds.x import api, capture, jobs, media, rebuild, store
        from investment_tool.workflow import run

        self.assertTrue(hasattr(openai, "call_responses_json"))
        self.assertTrue(callable(paths.storage_paths))
        self.assertTrue(callable(prices.main))
        self.assertTrue(callable(descriptions.main))
        self.assertTrue(callable(indexes.render_all_indexes))
        self.assertTrue(callable(threads.render_thread_html))
        self.assertTrue(callable(filters.primary_label))
        self.assertTrue(callable(tickers.extract_tickers))
        self.assertTrue(callable(ingest.main))
        self.assertTrue(callable(bundles.main))
        self.assertTrue(callable(reconstruct.build_reconstruction_prompt))
        self.assertTrue(callable(api.XClient))
        self.assertTrue(callable(capture.run_live_x_capture))
        self.assertTrue(callable(jobs.main))
        self.assertTrue(callable(media.thread_local_media_paths))
        self.assertTrue(callable(rebuild.rebuild_from_raw_api))
        self.assertTrue(callable(store.rerender_cached_threads))
        self.assertTrue(callable(run.run_workflow))


if __name__ == "__main__":
    unittest.main()
