import csv
import html
import json
import pathlib
import re
import urllib.error
import urllib.parse
import urllib.request

from data_pipeline import SOURCES, _https_url


MAX_IMAGES_PER_SOURCE = 10
MAX_IMAGE_BYTES = 5 * 1024 * 1024
ALLOWED_IMAGE_HOSTS = {
    "google_maps": ("googleusercontent.com", "gstatic.com"),
    "instagram": ("cdninstagram.com", "fbcdn.net"),
    "youtube": ("ytimg.com", "ggpht.com"),
    "x": ("twimg.com",),
    "pinterest": ("pinimg.com",),
}
IMAGE_EXTENSIONS = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
    "image/gif": ".gif",
}


class NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, file_pointer, code, message, headers, new_url):
        return None


def _download_image(source_key, image_url, output_path):
    if not _https_url(image_url):
        return None
    host = urllib.parse.urlparse(image_url).hostname or ""
    if not any(
        host == domain or host.endswith(f".{domain}")
        for domain in ALLOWED_IMAGE_HOSTS[source_key]
    ):
        return None

    opener = urllib.request.build_opener(NoRedirectHandler)
    request = urllib.request.Request(
        image_url,
        headers={"User-Agent": "SenegalPublicDataCourseProject/1.0"},
    )
    try:
        with opener.open(request, timeout=15) as response:
            content_type = response.headers.get_content_type()
            extension = IMAGE_EXTENSIONS.get(content_type)
            if not extension:
                return None
            content_length = response.headers.get("Content-Length")
            if content_length and int(content_length) > MAX_IMAGE_BYTES:
                return None
            image_data = response.read(MAX_IMAGE_BYTES + 1)
            if len(image_data) > MAX_IMAGE_BYTES:
                return None
    except (urllib.error.URLError, TimeoutError, ValueError, OSError):
        return None

    output_path = output_path.with_suffix(extension)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(image_data)
    return output_path


def _write_dashboard(output_dir, results, rows, capture_paths):
    source_sections = []
    counts = {}
    for source_key, result in results.items():
        records = result.get("records") or []
        label = result.get("label") or SOURCES.get(source_key, {}).get("label", source_key)
        counts[label] = len(records)
        cards = []
        for index, record in enumerate(records, start=1):
            image_path = capture_paths.get((source_key, index))
            image_html = (
                f'<a href="{html.escape(image_path, quote=True)}">'
                f'<img src="{html.escape(image_path, quote=True)}" alt="Image {index} — {html.escape(label, quote=True)}" loading="lazy"></a>'
                if image_path
                else (
                    f'<a href="{html.escape(record.get("image_url", ""), quote=True)}">'
                    '<span class="no-image">Image non archivée localement</span></a>'
                )
            )
            title = html.escape(record.get("title") or "Sans titre")
            source_url = record.get("source_url") or ""
            source_link = (
                f'<a href="{html.escape(source_url, quote=True)}" '
                'target="_blank" rel="noopener noreferrer">Publication source</a>'
                if source_url
                else ""
            )
            cards.append(
                f'<article class="card">{image_html}<div class="card-body">'
                f'<h3>{title}</h3><p>{html.escape(record.get("published_at") or "")}</p>'
                f'{source_link}</div></article>'
            )
        warning = (
            f'<p class="warning">{html.escape(str(result["error"]))}</p>'
            if result.get("error")
            else ""
        )
        source_sections.append(
            f'<section><h2>{html.escape(label)} <span>{len(records)} résultat(s)</span></h2>'
            f'{warning}<div class="grid">{"".join(cards) or "<p>Aucune image trouvée pour cette source.</p>"}</div></section>'
        )

    max_count = max(counts.values(), default=1) or 1
    bars = "".join(
        f'<div class="bar-row"><span>{html.escape(label)}</span>'
        f'<div class="bar"><i style="width:{count / max_count * 100:.0f}%"></i></div>'
        f'<b>{count}</b></div>'
        for label, count in counts.items()
    )
    csv_link = '<a class="button" href="donnees_scrappees.csv">Télécharger le CSV</a>'
    document = f"""<!doctype html>
<html lang="fr"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Tableau de bord — Collecte Sénégal</title>
<style>
body{{font:16px/1.5 system-ui,sans-serif;margin:0;background:#f4f7fb;color:#17233b}}
header{{background:#102a43;color:white;padding:2rem max(1rem,calc((100vw - 1200px)/2))}}
main{{max-width:1200px;margin:auto;padding:1.5rem}}
.summary,.grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(230px,1fr));gap:1rem}}
.panel,section,.card{{background:white;border-radius:12px;box-shadow:0 2px 12px #16324f12}}
.panel{{padding:1rem;margin:1rem 0}}
section{{padding:1.25rem;margin:1.5rem 0}}
h2 span{{font-size:.85rem;color:#52677d;font-weight:normal}}
.bar-row{{display:grid;grid-template-columns:130px 1fr 30px;gap:.75rem;align-items:center;margin:.6rem 0}}
.bar{{height:12px;background:#e5edf5;border-radius:9px;overflow:hidden}}.bar i{{display:block;height:100%;background:#167d7f}}
.card{{overflow:hidden}}.card img{{width:100%;height:190px;object-fit:cover;background:#edf2f7}}
.card-body{{padding:.9rem}}.card h3{{font-size:1rem;margin:.1rem 0 .4rem}}.card p{{color:#60758a;font-size:.85rem}}
.button{{display:inline-block;padding:.65rem 1rem;background:#167d7f;color:white;border-radius:8px;text-decoration:none}}
.warning,.note{{background:#fff5da;padding:.8rem;border-radius:8px}}footer{{color:#60758a;font-size:.85rem;padding:1rem 0}}
.no-image{{display:grid;place-items:center;height:190px;background:#edf2f7}}
</style></head>
<body><header><h1>Collecte de données publiques — Sénégal</h1>
<p>Tableau de bord local des résultats collectés. Maximum 10 images par source.</p>{csv_link}</header>
<main><div class="summary"><div class="panel"><strong>{len(rows)}</strong><br>résultats CSV</div>
<div class="panel"><strong>{sum(bool(x) for x in capture_paths.values())}</strong><br>images archivées localement</div>
<div class="panel"><strong>{len(results)}</strong><br>sources interrogées</div></div>
<div class="panel"><h2>Résultats par source</h2>{bars}</div>
<p class="note">Images publiques conservées pour un usage pédagogique ; vérifiez les droits et conditions d’utilisation avant toute republication. Les images absentes restent accessibles depuis leur URL source dans le CSV.</p>
{"".join(source_sections)}
<footer>Généré depuis les données locales de la collecte. Les éventuels résultats manquants sont signalés par source.</footer>
</main></body></html>"""
    (output_dir / "tableau_de_bord.html").write_text(document, encoding="utf-8")


