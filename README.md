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

Le fichier `.env` local contient des secrets : gardez `APIFY_TOKEN` et
`COLLECT_ADMIN_PASSWORD` hors de Git. La collecte est désactivée tant que
`COLLECT_ADMIN_PASSWORD` n’est pas défini ; cette protection empêche les
visiteurs d’un déploiement public de lancer des Actors à vos frais.

La collecte se fait sur demande, avec confirmation explicite des coûts affichés.
Chaque Actor est limité à 20 résultats et chaque collecte applique le plafond
de dépense configuré dans `data_pipeline.py`.

## Déploiement Docker

Prérequis : Docker installé, une clé API Apify et un volume persistant configuré
chez l’hébergeur.

1. Construisez puis démarrez le conteneur :

   ```powershell
   cd C:\Users\HP\Desktop\td_collect
   docker build -t td-collect .
   docker run --rm -p 8000:8000 `
     -e APIFY_TOKEN="votre-cle-apify" `
     -e COLLECT_ADMIN_PASSWORD="un-mot-de-passe-long-aleatoire" `
     -e COLLECTIONS_FILE="/data/collectes.json" `
     -v td-collect-data:/data `
     td-collect
   ```

   Le tableau de bord est alors sur <http://localhost:8000> et la sonde de santé
   sur <http://localhost:8000/healthz>. Ne mettez jamais les valeurs des secrets
   dans un Dockerfile ou dans le dépôt ; sur un hébergeur, configurez-les dans
   son gestionnaire de secrets.
2. Sur un hébergeur Docker, définissez `APIFY_TOKEN` et
   `COLLECT_ADMIN_PASSWORD` comme secrets, définissez `COLLECTIONS_FILE` sur un
   chemin situé dans un volume persistant et publiez le port fourni par `PORT`.
   Le conteneur utilise `PORT` lorsqu’il est défini et écoute sur toutes les
   interfaces réseau.
3. Configurez la sonde de santé avec le chemin `/healthz`.

Sans volume persistant, les données collectées peuvent être perdues lors d’un
redémarrage ou d’un nouveau déploiement. Le tableau de bord affiche les données
collectées ; ne collectez ou ne publiez que ce que vous êtes autorisé à traiter.

## Render

Le dépôt contient `public/collectes.json` et `public/donnees_scrappees.csv` pour
afficher les résultats initiaux après le déploiement. Le CSV et ses textes/liens
seront publics sur le site.

La collecte est réglée sur 20 résultats par source. L’estimation pour les cinq
sources est d’environ 0,23 USD, avec un plafond strict de 0,90 USD par lancement.

Dans le Web Service Render relié à ce dépôt, configurez :

- **Build Command** : `pip install -r requirements.txt`
- **Start Command** : `gunicorn --bind 0.0.0.0:$PORT --workers 2 --timeout 240 app:app`
- **Health Check Path** : `/healthz`
- **Secret** `APIFY_TOKEN` : uniquement si de nouvelles collectes sont prévues.
- **Secret** `COLLECT_ADMIN_PASSWORD` : mot de passe privé exigé pour lancer une
  collecte ; sans lui, l’application reste en lecture seule.
- **Persistent Disk** : montez le disque sur `/var/data`, puis définissez
  `COLLECTIONS_FILE=/var/data/collectes.json` si les collectes effectuées sur
  Render doivent survivre aux redéploiements.

## Dépôt

Le code applicatif est dans le dépôt Git séparé `Mamadou-MB/td_collect`.
`.gitignore` et `.dockerignore` excluent le fichier `.env`, les résultats locaux,
les images téléchargées et les exports bruts ; seuls le CSV et le JSON de départ
dans `public/` sont suivis par Git et accessibles publiquement.
