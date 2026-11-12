import argparse
import os
import math
import pandas as pd
import numpy as np
from dotenv import load_dotenv
import httpx
from supabase import create_client, Client, ClientOptions
import time

# Tentative d'utilisation des certificats d'entreprise Windows via truststore si présent
try:
    import truststore
    truststore.inject_into_ssl()
except Exception:
    pass

# --- DICTIONNAIRES DE MAPPING POUR HARMONISER LES CATÉGORIES AVEC LA BASE ---
SECTOR_MAPPING = {
    'Finance': 'Banque et Finance',
    'Banque et Finance': 'Banque et Finance',
    'Energie': 'Energie et Ressources de base',
    'Matériaux': 'Energie et Ressources de base',
    'Immobilier': 'Infrastructure et Immobilier',
    'Infrastructure': 'Infrastructure et Immobilier',
    'Construction': 'Infrastructure et Immobilier',
    'Defense': 'Défense et Aérospatial',
    'Défense et Aérospatial': 'Défense et Aérospatial',
    'Soins de santé': 'Santé et Pharmacie',
    'Santé': 'Santé et Pharmacie',
    'Pharma': 'Santé et Pharmacie',
    'Biotechnologie': 'Santé et Pharmacie',
    'Santé et Pharmacie': 'Santé et Pharmacie',
    'Diversifié': 'Multi-Secteurs',
    'Multi-Secteur': 'Multi-Secteurs',
    'Multi-Secteurs': 'Multi-Secteurs',
    'Conso': 'Consommation discrétionnaire',
    'Consommation': 'Consommation de base',
    'Consommation de base': 'Consommation de base',
    'Consommation discrétionnaire': 'Consommation discrétionnaire',
    'Automobile': 'Automobile',
    'Industrie': 'Industrie',
    'Semi-conducteur': 'Semi-conducteurs',
    'Semi-conducteurs': 'Semi-conducteurs',
    'Streaming': 'Technologie, Digital et Streaming',
    'Technologie': 'Technologie, Digital et Streaming',
    'Technologie, Digital et Streaming': 'Technologie, Digital et Streaming',
    "Technologies de l'information": "Technologies de l'information",
    'Ser': 'Services de Communication',
    'Services de communication': 'Services de Communication',
    'Services de Communication': 'Services de Communication',
    'Services aux collectivités': 'Services aux collectivités',
    'ESG': 'ESG',
    'Sport': 'Sport',
    'NA': None,
}

COUNTRY_MAPPING = {
    'UNITED STATES': 'États-Unis',
    'Etats-unis': 'États-Unis',
    'FRANCE': 'France',
    'France': 'France',
    'BRITAIN': 'Royaume-Uni',
    'GERMANY': 'Allemagne',
    'ALLEMAGNE': 'Allemagne',
    'Allemagne': 'Allemagne',
    'EURO ZONE': 'Europe',
    'ZONE EURO': 'Europe',
    'EUROPE': 'Europe',
    'Europe': 'Europe',
    'SWITZERLAND': 'Suisse',
    'SWEDEN': 'Suède',
    'NETHERLANDS': 'Pays-Bas',
    'ITALY': 'Italie',
    'SPAIN': 'Espagne',
    'DENMARK': 'Danemark',
    'FINLAND': 'Finlande',
    'BELGIUM': 'Belgique',
    'BELGIQUE': 'Belgique',
    'NORWAY': 'Norvège',
    'IRELAND': 'Irlande',
    'POLAND': 'Pologne',
    'AUSTRIA': 'Autriche',
    'WORLD': 'Monde',
    'LUXEMBOURG': 'Luxembourg',
    'PORTUGAL': 'Portugal',
    'BERMUDA': 'Bermuda',
    'JAPAN': 'Japon',
    'CHILE': 'Chili',
    'CHINA': 'Chine',
    'CHINE': 'Chine',
    'AUSTRALIA': 'Australie',
    'FAROE ISLANDS': 'Îles Féroé',
    'MALTA': 'Malta',
    'RUSSIA': 'Russie',
    'KAZAKHSTAN': 'Kazakhstan',
    'JORDAN': 'Jordan',
    'HUNGARY': 'Hongrie',
    'CZECH': 'République Tchèque',
    'MACAU': 'Macau',
    'BRAZIL': 'Brésil',
    'TRANSATLANTIC': 'Transatlantique',
    'Transatlantique': 'Transatlantique',
    'ASIA': 'Asie',
    'EurAsie': 'Europe - Asie',
    'Euro-asie': 'Europe - Asie',
    'Corée': 'Corée',
    'HONG KONG': 'Hong Kong',
    'NA': None,
}

