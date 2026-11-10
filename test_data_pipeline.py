import os
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from data_pipeline import (
    _actor_input,
    _run_actor,
    load_results,
    normalize_items,
    save_results,
)
from app import app


class DataPipelineTests(unittest.TestCase):
    def test_normalize_items_keeps_unique_https_images_and_caps_results(self):
        items = [
            {
                "title": "Public place",
                "image": {"url": "https://cdn.example/image-1.jpg"},
                "thumbnailUrl": "http://cdn.example/not-secure.jpg",
            },
            {"images": ["https://cdn.example/image-1.jpg", "https://cdn.example/image-2.jpg"]},
            {"imageUrl": "https://cdn.example/image-3.jpg"},
        ]

        records = normalize_items(items, "Google Maps", limit=2)

        self.assertEqual(len(records), 2)
        self.assertEqual(
            [record["image_url"] for record in records],
            [
                "https://cdn.example/image-1.jpg",
                "https://cdn.example/image-2.jpg",
            ],
        )
        self.assertTrue(all(record["source"] == "Google Maps" for record in records))
        invalid_urls = normalize_items(
            [{"imageUrl": "https://127.0.0.1/image.jpg"}], "Instagram"
        )
        self.assertEqual(invalid_urls, [])
        instagram_records = normalize_items(
            [{"displayUrl": "https://cdn.example/instagram-post.jpg"}],
            "Instagram",
        )
        self.assertEqual(
            instagram_records[0]["image_url"],
            "https://cdn.example/instagram-post.jpg",
        )

    def test_actor_input_caps_result_count_at_ten(self):
        with patch.dict(
            "os.environ",
            {"APIFY_INPUT_INSTAGRAM": json.dumps({"maxItems": 250})},
            clear=False,
        ):
            self.assertEqual(_actor_input("instagram")["maxItems"], 10)

    def test_actor_token_uses_authorization_header(self):
        response = unittest.mock.MagicMock()
        response.__enter__.return_value.read.return_value = b"[]"
        with patch.dict(
            os.environ,
            {"APIFY_ACTOR_INSTAGRAM": "my-account~my-actor"},
            clear=False,
        ), patch("data_pipeline.urllib.request.urlopen", return_value=response) as urlopen:
            self.assertEqual(_run_actor("instagram", "test-secret-token"), [])

        request = urlopen.call_args.args[0]
        self.assertNotIn("test-secret-token", request.full_url)
        self.assertEqual(request.get_header("Authorization"), "Bearer test-secret-token")
        self.assertIn("maxTotalChargeUsd=0.10", request.full_url)

    def test_save_and_load_results(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "instance" / "collectes.json"
            expected = {"instagram": {"label": "Instagram", "records": [], "error": None}}

            save_results(expected, path)

            self.assertEqual(load_results(path)["instagram"]["records"], [])

    def test_collection_page_and_empty_selection(self):
        app.config["TESTING"] = True
        with app.test_client() as client:
            self.assertEqual(client.get("/collecte").status_code, 200)
            response = client.post("/collecte", data={"sources": []})
            self.assertEqual(response.status_code, 400)
            self.assertIn("Sélectionnez au moins une source.", response.get_data(as_text=True))
            with patch.dict(os.environ, {"APIFY_TOKEN": ""}):
                response = client.post(
                    "/collecte",
                    data={"sources": ["instagram"], "confirm_costs": "yes"},
                )
            self.assertEqual(response.status_code, 400)
            self.assertIn("Configurez APIFY_TOKEN", response.get_data(as_text=True))


if __name__ == "__main__":
    unittest.main()
