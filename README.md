# Cleaner Dataset

Agent de qualité de données pour fichiers CSV / Excel : il **inspecte** tout le dataset avec Pandas,
**vérifie** (référentiels externes, relations entre colonnes, doublons) et **agit** — uniquement après
validation humaine, via un moteur d'exécution à liste blanche.

```
01 Import → 02 Agent → 03 Human Review → 04 Execute → 05 Validate & Export
```

## Démarrage rapide

```powershell
py -3.15 -m venv .venv
.\.venv\Scripts\Activate.ps1
py -m pip install -r requirements.txt
Copy-Item .env.example .env
```

Pour Groq, ouvrez `.env` et remplacez `gsk_votre_cle` par votre clé. Cette étape est facultative. Pour démarrer :

```powershell
.\.venv\Scripts\python.exe -m streamlit run app.py
```

### Vérifier avec les jeux de données d'exemple

L'application fournit deux jeux de données sales, sans qu'il soit nécessaire d'en importer un :

- **Ventes café** (`data/dirty_cafe_sales.csv`) : 10 000 lignes avec valeurs manquantes, erreurs et doublons.
- **Données d'expéditions** (`data/shipment_data.csv`) : 2 540 lignes avec préambule, séparateur `;`, encodage Windows-1252, virgules décimales, dates françaises, valeurs incohérentes et doublons. Une version Excel de 800 lignes est aussi disponible dans `data/shipment_data.xlsx`.

Pour tester : démarrez l'application, sélectionnez **Ventes café** ou **Données d'expéditions** sur l'écran d'accueil, puis cliquez sur **Lancer DATA QUALITY AGENT**. Sans clé Groq, l'analyse se fait localement avec le moteur heuristique. Avec une clé, Groq choisit les outils et rédige le plan. Dans les deux cas, vous pouvez examiner le plan, choisir les actions, puis les exécuter et vérifier les contrôles et les exports.

La clé Groq est optionnelle et lue depuis `GROQ_API_KEY` dans `.env`. Elle n'est pas saisie ni affichée dans l'interface. `.env` est ignoré par Git : ne partagez pas votre clé et ne la commitez pas.

Le modèle et le contexte métier se règlent dans `DEFAULT_MODEL` de `core/agent.py` et `BUSINESS_CONTEXT` de `app.py`.

## Ce que fait chaque étape

| Étape | Détail |
|---|---|
| **01 Import** | CSV/TSV/XLSX/XLS. Détection de l'encodage (UTF-8, cp1252…), du séparateur, de la ligne d'en-tête (préambule ignoré), de la feuille Excel la plus pertinente. Vue « fichier brut » conservée. KPI + score qualité initial + profil par colonne. |
| **02 Agent** | Boucle de *function calling* Groq sur 11 outils Pandas (aperçu, marqueurs nuls, inférence de types, numériques, dates, doublons, cohérence texte, relations arithmétiques, dépendances fonctionnelles, formats email/téléphone, référentiels). Le LLM ne voit que des résultats compacts, jamais les données brutes. Trace opérationnelle complète. Repli automatique sur l'heuristique si Groq échoue. |
| **03 Human Review** | Cartes d'actions avec colonnes, sévérité (HIGH/MEDIUM/LOW), badge « À REVOIR », **impact simulé** (cellules touchées, lignes supprimées). Les actions risquées sont décochées par défaut. Ajout d'actions manuelles. |
| **04 Execute** | Moteur Pandas à liste blanche (15 types d'actions), ordre canonique sûr, sur une copie. Prévision du nombre de lignes finales. |
| **05 Validate & Export** | Avant/après, score qualité, cellules modifiées par colonne, contrôles (lignes, traçabilité des suppressions, colonnes, doublons, nouvelles valeurs manquantes, marqueurs résiduels, types, cohérence des formules), journal d'exécution. Exports : CSV standard, CSV Excel FR (`;` + virgule décimale), XLSX multi-feuilles (données, plan, journal, contrôles), rapport HTML, **recette JSON rejouable**. |

## Ajouts par rapport à la démo d'origine

- **Remplissage par dépendance** : détecte `Item → Price Per Unit` et complète les prix manquants avant le calcul `Total = Quantité × Prix`.
- **Référentiels externes** : pays ISO 3166 (noms FR/EN, codes), devises ISO 4217, villes du Maroc, moyens de paiement — ou votre propre liste (CSV/XLSX).
- **Harmonisation des catégories** (casse, accents, fautes proches), signalement des valeurs aberrantes, doublons de clé.
- **Score qualité** sur 4 dimensions (complétude, validité, unicité, cohérence des types), avant/après.
- **Recettes** : exportez un plan validé et rejouez-le sur l'export du mois suivant.
- **Constats hors plan** : emails invalides, dates futures, valeurs négatives… signalés sans être modifiés.

## Sécurité

- Aucun code généré par le LLM n'est exécuté : chaque action proposée est validée (`core/actions.py::validate_action`) — type autorisé, colonnes existantes, paramètres bornés. Les actions hors liste blanche sont rejetées et tracées.
- Le fichier d'origine n'est jamais modifié ; toutes les opérations travaillent sur une copie.
- Seuls des agrégats (comptes, exemples courts) sont envoyés au LLM.

## Structure

```
app.py                  interface Streamlit (5 étapes)
core/loader.py          import intelligent
core/profiler.py        outils d'inspection Pandas (exposés au LLM)
core/references.py      référentiels externes
core/agent.py           agent Groq + moteur heuristique
core/actions.py         moteur d'exécution à liste blanche
core/validation.py      contrôles et score qualité
core/export.py          exports CSV / XLSX / HTML / recette
ui/styles.py            thème visuel
data/                   jeux d'exemple + générateur
tests/                  tests pytest (agent Groq simulé inclus)
```

## Tests

```bash
.\.venv\Scripts\python.exe -m pytest -q
```

## Publier sur GitHub

1. Sur [GitHub](https://github.com/new), créez un dépôt vide nommé `cleaner-dataset`. Ne cochez pas l'option pour ajouter un README, une licence ou un `.gitignore`.
2. Dans PowerShell, depuis le dossier du projet, initialisez Git et envoyez les fichiers (remplacez `<VOTRE-NOM>` par votre nom d'utilisateur GitHub) :

```powershell
git init -b main
git add .
git status
git commit -m "Initial commit - Cleaner Dataset"
git remote add origin https://github.com/<VOTRE-NOM>/cleaner-dataset.git
git push -u origin main
```

Vérifiez `git status` avant le commit : `.env` doit être ignoré et ne doit pas apparaître parmi les fichiers à publier. Si Git demande votre identité, configurez-la une seule fois :

```powershell
git config --global user.name "Votre nom"
git config --global user.email "votre-email@example.com"
```

## Mettre le site en ligne

1. Ouvrez [Streamlit Community Cloud](https://share.streamlit.io/) et connectez votre compte GitHub.
2. Cliquez **Create app**, choisissez le dépôt `cleaner-dataset`, la branche `main` et le fichier principal `app.py`, puis déployez.
3. Le site fonctionne sans clé Groq avec le moteur heuristique local. Pour activer l'analyse Groq, ouvrez **App settings → Secrets** et ajoutez :

```toml
GROQ_API_KEY = "votre_cle_groq"
```

Ne mettez jamais la clé dans le code, dans GitHub ou dans `requirements.txt`. Les changements poussés sur `main` seront ensuite redéployés par Streamlit Cloud.
