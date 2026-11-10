import os
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from data_pipeline import (
    MAX_RESULTS_PER_SOURCE,
    _actor_input,
    _run_actor,
    load_results,
    normalize_items,
    save_results,
)
import app as app_module
from export_collection import clean_csv_rows

app = app_module.app


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

    def test_actor_input_caps_result_count_at_fifty(self):
        with patch.dict(
            "os.environ",
            {"APIFY_INPUT_INSTAGRAM": json.dumps({"searchLimit": 250})},
            clear=False,
        ):
            self.assertEqual(
                _actor_input("instagram")["searchLimit"],
                MAX_RESULTS_PER_SOURCE,
            )
        self.assertEqual(
            _actor_input("instagram")["search"],
            "Dakar, Senegal",
        )
        self.assertEqual(_actor_input("instagram")["searchType"], "place")

    def test_normalize_items_deduplicates_repeated_publication_urls(self):
        items = [
            {
                "title": "Post",
                "url": "https://x.com/account/status/123",
                "imageUrl": "https://cdn.example/one.jpg",
            },
            {
                "title": "Post duplicate",
                "url": "https://x.com/account/status/123",
                "imageUrl": "https://cdn.example/two.jpg",
            },
        ]
        self.assertEqual(len(normalize_items(items, "X")), 1)

    def test_clean_csv_rows_normalizes_dates_and_removes_duplicates(self):
        rows = [
            {
                "source": " X ",
                "titre": "  A post\n with spacing ",
                "date_publication": "Tue Nov 10 13:58:21 +0000 2026",
                "url_publication": "https://x.com/account/status/123",
                "url_image": "https://cdn.example/one.jpg",
                "capture_locale": "",
            },
            {
                "source": "X",
                "titre": "Duplicate",
                "date_publication": "",
                "url_publication": "https://x.com/account/status/123",
                "url_image": "https://cdn.example/two.jpg",
                "capture_locale": "",
            },
            {
                "source": "Pinterest",
                "titre": "=1+1",
                "url_publication": "javascript:alert(1)",
                "url_image": "http://cdn.example/image.jpg",
            },
            {
                "source": "Pinterest",
                "titre": "=1+1",
                "url_publication": "https://pinterest.com/pin/123",
                "url_image": "https://cdn.example/image.jpg",
            },
        ]
        cleaned = clean_csv_rows(rows)

        self.assertEqual(len(cleaned), 2)
        self.assertEqual(cleaned[0]["titre"], "A post with spacing")
        self.assertEqual(cleaned[0]["date_publication"], "2026-11-10T13:58:21Z")
        self.assertEqual(cleaned[0]["capture_locale"], "")
        self.assertEqual(cleaned[1]["titre"], "'=1+1")

    def test_clean_csv_rows_drops_missing_local_capture_references(self):
        row = {
            "source": "YouTube",
            "titre": "Video",
            "url_publication": "https://youtube.com/watch?v=123",
            "url_image": "https://i.ytimg.com/video.jpg",
            "capture_locale": "captures/youtube/missing.jpg",
        }
        with tempfile.TemporaryDirectory() as directory:
            cleaned = clean_csv_rows([row], Path(directory))
        self.assertEqual(cleaned[0]["capture_locale"], "")

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
        self.assertIn("limit=50", request.full_url)

    def test_x_uses_lite_actor_by_default(self):
        response = unittest.mock.MagicMock()
        response.__enter__.return_value.read.return_value = b"[]"
        with patch.dict(os.environ, {"APIFY_ACTOR_X": ""}, clear=False), patch(
            "data_pipeline.urllib.request.urlopen",
            return_value=response,
        ) as urlopen:
            self.assertEqual(_run_actor("x", "test-secret-token"), [])
        self.assertIn(
            "/acts/apidojo~twitter-scraper-lite/",
            urlopen.call_args.args[0].full_url,
        )

    def test_instagram_uses_search_actor_by_default(self):
        response = unittest.mock.MagicMock()
        response.__enter__.return_value.read.return_value = b"[]"
        with patch.dict(os.environ, {"APIFY_ACTOR_INSTAGRAM": ""}, clear=False), patch(
            "data_pipeline.urllib.request.urlopen",
            return_value=response,
        ) as urlopen:
            self.assertEqual(_run_actor("instagram", "test-secret-token"), [])
        self.assertIn(
            "/acts/apify~instagram-search-scraper/",
            urlopen.call_args.args[0].full_url,
        )

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
            with patch.dict(
                os.environ,
                {"APIFY_TOKEN": "", "COLLECT_ADMIN_PASSWORD": ""},
                clear=False,
            ):
                response = client.post(
                    "/collecte",
                    data={"sources": ["instagram"], "confirm_costs": "yes"},
                )
            self.assertEqual(response.status_code, 400)
            self.assertIn("COLLECT_ADMIN_PASSWORD", response.get_data(as_text=True))

    def test_collection_requires_admin_password(self):
        app.config["TESTING"] = True
        with app.test_client() as client, patch.dict(
            os.environ,
            {"COLLECT_ADMIN_PASSWORD": "expected-password"},
            clear=False,
        ):
            response = client.post(
                "/collecte",
                data={
                    "sources": ["instagram"],
                    "confirm_costs": "yes",
                    "collect_password": "wrong-password",
                },
            )
        self.assertEqual(response.status_code, 400)
        self.assertIn("Mot de passe de collecte incorrect.", response.get_data(as_text=True))

    def test_health_check(self):
        app.config["TESTING"] = True
        with app.test_client() as client:
            response = client.get("/healthz")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json(), {"status": "ok"})

    def test_dashboard_uses_public_seed_and_serves_public_csv(self):
        app.config["TESTING"] = True
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            seed_file = root / "collectes.json"
            csv_file = root / "donnees_scrappees.csv"
            seed_file.write_text(
                json.dumps(
                    {
                        "youtube": {
                            "label": "YouTube",
                            "records": [
                                {
                                    "title": "Public test result",
                                    "image_url": "https://i.ytimg.com/test.jpg",
                                    "source_url": "https://youtube.com/watch?v=test",
                                    "published_at": "",
                                }
                            ],
                        }
                    }
                ),
                encoding="utf-8",
            )
            csv_file.write_text("source,titre\nYouTube,Public test result\n", encoding="utf-8")
            with patch.object(app_module, "COLLECTIONS_FILE", root / "missing.json"), patch.object(
                app_module, "PUBLIC_SEED_FILE", seed_file
            ), patch.object(app_module, "PUBLIC_CSV_FILE", csv_file):
                with app.test_client() as client:
                    dashboard = client.get("/")
                    download = client.get("/donnees_scrappees.csv")
                    download_data = download.data
                    dashboard.close()
                    download.close()

        self.assertEqual(dashboard.status_code, 200)
        self.assertIn(b"Public test result", dashboard.data)
        self.assertIn(b"Explorer les r", dashboard.data)
        self.assertIn(b"previous-page", dashboard.data)
        self.assertIn(b"<strong>50</strong>", dashboard.data)
        self.assertIn(b"Vos sources", dashboard.data)
        self.assertIn(b"Le S\xc3\xa9n\xc3\xa9gal, en donn\xc3\xa9es.", dashboard.data)
        self.assertEqual(download.status_code, 200)
        self.assertIn(b"YouTube,Public test result", download_data)

    def test_dashboard_links_to_report_and_executable_notebook(self):
        app.config["TESTING"] = True
        with app.test_client() as client:
            dashboard = client.get("/")
            report = client.get("/rapport")
            notebook = client.get("/notebook-pretraitement.ipynb")

        self.assertEqual(dashboard.status_code, 200)
        self.assertIn(b"/rapport", dashboard.data)
        self.assertIn(b"/notebook-pretraitement.ipynb", dashboard.data)
        self.assertEqual(report.status_code, 200)
        self.assertIn(b"<strong>31</strong>", report.data)
        self.assertIn("répétitions retirées".encode("utf-8"), report.data)
        self.assertEqual(notebook.status_code, 200)
        self.assertIn("application/x-ipynb+json", notebook.content_type)
        notebook_content = json.loads(notebook.data)
        code_cells = [
            cell for cell in notebook_content["cells"] if cell["cell_type"] == "code"
        ]
        self.assertGreaterEqual(len(code_cells), 3)
        dashboard.close()
        report.close()
        notebook.close()

    def test_normalize_items_uses_fifty_result_default_cap(self):
        items = [{"imageUrl": f"https://cdn.example/image-{index}.jpg"} for index in range(60)]
        records = normalize_items(items, "YouTube")
        self.assertEqual(len(records), 50)


if __name__ == "__main__":
    unittest.main()
