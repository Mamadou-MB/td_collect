import ipaddress
import json
import os
import pathlib
import re
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone


APIFY_API = "https://api.apify.com/v2"
MAX_RESULTS_PER_SOURCE = 50
IMAGE_KEYS = re.compile(
    r"(image|photo|picture|thumbnail|thumb|media|display)", re.IGNORECASE
)

SOURCES = {
    "google_maps": {
        "label": "Google Maps",
        "actor_id": "compass~crawler-google-places",
        "actor_env": "APIFY_ACTOR_GOOGLE_MAPS",
        "input_env": "APIFY_INPUT_GOOGLE_MAPS",
        "max_charge_usd": "0.50",
        "cost_hint": "plafond 0,50 $ par collecte",
        "default_input": {
            "searchStringsArray": ["restaurants"],
            "locationQuery": "Senegal",
            "maxCrawledPlacesPerSearch": MAX_RESULTS_PER_SOURCE,
            "language": "fr",
        },
    },
    "instagram": {
        "label": "Instagram",
        "actor_id": "apify~instagram-search-scraper",
        "actor_env": "APIFY_ACTOR_INSTAGRAM",
        "input_env": "APIFY_INPUT_INSTAGRAM",
        "max_charge_usd": "0.10",
        "cost_hint": "tarif gratuit affiché : 0,0027 $/résultat ; plafond 0,10 $ (environ 37 résultats au plus)",
        "default_input": {
            "search": "Dakar, Senegal",
            "searchType": "place",
            "searchLimit": MAX_RESULTS_PER_SOURCE,
        },
    },
    "youtube": {
        "label": "YouTube",
        "actor_id": "streamers~youtube-scraper",
        "actor_env": "APIFY_ACTOR_YOUTUBE",
        "input_env": "APIFY_INPUT_YOUTUBE",
        "max_charge_usd": "0.10",
        "cost_hint": "plafond 0,10 $ par collecte",
        "default_input": {
            "searchQueries": ["Sénégal Dakar"],
            "maxResults": MAX_RESULTS_PER_SOURCE,
        },
    },
    "x": {
        "label": "X",
        "actor_id": "apidojo~twitter-scraper-lite",
        "actor_env": "APIFY_ACTOR_X",
        "input_env": "APIFY_INPUT_X",
        "max_charge_usd": "0.10",
        "cost_hint": "plafond 0,10 $ par collecte",
        "default_input": {
            "searchTerms": ["Senegal OR Sénégal"],
            "maxItems": MAX_RESULTS_PER_SOURCE,
        },
    },
    "pinterest": {
        "label": "Pinterest",
        "actor_id": "epctex~pinterest-scraper",
        "actor_env": "APIFY_ACTOR_PINTEREST",
        "input_env": "APIFY_INPUT_PINTEREST",
        "max_charge_usd": "0.10",
        "cost_hint": "plafond 0,10 $ par collecte",
        "default_input": {
            "search": "Sénégal Dakar",
            "maxItems": MAX_RESULTS_PER_SOURCE,
            "getDetails": False,
        },
    },
}


def _https_url(value):
    if not isinstance(value, str):
        return None
    value = value.strip()
    try:
        parsed = urllib.parse.urlparse(value)
        hostname = parsed.hostname
        parsed.port
    except ValueError:
        return None
    if (
        parsed.scheme != "https"
        or not hostname
        or parsed.username
        or parsed.password
    ):
        return None
    try:
        address = ipaddress.ip_address(hostname)
    except ValueError:
        if (
            "." not in hostname
            or hostname.lower().endswith((".localhost", ".local", ".internal"))
        ):
            return None
    else:
        if not address.is_global:
            return None
    if not parsed.netloc:
        return None
    return value


def _image_urls(item):
    found = []

    def visit(value, key=""):
        if isinstance(value, dict):
            for child_key, child_value in value.items():
                visit(
                    child_value,
                    child_key if IMAGE_KEYS.search(child_key) else key,
                )
        elif isinstance(value, list):
            for child_value in value:
                visit(child_value, key)
        elif IMAGE_KEYS.search(key):
            url = _https_url(value)
            if url and url not in found:
                found.append(url)

    visit(item)
    return found


def _clean_text(value):
    if not isinstance(value, str):
        return ""
    value = re.sub(r"[\x00-\x1f\x7f]+", " ", value)
    return re.sub(r"\s+", " ", value).strip()


def _record_for_image(item, image_url, source):
    title = next(
        (
            item.get(key)
            for key in ("title", "name", "text", "caption", "description")
            if isinstance(item.get(key), str) and item.get(key).strip()
        ),
        "",
    )
    source_url = next(
        (
            _https_url(item.get(key))
            for key in ("url", "postUrl", "link", "videoUrl")
            if _https_url(item.get(key))
        ),
        "",
    )
    published_at = next(
        (
            item.get(key)
            for key in ("publishedAt", "timestamp", "date", "createdAt")
            if isinstance(item.get(key), str)
        ),
        "",
    )
    return {
        "source": source,
        "title": _clean_text(title)[:400],
        "source_url": source_url,
        "image_url": image_url,
        "published_at": _clean_text(published_at)[:80],
    }