# --- MAPPING D'ALIAS POUR LES TICKERS DU FICHIER COURS.CSV ET RÉFÉRENTIEL ---
# Permet de reconnaître les colonnes avec suffixe 'Equity' dans cours.csv
# et d'alimenter directement le vrai ticker 'Index' en base de données, sans changer son nom en base.
TICKER_ALIASES = {
    'ENG 160 EQUITY': 'ENG 160 Index',
    'STLAP140 EQUITY': 'STLAP140 Index',
    'SGO220 EQUITY': 'SGO220 Index',
    'SOL240 EQUITY': 'SOL240 Index',
    'AXA215 EQUITY': 'AXA215 Index',
    'SCR180 EQUITY': 'SCR180 Index',
    'RNO185 EQUITY': 'RNO185 Index',
    'VIE140 EQUITY': 'VIE140 Index',
    'UCG290 EQUITY': 'UCG290 Index',
    'PUB360 EQUITY': 'PUB360 Index',
}


def clean_val(v):
    if v is None:
        return None
    if isinstance(v, float) and (math.isnan(v) or np.isnan(v)):
        return None
    if pd.isna(v):
        return None
    s = str(v).strip()
    if s.upper() in ('NAN', 'NONE', 'NULL', 'NA', '#N/A', '#NOM?'):
        return None
    return s


def map_sector(val):
    c = clean_val(val)
    if not c:
        return None
    return SECTOR_MAPPING.get(c, c)


def map_country(val):
    c = clean_val(val)
    if not c:
        return None
    return COUNTRY_MAPPING.get(c, c)


def clean_asset_type_and_subtype(raw_type, raw_subtype):
    t = clean_val(raw_type)
    st = clean_val(raw_subtype)
    # Si le sous-type est vide, on prend le type (ex: Devise, Taux, Crédit, Matière Première)
    if not st and t:
        st = t
    return t, st


def get_supabase_client() -> Client:
    # Supporte .env et ATT33429.env
    if os.path.exists('.env'):
        load_dotenv('.env', override=True)
    elif os.path.exists('ATT33429.env'):
        load_dotenv('ATT33429.env', override=True)
    else:
        load_dotenv(override=True)

    url = os.getenv("SUPABASE_URL")
    key = os.getenv("SUPABASE_KEY")

    if not url or not key:
        print("[ERREUR] SUPABASE_URL ou SUPABASE_KEY introuvable dans le fichier .env")
        print("Veuillez les ajouter (voir les paramètres d'API dans votre projet Supabase).")
        exit(1)

    # Gestion des réseaux d'entreprise (proxy DLPK / Nexo avec inspection SSL et certificat auto-signé)
    # Désactive la vérification stricte par défaut pour éviter l'erreur [SSL: CERTIFICATE_VERIFY_FAILED]
    # Possibilité de forcer la vérification avec SSL_VERIFY=true dans le .env
    ssl_verify_env = os.getenv("SSL_VERIFY", "false").lower()
    ssl_verify = ssl_verify_env in ("true", "1", "yes")

    http_client = httpx.Client(verify=ssl_verify, timeout=120.0)
    options = ClientOptions(httpx_client=http_client)

    return create_client(url, key, options=options)


