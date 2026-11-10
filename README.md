# td_collect — collecte Sénégal

Application Flask indépendante du projet `mon_projet`. Elle sert son tableau de
bord sur `http://127.0.0.1:5001/` et enregistre ses résultats dans
`instance/collectes.json`.

## Lancer sous Windows

Depuis PowerShell :

```powershell
cd C:\Users\HP\Desktop\td_collect
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python app.py
```

Le dossier contient déjà `.env`. Gardez `APIFY_TOKEN` uniquement dans ce fichier
local et ne le publiez pas. `.gitignore` exclut la clé, les captures et les
exports contenant les données collectées.

La collecte se fait sur demande, avec confirmation explicite des coûts affichés.
Chaque Actor est limité à 10 résultats et chaque collecte applique le plafond
de dépense configuré dans `data_pipeline.py`.

## Git et publication

Ce dossier est conçu pour devenir un dépôt Git distinct. Ne le poussez pas dans
le dépôt `AlyCoto/African_Business_Company`, qui héberge un autre site.

L’application Flask nécessite un hébergeur Python pour être visible sur Internet.
GitHub Pages ne peut publier que le résumé statique ; il n’exécute pas Flask.
Avant une mise en ligne, retirer la clé et les données de collecte de tout
commit, configurer `APIFY_TOKEN` comme secret de l’hébergeur et protéger le
tableau de bord, car les données et les images peuvent concerner des personnes.
