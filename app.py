import hmac
import os
from pathlib import Path

from dotenv import load_dotenv
from flask import Flask, abort, jsonify, render_template, request, send_file

from data_pipeline import (
    MAX_RESULTS_PER_SOURCE,
    SOURCES,
    collect,
    load_results,
    save_results,
)


PROJECT_DIR = Path(__file__).resolve().parent
load_dotenv(PROJECT_DIR / ".env", override=False)

app = Flask(__name__, template_folder=str(PROJECT_DIR / "templates"))
COLLECTIONS_FILE = Path(
    os.environ.get(
        "COLLECTIONS_FILE",
        str(PROJECT_DIR / "instance" / "collectes.json"),
    )
)
PUBLIC_SEED_FILE = PROJECT_DIR / "public" / "collectes.json"
PUBLIC_CSV_FILE = PROJECT_DIR / "public" / "donnees_scrappees.csv"
PREPROCESSING_NOTEBOOK_FILE = (
    PROJECT_DIR / "notebooks" / "pretraitement_donnees_senegal.ipynb"
)


def _dashboard_results():
    saved_results = load_results(COLLECTIONS_FILE)
    if saved_results or not PUBLIC_SEED_FILE.is_file():
        return saved_results
    return load_results(PUBLIC_SEED_FILE)


@app.route("/", methods=["GET", "POST"])
@app.route("/collecte", methods=["GET", "POST"])
def dashboard():
    message = None
    error = None

    if request.method == "POST":
        selected_sources = list(dict.fromkeys(request.form.getlist("sources")))
        admin_password = os.environ.get("COLLECT_ADMIN_PASSWORD", "")
        if not selected_sources:
            error = "Sélectionnez au moins une source."
        elif any(source not in SOURCES for source in selected_sources):
            error = "Une source sélectionnée n’est pas valide."
        elif request.form.get("confirm_costs") != "yes":
            error = "Confirmez les coûts plafonnés avant de lancer les Actors."
        elif not admin_password:
            error = (
                "La collecte est désactivée : le secret "
                "COLLECT_ADMIN_PASSWORD n’est pas configuré."
            )
        elif not hmac.compare_digest(
            request.form.get("collect_password", ""),
            admin_password,
        ):
            error = "Mot de passe de collecte incorrect."
        else:
            try:
                if not COLLECTIONS_FILE.exists() and PUBLIC_SEED_FILE.is_file():
                    save_results(load_results(PUBLIC_SEED_FILE), COLLECTIONS_FILE)
                results = collect(selected_sources)
                save_results(results, COLLECTIONS_FILE)
                message = "Collecte terminée. Les données locales ont été actualisées."
            except ValueError as exception:
                error = str(exception)
            except RuntimeError as exception:
                error = str(exception)

    try:
        saved_results = _dashboard_results()
    except RuntimeError as exception:
        saved_results = {}
        error = str(exception)

    total_records = sum(
        len(result.get("records") or []) for result in saved_results.values()
    )
    return render_template(
        "dashboard.html",
        sources=SOURCES,
        max_results_per_source=MAX_RESULTS_PER_SOURCE,
        saved_results=saved_results,
        total_records=total_records,
        message=message,
        error=error,
        apify_configured=bool(os.environ.get("APIFY_TOKEN", "").strip()),
        collection_enabled=bool(os.environ.get("COLLECT_ADMIN_PASSWORD", "").strip()),
    ), (400 if error and request.method == "POST" else 200)


@app.get("/healthz")
def health_check():
    return jsonify(status="ok")


@app.get("/rapport")
def preprocessing_report():
    return render_template("rapport.html")


@app.get("/notebook-pretraitement.ipynb")
def download_preprocessing_notebook():
    if not PREPROCESSING_NOTEBOOK_FILE.is_file():
        abort(404)
    return send_file(
        PREPROCESSING_NOTEBOOK_FILE,
        mimetype="application/x-ipynb+json",
        as_attachment=True,
        download_name="pretraitement_donnees_senegal.ipynb",
    )


@app.get("/donnees_scrappees.csv")
def download_public_csv():
    if not PUBLIC_CSV_FILE.is_file():
        abort(404)
    return send_file(
        PUBLIC_CSV_FILE,
        mimetype="text/csv; charset=utf-8",
        as_attachment=True,
        download_name="donnees_scrappees.csv",
    )


if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=int(os.environ.get("PORT", "5001")),
        debug=False,
    )