def sync_new_assets(supabase: Client):
    print("[*] ÉTAPE 1 : Scan des nouveaux actifs depuis le référentiel...")
    # Supporte Univers ssjac New.xlsm (poste de travail) et referentiel_sj_new.csv
    file_path = None
    if os.path.exists('Univers ssjac New.xlsm'):
        file_path = 'Univers ssjac New.xlsm'
        print(f"    -> Fichier source : {file_path} (Excel)")
        df = pd.read_excel(file_path, sheet_name='export')
    elif os.path.exists('referentiel_sj_new.csv'):
        file_path = 'referentiel_sj_new.csv'
        print(f"    -> Fichier source : {file_path} (CSV)")
        df = pd.read_csv(file_path, sep=';', encoding='utf-8-sig', low_memory=False)
    else:
        print("[ERREUR] Aucun fichier référentiel trouvé ('Univers ssjac New.xlsm' ou 'referentiel_sj_new.csv').")
        return

    col_mapping = {
        'Type': 'asset_type',
        'SousType': 'asset_subtype',
        'ISIN': 'isin',
        'Ticker': 'ticker_bloomberg',
        'Nom': 'name',
        'Pays': 'country',
        'Secteur': 'sector',
        'Bourse': 'exchange',
        'Devise': 'currency'
    }
    df = df.rename(columns=col_mapping)
    df = df.replace({np.nan: None})

    # Récupération de TOUS les tickers existants (pagination pour contourner la limite de 1000 lignes de l'API)
    print("    -> Récupération des tickers existants en base...")
    existing_tickers = set()
    start = 0
    while True:
        response = supabase.table('asset').select('ticker_bloomberg').not_.is_('ticker_bloomberg', 'null').range(start, start + 999).execute()
        if not response.data:
            break
        for row in response.data:
            t = row.get('ticker_bloomberg')
            if t:
                existing_tickers.add(t.strip().upper())
        if len(response.data) < 1000:
            break
        start += 1000

    print(f"    -> {len(existing_tickers)} tickers existants trouvés en base.")

    new_assets_to_insert = []
    # On parcourt TOUT le DataFrame (du début à la fin, sans s'arrêter prématurément)
    for index, row in df.iterrows():
        ticker = row.get('ticker_bloomberg')
        if not ticker or pd.isna(ticker):
            continue

        ticker_clean = str(ticker).strip()

        # Si le ticker existe déjà, ou correspond à un alias déjà existant en base (ex: 'STLAP140 Equity' -> 'STLAP140 Index')
        normalized_ticker = TICKER_ALIASES.get(ticker_clean.upper(), ticker_clean)
        if ticker_clean.upper() in existing_tickers or normalized_ticker.upper() in existing_tickers:
            continue

        name_clean = clean_val(row.get('name'))
        # La colonne 'name' est NOT NULL en base : si elle est vide ou en erreur (#NOM?), on ignore cette ligne invalide
        if not name_clean:
            continue

        # Sinon, c'est un nouvel actif valide, on applique le mapping des catégories
        asset_type, asset_subtype = clean_asset_type_and_subtype(row.get('asset_type'), row.get('asset_subtype'))
        sector_clean = map_sector(row.get('sector'))
        country_clean = map_country(row.get('country'))

        params = {
            "name": name_clean,
            "ticker_bloomberg": ticker_clean,
            "isin": clean_val(row.get('isin')),
            "asset_type": clean_val(asset_type),
            "asset_subtype": clean_val(asset_subtype),
            "country": clean_val(country_clean),
            "sector": clean_val(sector_clean),
            "exchange": clean_val(row.get('exchange')),
            "currency": clean_val(row.get('currency'))
        }

        # Sécurité anti-NaN pour JSON
        params = {k: (None if (pd.isna(v) or v is None) else v) for k, v in params.items()}
        new_assets_to_insert.append(params)
        existing_tickers.add(ticker_clean.upper())

    if new_assets_to_insert:
        print(f"[*] {len(new_assets_to_insert)} nouveaux actifs détectés. Insertion en cours...")
        for params in new_assets_to_insert:
            try:
                supabase.table('asset').insert(params).execute()
                print(f"    -> Ajouté : {params['ticker_bloomberg']} ({params['name']}) | Type: {params['asset_type']} | Secteur: {params['sector']} | Pays: {params['country']}")
            except Exception as e:
                print(f"    [ATTENTION] Actif ignoré {params['ticker_bloomberg']} : {e}")
    else:
        print("[*] Aucun nouvel actif à ajouter.")


