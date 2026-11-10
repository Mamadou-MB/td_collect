import os
from pathlib import Path

from dotenv import load_dotenv
from flask import Flask, render_template, request

from data_pipeline import SOURCES, collect, load_results, save_results


PROJECT_DIR = Path(__file__).resolve().parent
load_dotenv(PROJECT_DIR / ".env", override=False)

app = Flask(__name__, template_folder=str(PROJECT_DIR / "templates"))
COLLECTIONS_FILE = PROJECT_DIR / "instance" / "collectes.json"


@app.route("/", methods=["GET", "POST"])
@app.route("/collecte", methods=["GET", "POST"])
def dashboard():
    message = None
    error = None

    if request.method == "POST":
        selected_sources = list(dict.fromkeys(request.form.getlist("sources")))
        if not selected_sources:
            error = "Sélectionnez au moins une source."
        elif any(source not in SOURCES for source in selected_sources):
            error = "Une source sélectionnée n’est pas valide."
        elif request.form.get("confirm_costs") != "yes":
            error = "Confirmez les coûts plafonnés avant de lancer les Actors."
        else:
            try:
                results = collect(selected_sources)
                save_results(results, COLLECTIONS_FILE)
                message = "Collecte terminée. Les données locales ont été actualisées."
            except ValueError as exception:
                error = str(exception)
            except RuntimeError as exception:
                error = str(exception)

    try:
        saved_results = load_results(COLLECTIONS_FILE)
    except RuntimeError as exception:
        saved_results = {}
        error = str(exception)

    total_records = sum(
        len(result.get("records") or []) for result in saved_results.values()
    )
    return render_template(
        "dashboard.html",
        sources=SOURCES,
        saved_results=saved_results,
        total_records=total_records,
        message=message,
        error=error,
        apify_configured=bool(os.environ.get("APIFY_TOKEN", "").strip()),
    ), (400 if error and request.method == "POST" else 200)


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5001, debug=False)