def normalize_items(items, source, limit=MAX_RESULTS_PER_SOURCE):
    """Keep only safe HTTPS image references; never copy the image itself."""
    records = []
    seen = set()
    for item in items:
        if not isinstance(item, dict):
            continue
        for image_url in _image_urls(item):
            record = _record_for_image(item, image_url, source)
            identity = record["source_url"] or image_url
            if identity in seen:
                continue
            seen.add(identity)
            records.append(record)
            if len(records) >= limit:
                return records
    return records


def _actor_input(source_key):
    source = SOURCES[source_key]
    raw_input = os.environ.get(source["input_env"])
    if not raw_input:
        return source["default_input"]
    try:
        actor_input = json.loads(raw_input)
    except json.JSONDecodeError as error:
        raise ValueError(f"Le JSON de {source['input_env']} est invalide.") from error
    if not isinstance(actor_input, dict):
        raise ValueError(f"{source['input_env']} doit contenir un objet JSON.")
    for key in (
        "maxCrawledPlacesPerSearch",
        "maxItems",
        "maxResults",
        "maxTweets",
        "resultsLimit",
        "searchLimit",
        "limit",
    ):
        if isinstance(actor_input.get(key), (int, float)):
            actor_input[key] = min(max(int(actor_input[key]), 1), MAX_RESULTS_PER_SOURCE)
    return actor_input


def _run_actor(source_key, token):
    source = SOURCES[source_key]
    actor_id = (os.environ.get(source["actor_env"]) or source["actor_id"]).strip()
    if not actor_id:
        raise ValueError(f"Configurez {source['actor_env']} pour cette source.")

    actor_path = urllib.parse.quote(actor_id, safe="~")
    query = urllib.parse.urlencode(
        {
            "format": "json",
            "clean": "true",
            "limit": str(MAX_RESULTS_PER_SOURCE),
            "maxTotalChargeUsd": source["max_charge_usd"],
        }
    )
    url = f"{APIFY_API}/acts/{actor_path}/run-sync-get-dataset-items?{query}"
    body = json.dumps(_actor_input(source_key)).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=body,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=180) as response:
            data = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        raise RuntimeError(f"Apify a retourné le statut HTTP {error.code}.") from None
    except urllib.error.URLError:
        raise RuntimeError("Connexion à Apify impossible.") from None
    except TimeoutError:
        raise RuntimeError("La collecte a dépassé le délai d’attente.") from None
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise RuntimeError("La réponse d’Apify n’est pas un JSON valide.") from None
    if not isinstance(data, list):
        raise RuntimeError("L’acteur Apify n’a pas retourné une liste de résultats.")
    return normalize_items(data, source["label"])


def collect(source_keys):
    token = os.environ.get("APIFY_TOKEN", "").strip()
    if not token:
        raise ValueError("Configurez APIFY_TOKEN avant de lancer une collecte.")
    unknown_sources = set(source_keys) - SOURCES.keys()
    if unknown_sources:
        raise ValueError("Une source sélectionnée n’est pas prise en charge.")

    with ThreadPoolExecutor(max_workers=min(len(source_keys), 5) or 1) as executor:
        futures = {
            source_key: executor.submit(_run_actor, source_key, token)
            for source_key in source_keys
        }
        results = {}
        for source_key, future in futures.items():
            try:
                results[source_key] = {
                    "label": SOURCES[source_key]["label"],
                    "records": future.result(),
                    "error": None,
                }
            except (ValueError, RuntimeError) as error:
                results[source_key] = {
                    "label": SOURCES[source_key]["label"],
                    "records": [],
                    "error": str(error),
                }
    return results


def save_results(results, storage_path):
    storage_path = pathlib.Path(storage_path)
    storage_path.parent.mkdir(parents=True, exist_ok=True)
    existing = load_results(storage_path)
    for source_key, result in results.items():
        existing[source_key] = {
            **result,
            "collected_at": datetime.now(timezone.utc).isoformat(),
        }

    temporary_path = None
    try:
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            dir=storage_path.parent,
            delete=False,
        ) as temporary_file:
            temporary_path = pathlib.Path(temporary_file.name)
            json.dump(existing, temporary_file, ensure_ascii=False, indent=2)
        temporary_path.replace(storage_path)
    finally:
        if temporary_path and temporary_path.exists():
            temporary_path.unlink()
    return existing


def load_results(storage_path):
    try:
        with pathlib.Path(storage_path).open(encoding="utf-8") as data_file:
            results = json.load(data_file)
    except FileNotFoundError:
        return {}
    except (OSError, json.JSONDecodeError) as error:
        raise RuntimeError("Impossible de lire les données de collecte enregistrées.") from error
    if not isinstance(results, dict):
        raise RuntimeError("Le fichier de collecte a un format invalide.")
    return results