def update_historical_prices(supabase: Client):
    print("\n[*] ÉTAPE 2 : Mise à jour des cours depuis cours.csv...")
    csv_file = "cours.csv"
    if not os.path.exists(csv_file):
        print(f"[ERREUR] Le fichier {csv_file} est introuvable.")
        return

    print("    -> Interrogation de la base de données (Tickers)...")
    db_assets = {}
    start = 0
    while True:
        response = supabase.table('asset').select('ticker_bloomberg, asset_id').not_.is_('ticker_bloomberg', 'null').range(start, start + 999).execute()
        if not response.data:
            break
        for row in response.data:
            t = row.get('ticker_bloomberg')
            if t:
                db_assets[t.strip().upper()] = row['asset_id']
        if len(response.data) < 1000:
            break
        start += 1000

    print("    -> Interrogation de la base de données (Dates Max)...")
    max_dates = {}
    total_assets = len(db_assets)

    # Avec l'API REST, on fait une requête par actif pour avoir la date max
    # On utilise limit(1) et order('date', desc=True) pour être rapide
    for idx, (ticker, asset_id) in enumerate(db_assets.items()):
        if idx % 50 == 0 and idx > 0:
            print(f"       (Chargement dates max: {idx}/{total_assets})")

        res = supabase.table('historical_price') \
            .select('date') \
            .eq('asset_id', asset_id) \
            .eq('data_source', 'bloomberg_csv') \
            .order('date', desc=True) \
            .limit(1) \
            .execute()

        if res.data:
            max_dates[asset_id] = pd.to_datetime(res.data[0]['date'])

    print("    -> Lecture et parsing de cours.csv...")
    df = pd.read_csv(csv_file, sep=';', low_memory=False)
    if 'Date' not in df.columns:
        print("[ERREUR] Colonne 'Date' introuvable.")
        return

    df['Date'] = pd.to_datetime(df['Date'], format='%d/%m/%Y', errors='coerce')
    df = df.dropna(subset=['Date'])
    df = df[df['Date'] >= pd.to_datetime("2016-08-01")]

    # --- RÈGLE D'HARMONISATION DES TICKERS (ALIAS) ---
    # Renomme les colonnes du CSV terminant par Equity vers Index en mémoire
    df.columns = [TICKER_ALIASES.get(col.strip().upper(), col.strip()) for col in df.columns]
    # Si doublons éventuels de colonnes, on conserve la dernière
    df = df.loc[:, ~df.columns.duplicated(keep='last')]

    valid_cols = ['Date']
    for col in df.columns:
        if col == 'Date':
            continue
        if col.strip().upper() in db_assets:
            valid_cols.append(col)

    df = df[valid_cols]

    print("    -> Transformation des données...")
    df_long = pd.melt(df, id_vars=['Date'], var_name='ticker', value_name='close')
    df_long['close'] = df_long['close'].astype(str).str.replace(' ', '').str.replace(',', '.')
    df_long['close'] = pd.to_numeric(df_long['close'], errors='coerce')
    df_long = df_long.dropna(subset=['close'])

    df_long['asset_id'] = df_long['ticker'].str.strip().str.upper().map(db_assets)
    df_long['asset_id'] = df_long['asset_id'].astype(int)

    print("    -> Filtrage : Tout l'historique pour les nouveaux, (MAX(date) - 5 jours) pour les anciens...")
    def keep_row(row):
        m_date = max_dates.get(row['asset_id'])
        if pd.isnull(m_date):
            return True  # Nouvel actif : on garde TOUT l'historique
        # Ancien actif : on garde seulement les dates >= MAX(date) - 5 jours
        return row['Date'] >= (m_date - pd.Timedelta(days=5))

    mask = df_long.apply(keep_row, axis=1)
    df_long = df_long[mask]

    if df_long.empty:
        print("[*] Aucune nouvelle donnée de cours à insérer.")
        return

    df_final = pd.DataFrame({
        'asset_id': df_long['asset_id'],
        'date': df_long['Date'],
        'data_source': 'bloomberg_csv',
        'close': df_long['close'],
        'volume': None
    })

    df_final = df_final.drop_duplicates(subset=['asset_id', 'date', 'data_source'])

    print(f"[*] Lancement de l'Upsert pour {len(df_final)} lignes via l'API REST...")
    try:
        records = df_final.to_dict('records')
        chunk_size = 1000  # On envoie par paquets de 1000 pour ne pas surcharger l'API HTTPS

        for i in range(0, len(records), chunk_size):
            chunk = records[i:i + chunk_size]
            # Conversion des dates au format ISO (YYYY-MM-DD)
            for row in chunk:
                row['date'] = row['date'].strftime('%Y-%m-%d')

            # Upsert via REST (Gère automatiquement le on_conflict_do_update)
            supabase.table('historical_price').upsert(
                chunk,
                on_conflict='asset_id,date,data_source'
            ).execute()

            print(f"       -> {min(i + chunk_size, len(records))} / {len(records)} lignes envoyées...")

        print("[OK] Mise à jour des cours terminée avec succès !")
    except Exception as e:
        print(f"[ERREUR] Échec lors de l'insertion REST : {e}")


