import scena_test_isolation  # noqa: F401
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import server.app
from fastapi.testclient import TestClient
from server.app_deps import HTTPException
from server.modules import huggingface_models as models


class HuggingFaceSearchOrderTests(unittest.TestCase):
    def setUp(self):
        models.HF_SEARCH_CACHE.clear()
        self.addCleanup(models.HF_SEARCH_CACHE.clear)
        platform = patch.object(models, "WINDOWS_MODEL_CATALOG", True)
        platform.start()
        self.addCleanup(platform.stop)

    def test_rank_is_requested_before_limit_and_is_part_of_cache_key(self):
        with patch.object(models, "HfApi") as api:
            api.return_value.list_models.return_value = []
            for order, expected in [("downloads", "downloads"), ("likes", "likes"), ("name", "downloads"), ("default", None)]:
                models.search_huggingface_models("gemma", ["publisher:org"], order)
                self.assertEqual(api.return_value.list_models.call_args.kwargs["sort"], expected)
                self.assertEqual(api.return_value.list_models.call_args.kwargs["limit"], 30)
            self.assertEqual(api.return_value.list_models.call_count, 4)
            models.search_huggingface_models("gemma", ["publisher:org"], "likes")
            self.assertEqual(api.return_value.list_models.call_count, 4)

    def test_name_order_is_alphabetical_by_model_name(self):
        items = [SimpleNamespace(id=name, tags=["gguf"], library_name=None, downloads=1, gated=False)
                 for name in ["a/Zulu", "z/alpha", "a/Beta"]]
        with patch.object(models, "HfApi") as api:
            api.return_value.list_models.return_value = items
            result = models.search_huggingface_models("model", order="name")
        self.assertEqual([item["repoId"] for item in result["models"]], ["z/alpha", "a/Beta", "a/Zulu"])

    def test_http_defaults_to_downloads_and_accepts_popularity(self):
        with patch.object(models, "HfApi") as api:
            api.return_value.list_models.return_value = []
            client = TestClient(server.app.app)
            self.assertEqual(client.get("/api/llm/huggingface/search").status_code, 200)
            self.assertEqual(api.return_value.list_models.call_args.kwargs["sort"], "downloads")
            self.assertEqual(client.get("/api/llm/huggingface/search?order=likes").status_code, 200)
            self.assertEqual(api.return_value.list_models.call_args.kwargs["sort"], "likes")
            self.assertEqual(client.get("/api/llm/huggingface/search?order=invalid").status_code, 422)

    def test_invalid_order_does_not_contact_hub(self):
        with patch.object(models, "HfApi") as api, self.assertRaises(HTTPException):
            models.search_huggingface_models("model", order="invalid")
        api.assert_not_called()