def export_collection(
    source_path=pathlib.Path("instance") / "collectes.json",
    output_dir=pathlib.Path.home() / "Desktop" / "td_collect",
):
    source_path = pathlib.Path(source_path)
    output_dir = pathlib.Path(output_dir)
    with source_path.open(encoding="utf-8") as data_file:
        results = json.load(data_file)

    output_dir.mkdir(parents=True, exist_ok=True)
    rows = []
    capture_paths = {}
    per_source = {}
    for source_key, result in results.items():
        records = (result.get("records") or [])[:MAX_IMAGES_PER_SOURCE]
        per_source[source_key] = records
        capture_count = 0
        for index, record in enumerate(records, start=1):
            capture_path = _download_image(
                source_key,
                record.get("image_url", ""),
                output_dir / "captures" / source_key / f"{index:02d}",
            )
            relative_capture = (
                capture_path.relative_to(output_dir).as_posix()
                if capture_path
                else ""
            )
            if relative_capture:
                capture_paths[(source_key, index)] = relative_capture
                capture_count += 1
            rows.append(
                {
                    "source": result.get("label", source_key),
                    "titre": record.get("title", ""),
                    "date_publication": record.get("published_at", ""),
                    "url_publication": record.get("source_url", ""),
                    "url_image": record.get("image_url", ""),
                    "capture_locale": relative_capture,
                }
            )
        result["_local_capture_count"] = capture_count

    csv_path = output_dir / "donnees_scrappees.csv"
    with csv_path.open("w", encoding="utf-8-sig", newline="") as csv_file:
        writer = csv.DictWriter(csv_file, fieldnames=list(rows[0]) if rows else [
            "source", "titre", "date_publication", "url_publication", "url_image", "capture_locale"
        ])
        writer.writeheader()
        writer.writerows(rows)

    _write_dashboard(output_dir, results, rows, capture_paths)
    analysis = [
        "ANALYSE DES DONNEES — COLLECTE SENEGAL",
        "",
        f"Nombre total de résultats CSV : {len(rows)}",
        f"Nombre de sources : {len(per_source)}",
        "",
        "Résultats et images archivées par source :",
    ]
    for source_key, records in per_source.items():
        result = results[source_key]
        label = result.get("label", source_key)
        source_rows = [row for row in rows if row["source"] == label]
        titles = sum(bool(row["titre"].strip()) for row in source_rows)
        source_links = sum(bool(row["url_publication"].strip()) for row in source_rows)
        analysis.append(
            f"- {label}: {len(records)} résultat(s), "
            f"{result.get('_local_capture_count', 0)} image(s) archivée(s), "
            f"{titles} titre(s), {source_links} lien(s) source ; "
            f"collecte {result.get('collected_at', 'date inconnue')}."
        )
        if result.get("error"):
            analysis.append(f"  Erreur de collecte : {result['error']}")
        elif not records:
            analysis.append("  Aucun résultat image renvoyé pour cette source.")
    analysis.extend(
        [
            "",
            "Limites : les images ne sont archivées que si elles proviennent du domaine CDN attendu,",
            "sont accessibles sans redirection et pèsent au plus 5 Mo. Les autres URL restent dans le CSV.",
            "Les URL et métadonnées peuvent contenir des informations personnelles publiques ; ne publiez",
            "pas cet export sans vérifier les règles des plateformes, les droits et le cadre applicable.",
        ]
    )
    (output_dir / "analyse.txt").write_text("\n".join(analysis) + "\n", encoding="utf-8")

    return {
        "output_dir": output_dir,
        "csv": csv_path,
        "dashboard": output_dir / "tableau_de_bord.html",
        "analysis": output_dir / "analyse.txt",
        "record_count": len(rows),
        "capture_count": len(capture_paths),
        "source_counts": {
            result.get("label", key): {
                "records": len(per_source[key]),
                "captures": result.get("_local_capture_count", 0),
            }
            for key, result in results.items()
        },
    }


if __name__ == "__main__":
    report = export_collection()
    print(f"Dossier: {report['output_dir']}")
    print(f"CSV: {report['csv']}")
    print(f"Tableau de bord: {report['dashboard']}")
    print(f"Analyse: {report['analysis']}")
    print(f"Résultats: {report['record_count']}; captures: {report['capture_count']}")