def update_implied_volatilities(supabase: Client):
    print("\n[*] ÉTAPE 3 : Mise à jour des volatilités implicites depuis vol_impli.csv...")
    csv_file = "vol_impli.csv"
    if not os.path.exists(csv_file):
        print(f"    [*] Fichier '{csv_file}' non trouvé dans le dossier (étape ignorée).")
        return

    # 1. Lecture du fichier CSV
    try:
        df = pd.read_csv(csv_file, sep=';', encoding='utf-8-sig', low_memory=False)
    except Exception:
        try:
            df = pd.read_csv(csv_file, sep=';', encoding='latin1', low_memory=False)
        except Exception as e:
            print(f"    [ERREUR] Impossible de lire {csv_file} : {e}")
            return

    if df.empty:
        print("    [ATTENTION] Le fichier vol_impli.csv est vide.")
        return

    # 2. Détection de la colonne Ticker Bloomberg
    col_bloomberg = None
    for c in df.columns:
        c_clean = str(c).strip().lower()
        if 'bloom' in c_clean or 'bbg' in c_clean:
            col_bloomberg = c
            break
    if not col_bloomberg:
        for c in df.columns:
            c_clean = str(c).strip().lower()
            if 'ticker' in c_clean and 'reuters' not in c_clean:
                col_bloomberg = c
                break

    if not col_bloomberg:
        print(f"    [ERREUR] Colonne Ticker Bloomberg introuvable dans {csv_file}. Colonnes détectées : {list(df.columns)}")
        return

    print(f"    -> Colonne Ticker Bloomberg détectée : '{col_bloomberg}'")

    # 3. Détection de la colonne Vol Impli (valeurs numériques)
    col_vol = None
    for c in df.columns:
        c_clean = str(c).strip().lower()
        if 'vol' in c_clean and 'impli' in c_clean and 'formule' not in c_clean:
            col_vol = c
            break

    if not col_vol:
        for c in df.columns:
            c_clean = str(c).strip().lower()
            if 'vol' in c_clean and 'formule' not in c_clean:
                col_vol = c
                break

    if not col_vol:
        print(f"    [ERREUR] Colonne de valeurs de Vol Implicite introuvable. Colonnes détectées : {list(df.columns)}")
        return

    print(f"    -> Colonne Vol Implicite détectée : '{col_vol}'")

    # 4. Extraction de la Date et de la Maturité depuis les en-têtes
    import re
    date_str = None
    all_headers_str = " ".join([str(c) for c in df.columns])
    m_date = re.search(r'(\d{1,2}[/-]\d{1,2}[/-]\d{2,4})', str(col_vol)) or re.search(r'(\d{1,2}[/-]\d{1,2}[/-]\d{2,4})', all_headers_str)
    if m_date:
        try:
            d_parsed = pd.to_datetime(m_date.group(1), dayfirst=True)
            date_str = d_parsed.strftime('%Y-%m-%d')
        except Exception:
            pass

    if not date_str:
        date_str = pd.Timestamp.now().strftime('%Y-%m-%d')
        print(f"    [INFO] Date non trouvée dans l'en-tête, utilisation de la date du jour : {date_str}")
    else:
        print(f"    -> Date de relevé extraite : {date_str}")

    maturity_str = "DEC26"
    m_mat = re.search(r'(?i)(JAN|FEB|MAR|APR|MAY|JUN|JUL|AUG|SEP|OCT|NOV|DEC)\s*(\d{2,4})', all_headers_str)
    if m_mat:
        mois = m_mat.group(1).upper()
        annee = m_mat.group(2)
        if len(annee) == 4:
            annee = annee[-2:]
        maturity_str = f"{mois}{annee}"
        print(f"    -> Maturité extraite : {maturity_str}")
    else:
        print(f"    -> Maturité par défaut : {maturity_str}")

    # 5. Récupération des correspondances Ticker Bloomberg -> asset_id depuis Supabase
    print("    -> Récupération des tickers existants en base...")
    db_assets = {}
    start = 0
    while True:
        response = supabase.table('asset').select('ticker_bloomberg, asset_id').not_.is_('ticker_bloomberg', 'null').range(start, start + 999).execute()
        if not response.data:
            break
        for row in response.data:
            t = row.get('ticker_bloomberg')
            if t:
                db_assets[t.strip().upper()] = row['asset_id']
        if len(response.data) < 1000:
            break
        start += 1000

    # 6. Nettoyage et préparation des données
    df_clean = df[[col_bloomberg, col_vol]].copy()
    df_clean.columns = ['raw_ticker', 'raw_vol']
    df_clean = df_clean.dropna(subset=['raw_ticker', 'raw_vol'])

    df_clean['ticker_clean'] = df_clean['raw_ticker'].astype(str).str.strip().str.upper()
    df_clean['ticker_clean'] = df_clean['ticker_clean'].map(lambda x: TICKER_ALIASES.get(x, x))

    df_clean['vol_str'] = df_clean['raw_vol'].astype(str).str.replace(' ', '').str.replace(',', '.')
    df_clean['vol_num'] = pd.to_numeric(df_clean['vol_str'], errors='coerce')
    df_clean = df_clean.dropna(subset=['vol_num'])
    df_clean = df_clean[df_clean['vol_num'] > 0]

    df_clean['asset_id'] = df_clean['ticker_clean'].map(db_assets)
    matched_df = df_clean.dropna(subset=['asset_id']).copy()
    matched_df['asset_id'] = matched_df['asset_id'].astype(int)

    unmatched = df_clean[df_clean['asset_id'].isna()]
    if len(unmatched) > 0:
        print(f"    [ATTENTION] {len(unmatched)} tickers non trouvés dans la table asset : {list(unmatched['ticker_clean'].unique())[:5]}")

    if matched_df.empty:
        print("    [ERREUR] Aucun actif reconnu dans la base. Vérifiez les tickers Bloomberg.")
        return

    records = []
    for _, r in matched_df.iterrows():
        records.append({
            'asset_id': int(r['asset_id']),
            'date': date_str,
            'maturity': maturity_str,
            'vol_value': round(float(r['vol_num']), 4),
            'ticker_bloomberg': r['ticker_clean']
        })

    # Dédoublonnage sur la clé unique
    records_dict = {(rec['asset_id'], rec['date'], rec['maturity']): rec for rec in records}
    final_records = list(records_dict.values())

    print(f"[*] Envoi de {len(final_records)} volatilités implicites dans 'implied_volatility'...")
    try:
        chunk_size = 500
        for i in range(0, len(final_records), chunk_size):
            chunk = final_records[i:i + chunk_size]
            supabase.table('implied_volatility').upsert(
                chunk,
                on_conflict='asset_id,date,maturity'
            ).execute()
        print(f"[OK] {len(final_records)} volatilités implicites enregistrées avec succès (Maturité {maturity_str}, Date {date_str}) !")
    except Exception as e:
        print(f"[ERREUR] Échec de l'insertion dans implied_volatility : {e}")
        print("Vérifiez que la table 'implied_volatility' a bien été créée dans Supabase.")


def main():
    parser = argparse.ArgumentParser(description="Pipeline global de mise à jour (Univers, Cours et Vol Implicite) via API REST (HTTPS).")
    args = parser.parse_args()

    supabase = get_supabase_client()

    # 1. On scanne et insère les potentiels nouveaux actifs
    sync_new_assets(supabase)

    # 2. On met à jour les cours
    update_historical_prices(supabase)

    # 3. On met à jour les volatilités implicites
    update_implied_volatilities(supabase)


if __name__ == "__main__":
    main()
