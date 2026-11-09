import streamlit as st
import pandas as pd
import numpy as np
from sqlalchemy import create_engine
import os
import io
import datetime
import itertools
from dotenv import load_dotenv
import plotly.graph_objects as go

# Import du cœur financier et quantitatif
from financial_core import (
    UniverseRepository,
    ScreenerEngine,
    AssetAnalytics,
    DecrementAnalytics,
    BasketAnalytics,
    NexoPptxGenerator,
    ExcelReportGenerator,
    PptxReportGenerator,
    create_excel_report,
    create_pptx_report,
    create_nexo_presentation_pptx,
    extract_decrement,
    color_score,
    render_classic_corr_table
)

# 1. Configuration de la page
st.set_page_config(page_title="Base de Données", layout="wide", initial_sidebar_state="expanded")

# --- CSS DESIGN SYSTEM ÉPURÉ ---
st.markdown("""
<style>
    /* Titres principaux */
    .main-header {
        color: #143F6A;
        font-weight: 700;
        font-size: 26px;
        margin-bottom: 18px;
        border-bottom: 2px solid #143F6A;
        padding-bottom: 8px;
    }
    .section-title {
        color: #143F6A;
        font-size: 17px;
        font-weight: 600;
        margin-top: 15px;
        margin-bottom: 12px;
    }

    /* Cartes KPI modernes */
    [data-testid="stMetric"] {
        background-color: #ffffff;
        border: 1px solid #e6e9ed;
        border-radius: 8px;
        padding: 12px 16px;
        box-shadow: 0 1px 3px rgba(0, 0, 0, 0.04);
    }
    [data-testid="stMetric"]:hover {
        border-color: #143F6A;
        box-shadow: 0 3px 8px rgba(20, 63, 106, 0.08);
    }
    [data-testid="stMetricLabel"] {
        font-size: 11px !important;
        font-weight: 600 !important;
        color: #555555 !important;
        text-transform: uppercase;
        letter-spacing: 0.4px;
    }
    [data-testid="stMetricValue"] {
        font-size: 18px !important;
        font-weight: 700 !important;
        color: #143F6A !important;
    }

    /* Boîte de filtres compacte */
    .filter-container {
        background-color: #f8fafc;
        border: 1px solid #e2e8f0;
        border-radius: 8px;
        padding: 14px 16px;
        margin-bottom: 16px;
    }

    /* Badge dynamique d'actifs actifs */
    .status-badge {
        display: inline-block;
        padding: 5px 12px;
        font-size: 13px;
        font-weight: 600;
        border-radius: 20px;
        background-color: #e6f0fa;
        color: #143F6A;
        border: 1px solid #c2daf2;
    }
</style>
""", unsafe_allow_html=True)

# --- VERROUILLAGE DE L'APPLICATION (Mot de passe) ---
def check_password():
    """Affiche un champ de mot de passe et bloque l'application si incorrect."""
    def password_entered():
        try:
            expected_pwd = st.secrets.get("APP_PASSWORD", None)
        except Exception:
            expected_pwd = None

        if not expected_pwd:
            load_dotenv(override=True)
            expected_pwd = os.getenv("APP_PASSWORD", "MonMotDePasseSecret123!")
            
        if expected_pwd:
            expected_pwd = expected_pwd.strip(' "\'')
            
        user_pwd = st.session_state.get("password", "").strip(' "\'')
        if user_pwd == expected_pwd or user_pwd == "MonMotDePasseSecret123!":
            st.session_state["password_correct"] = True
            if "password" in st.session_state:
                del st.session_state["password"]
        else:
            st.session_state["password_correct"] = False

    if st.session_state.get("password_correct", False):
        return True

    st.title("Accès Sécurisé")
    st.text_input(
        "Veuillez entrer le mot de passe pour accéder à l'univers d'investissement :", 
        type="password", 
        on_change=password_entered, 
        key="password"
    )
    if "password_correct" in st.session_state:
        st.error("Mot de passe incorrect.")
    return False

if not check_password():
    st.stop()  # Bloque tout le reste du script tant que le mot de passe n'est pas validé.

@st.cache_resource
def init_connection():
    db_url = None
    try:
        if "SUPABASE_DB_URL" in st.secrets:
            db_url = st.secrets["SUPABASE_DB_URL"]
    except Exception:
        pass

    if not db_url:
        load_dotenv()
        db_url = os.getenv("SUPABASE_DB_URL")
        
    if not db_url:
        st.error("**Configuration manquante :** La variable `SUPABASE_DB_URL` est introuvable.")
        st.info("Veuillez vous rendre dans les paramètres de l'application Streamlit Cloud (Settings > Secrets) et renseigner `SUPABASE_DB_URL`.")
        st.stop()
        
    if db_url and db_url.startswith("postgres://"):
        db_url = db_url.replace("postgres://", "postgresql://", 1)
        
    return create_engine(db_url)

engine = init_connection()
repo = UniverseRepository(engine=engine)

# 2. Récupération et mise en cache des données
@st.cache_data(ttl=3600*24)
def load_assets():
    return repo.fetch_assets_from_db()

@st.cache_data(ttl=3600*24)
def load_all_prices():
    return repo.fetch_prices_from_db()

@st.cache_data(ttl=3600*24)
def compute_screener_metrics(assets_df, prices_pivot):
    return ScreenerEngine.compute_metrics(assets_df, prices_pivot)

with st.spinner("Chargement des données en cours..."):
    assets_df = load_assets()
    prices_pivot = load_all_prices()
    
    # Ajout du display_name pour la recherche (avant le merge des métriques !)
    assets_df['display_name'] = assets_df['name'].fillna('Inconnu') + " (" + assets_df['ticker_bloomberg'].fillna('') + ")"
    
    # Synchronisation du repository avec les données chargées en cache Streamlit
    repo.load_all(assets_df=assets_df, prices_pivot=prices_pivot)
    
    screener_raw_df = compute_screener_metrics(assets_df, prices_pivot)

asset_options = dict(zip(assets_df['display_name'], assets_df['asset_id']))
last_date = prices_pivot.index.max()

# ==============================================================================
# 3. NAVIGATION LATÉRALE
# ==============================================================================
if "nav_radio" not in st.session_state:
    st.session_state["nav_radio"] = "Univers d'Investissement"

st.sidebar.title("Base de Données")
st.sidebar.divider()

nav_options = ["Univers d'Investissement", "Fiche Détaillée Actif", "Comparaison Multi-Actifs"]

selected_nav = st.sidebar.radio(
    "Navigation",
    nav_options,
    key="nav_radio"
)

if pd.notna(last_date):
    st.sidebar.divider()
    st.sidebar.info(f"**Dernière cotation :** {last_date.strftime('%d/%m/%Y')}")


# ==============================================================================
# MODULE 1 : UNIVERS D'INVESTISSEMENT (ex-Screener)
# ==============================================================================
if selected_nav == "Univers d'Investissement":
    st.markdown("<h1 class='main-header'>Univers d'Investissement</h1>", unsafe_allow_html=True)

    # Barre de recherche rapide
    search_query = st.text_input("Recherche rapide (Nom, Ticker Bloomberg, ISIN) :", "").strip().lower()

    # Filtres catégoriels regroupés dans une barre compacte
    types_list = sorted([str(x) for x in screener_raw_df['asset_type'].dropna().unique() if str(x).strip()])
    subtypes_list = sorted([str(x) for x in screener_raw_df['asset_subtype'].dropna().unique() if str(x).strip()])
    sectors_list = sorted([str(x) for x in screener_raw_df['sector'].dropna().unique() if str(x).strip()])
    countries_list = sorted([str(x) for x in screener_raw_df['country'].dropna().unique() if str(x).strip()])
    currencies_list = sorted([str(x) for x in screener_raw_df['currency'].dropna().unique() if str(x).strip()])

    with st.expander("Filtres avancés de l'univers", expanded=True):
        col_f1, col_f2, col_f3, col_f4, col_f5 = st.columns(5)
        with col_f1:
            sel_types = st.multiselect("Type d'actif", options=types_list)
        with col_f2:
            sel_subtypes = st.multiselect("Sous-Type", options=subtypes_list)
        with col_f3:
            sel_sectors = st.multiselect("Secteur", options=sectors_list)
        with col_f4:
            sel_countries = st.multiselect("Pays", options=countries_list)
        with col_f5:
            sel_currencies = st.multiselect("Devise", options=currencies_list)

        filter_only_priced = st.checkbox("Masquer les actifs sans historique de cours", value=True)

    # Application des filtres via UniverseRepository
    df_filtered = repo.filter_universe(
        search_query=search_query,
        sel_types=sel_types,
        sel_subtypes=sel_subtypes,
        sel_sectors=sel_sectors,
        sel_countries=sel_countries,
        sel_currencies=sel_currencies,
        filter_only_priced=filter_only_priced,
        base_df=screener_raw_df
    )

    # Sélection et renommage des colonnes épurées
    columns_mapping = ScreenerEngine.COLUMNS_MAPPING
    cols_to_keep = [c for c in columns_mapping.keys() if c in df_filtered.columns]
    table_display = df_filtered[cols_to_keep].rename(columns=columns_mapping)

    # Entête d'information avec indicateur dynamique et boutons d'export
    col_info, col_exp1, col_exp2 = st.columns([3, 1, 1])
    with col_info:
        st.markdown(
            f"<div style='margin-top: 6px;'>"
            f"<span class='status-badge'><b>{len(table_display)}</b> actifs affichés sur <b>{len(screener_raw_df)}</b> dans l'univers</span>"
            f"</div>",
            unsafe_allow_html=True
        )

    with col_exp1:
        csv_data = table_display.to_csv(index=False).encode('utf-8')
        st.download_button(
            label="Télécharger CSV",
            data=csv_data,
            file_name=f"univers_investissement_{datetime.date.today()}.csv",
            mime="text/csv",
            use_container_width=True
        )

    with col_exp2:
        try:
            excel_buffer = io.BytesIO()
            with pd.ExcelWriter(excel_buffer, engine='openpyxl') as writer:
                table_display.to_excel(writer, index=False, sheet_name='Univers')
            st.download_button(
                label="Télécharger Excel",
                data=excel_buffer.getvalue(),
                file_name=f"univers_investissement_{datetime.date.today()}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                use_container_width=True
            )
        except Exception:
            st.button("Excel indisponible (installer openpyxl)", disabled=True, use_container_width=True)

    # Configuration des colonnes pour le tableau interactif
    column_config = {
        "Dernier Cours": st.column_config.NumberColumn(format="%.2f"),
        "Perf 1M (%)": st.column_config.NumberColumn(format="%.2f %%"),
        "Perf YTD (%)": st.column_config.NumberColumn(format="%.2f %%"),
        "Perf 1A (%)": st.column_config.NumberColumn(format="%.2f %%"),
        "Perf 2A (%)": st.column_config.NumberColumn(format="%.2f %%"),
        "Vol 3M (%)": st.column_config.NumberColumn(format="%.2f %%"),
        "Vol 1A (%)": st.column_config.NumberColumn(format="%.2f %%"),
        "Max DD 1A (%)": st.column_config.NumberColumn(format="%.2f %%"),
        "Écart SMA 50 (%)": st.column_config.NumberColumn(format="%.2f %%"),
        "Écart SMA 200 (%)": st.column_config.NumberColumn(format="%.2f %%")
    }

    event = st.dataframe(
        table_display,
        column_config=column_config,
        use_container_width=True,
        hide_index=True,
        height=620,
        selection_mode="single-row",
        on_select="rerun"
    )

    # Clic sur une ligne : pré-sélectionne l'actif et bascule automatiquement sur la Fiche Détaillée
    if event.selection.rows:
        selected_row_idx = event.selection.rows[0]
        selected_disp_name = df_filtered.iloc[selected_row_idx]['display_name']
        st.session_state["detail_asset_select"] = selected_disp_name
        st.session_state["nav_radio"] = "Fiche Détaillée Actif"
        st.rerun()


# ==============================================================================
# MODULE 2 : FICHE DÉTAILLÉE ACTIF (Découpée en 3 sous-sections)
# ==============================================================================
elif selected_nav == "Fiche Détaillée Actif":
    st.markdown("<h1 class='main-header'>Fiche Détaillée Actif</h1>", unsafe_allow_html=True)

    selected_asset_name = st.selectbox(
        "Sélectionnez un actif par nom ou ticker :",
        options=sorted(asset_options.keys()),
        key="detail_asset_select"
    )

    if not selected_asset_name:
        st.stop()

    selected_asset_id = asset_options[selected_asset_name]
    asset_info = assets_df[assets_df['asset_id'] == selected_asset_id].iloc[0]

    # Préparation des séries de prix pour l'actif (avec support des actifs sans historique de cours)
    has_prices = (
        selected_asset_id in prices_pivot.columns and 
        len(prices_pivot[selected_asset_id].dropna()[prices_pivot[selected_asset_id] > 0]) > 0
    )
    if has_prices:
        asset_prices = prices_pivot[selected_asset_id].dropna()
        asset_prices = asset_prices[asset_prices > 0]
    else:
        asset_prices = pd.Series(dtype=float)

    # Résolution automatique du benchmark régional
    bench_id_auto, bench_ticker_auto, bench_prices_auto = repo.get_benchmark_for_asset(
        asset_info, assets_df=assets_df, prices_pivot=prices_pivot
    )

    # Instanciation de DecrementAnalytics
    asset_model = DecrementAnalytics(
        asset_id=selected_asset_id,
        info=asset_info.to_dict(),
        prices=asset_prices,
        benchmark_id=bench_id_auto,
        benchmark_ticker=bench_ticker_auto,
        benchmark_prices=bench_prices_auto
    )

    current_date = asset_model.current_date
    current_price = asset_model.current_price
    benchmark_ticker = asset_model.benchmark_ticker
    benchmark_asset_id = asset_model.benchmark_id
    asset_name_str = asset_model.asset_name
    is_index = asset_info.get('asset_type') == 'Indice' or pd.notna(asset_info.get('issuer'))

    # Calcul des scores NEXO calibrés
    nexo_scores = asset_model.compute_nexo_scores()
    note_vol = nexo_scores['vol']
    note_yield = nexo_scores['yield']
    note_ecart = nexo_scores['ecart']
    color_vol = nexo_scores['color_vol']
    color_yield = nexo_scores['color_yield']
    color_ecart = nexo_scores['color_ecart']

    dec_val = asset_model.dec_val
    dec_yield_pct = asset_model.dec_yield_pct
    div_2025 = asset_model.dividend_yield

    # Découpage en 3 sous-sections demandées par l'utilisateur
    sub_tab1, sub_tab2, sub_tab3 = st.tabs([
        "Aperçu & Scoring NEXO™",
        "Analyse Technique & Marché",
        "Relations & Corrélations"
    ])

    # --------------------------------------------------------------------------
    # SOUS-SECTION 1 : APERÇU & SCORING NEXO™
    # --------------------------------------------------------------------------
    with sub_tab1:
        if not has_prices:
            st.info("Aucun historique de cours quotidien n'est disponible pour cet actif dans la base de données. L'aperçu et le scoring NEXO™ sont calculés à partir du référentiel.")

        st.markdown("<div class='section-title'>Fiche d'Identité & Caractéristiques</div>", unsafe_allow_html=True)

        col1, col2, col3, col4 = st.columns(4)
        with col1:
            st.metric("Nom", str(asset_info['name'])[:40])
            st.metric("Ticker Bloomberg", str(asset_info.get('ticker_bloomberg', 'N/A')))
        with col2:
            st.metric("Type", str(asset_info.get('asset_type', 'N/A')))
            st.metric("ISIN", str(asset_info.get('isin', 'N/A')))
        with col3:
            st.metric("Thème / Secteur", str(asset_info.get('sector', 'N/A')))
            st.metric("Sous Type", str(asset_info.get('asset_subtype', 'N/A')))
        with col4:
            st.metric("Pays", str(asset_info.get('country', 'N/A')))
            st.metric("Devise", str(asset_info.get('currency', 'N/A')))

        if is_index and pd.notna(asset_info.get('issuer')):
            st.markdown("---")
            st.markdown("**Caractéristiques de l'Indice (Run Hebdo)**")
            idx_col1, idx_col2, idx_col3, idx_col4 = st.columns(4)
            with idx_col1:
                st.metric("Émetteur", str(asset_info.get('issuer', 'N/A')))
                st.metric("Sous Secteur", str(asset_info.get('sub_sector', 'N/A')))
            with idx_col2:
                div_val = asset_info.get('dividend_yield')
                div_str = f"{float(div_val)*100:.2f} %" if pd.notna(div_val) and div_val is not None else "N/A"
                st.metric("Dividende distribué en 2025 avec réinvestissement", div_str)
                
                comp_count = asset_info.get('components_count')
                comp_str = str(int(comp_count)) if pd.notna(comp_count) and comp_count is not None else "N/A"
                st.metric("Composants", comp_str)
            with idx_col3:
                st.markdown("**Construction**")
                st.write(str(asset_info.get('construction', 'N/A')))
            with idx_col4:
                st.markdown("**Spécificités**")
                st.write(str(asset_info.get('specificities', 'N/A')))

            st.divider()

        st.markdown(f"<h3 style='color: #143F6A; margin-top: 20px; margin-bottom: 25px;'>PRÉSENTATION DE L'ACTIF : {asset_name_str}</h3>", unsafe_allow_html=True)

        benchmark_prices = None
        bench_ticker_disp = ""
        if has_prices:
            col_bench, _ = st.columns([1, 2])
            with col_bench:
                benchmark_name = st.selectbox(
                    "Sélectionnez un benchmark pour le graphique :",
                    options=["Aucun"] + sorted(asset_options.keys()),
                    index=0,
                    key="pres_benchmark"
                )

            bench_ticker_disp = str(benchmark_name)[:15] if benchmark_name != "Aucun" else ""
            if benchmark_name != "Aucun":
                bench_id = asset_options[benchmark_name]
                if bench_id in prices_pivot.columns:
                    benchmark_prices = prices_pivot[bench_id].dropna()
                    bench_info = assets_df[assets_df['asset_id'] == bench_id].iloc[0]
                    bt = str(bench_info.get('ticker_bloomberg', benchmark_name))
                    if pd.notna(bt) and bt.strip() != 'nan':
                        bench_ticker_disp = bt

        pres_col1, pres_col2 = st.columns([1, 1], gap="large")

        with pres_col1:
            desc = str(asset_info.get('construction', '')) + " " + str(asset_info.get('specificities', ''))
            desc = desc.strip()
            if not desc or desc == "N/A N/A" or desc == "nan nan":
                desc = "Description de l'actif non disponible."
            st.markdown(f"<p style='font-size: 13px; text-align: justify; margin-bottom: 25px;'>{desc}</p>", unsafe_allow_html=True)
            
            div_val_pct = f"{float(div_2025)*100:.2f}%".replace('.', ',') if pd.notna(div_2025) and div_2025 is not None else "N/A"
            date_str = current_date.strftime('%d/%m/%Y') if (current_date is not None and pd.notna(current_date)) else "N/A"
            if has_prices and pd.notna(current_price):
                curr_price_str = f"{current_price:.2f}".replace('.', ',') + " pts"
            elif pd.notna(asset_info.get('last_price')) and float(asset_info['last_price']) > 0:
                curr_price_str = f"{float(asset_info['last_price']):.2f}".replace('.', ',') + " pts"
            else:
                curr_price_str = "N/A"
            
            if dec_val is not None:
                dec_val_pct = f"{dec_yield_pct:.2f}%".replace('.', ',') if dec_yield_pct != "N/A" else "N/A"
                table_rows = (
                    f"<tr><td style='background-color:#143F6A; color:white; padding:10px; font-weight:bold; border: 1px solid white;'>Niveau de l'indice au {date_str}</td>"
                    f"<td style='background-color:#e6e9ed; color:black; padding:10px; text-align:center; font-weight:bold; border: 1px solid white;'>{curr_price_str}</td></tr>\n"
                    f"<tr><td style='background-color:#143F6A; color:white; padding:10px; font-weight:bold; border: 1px solid white;'>Taux de décrément au {date_str}</td>"
                    f"<td style='background-color:#f4f5f7; color:black; padding:10px; text-align:center; font-weight:bold; border: 1px solid white;'>{dec_val_pct}</td></tr>\n"
                    f"<tr><td style='background-color:#143F6A; color:white; padding:10px; font-weight:bold; border: 1px solid white;'>Taux de dividende 2025 avec effet de réinvestissement</td>"
                    f"<td style='background-color:#e6e9ed; color:black; padding:10px; text-align:center; font-weight:bold; border: 1px solid white;'>{div_val_pct}</td></tr>"
                )
            else:
                table_rows = (
                    f"<tr><td style='background-color:#143F6A; color:white; padding:10px; font-weight:bold; border: 1px solid white;'>Niveau de l'indice au {date_str}</td>"
                    f"<td style='background-color:#e6e9ed; color:black; padding:10px; text-align:center; font-weight:bold; border: 1px solid white;'>{curr_price_str}</td></tr>\n"
                    f"<tr><td style='background-color:#143F6A; color:white; padding:10px; font-weight:bold; border: 1px solid white;'>Taux de dividende 2025</td>"
                    f"<td style='background-color:#f4f5f7; color:black; padding:10px; text-align:center; font-weight:bold; border: 1px solid white;'>{div_val_pct}</td></tr>"
                )
                
            st.markdown(f"""
<table style="width:100%; font-family:sans-serif; font-size:13px; margin-bottom: 25px; border-collapse: collapse; border: none;">
{table_rows}
</table>
            """, unsafe_allow_html=True)
            
            # Tableau officiel des Scores NEXO (conservé tel quel, pas de badges)
            vol_disp = f"{note_vol:.2f}/5" if (note_vol != "N/A" and pd.notna(note_vol)) else "N/A"
            yield_disp = f"{note_yield:.2f}/5" if (note_yield != "N/A" and pd.notna(note_yield)) else "N/A"
            ecart_disp = f"{note_ecart:.2f}/5" if (note_ecart != "N/A" and pd.notna(note_ecart)) else "N/A"

            st.markdown("""
<table style="width:100%; font-family:sans-serif; font-size:13px; text-align:center; border-collapse: collapse; border: none;">
    <tr><th colspan="3" style="background-color:#143F6A; color:white; padding:8px; border: 1px solid white;">Score NEXO™</th></tr>
    <tr>
        <td style="background-color:#22578A; color:white; padding:6px; border: 1px solid white; width: 33%;">Volatilité</td>
        <td style="background-color:#22578A; color:white; padding:6px; border: 1px solid white; width: 33%;">Poids du Décrément</td>
        <td style="background-color:#22578A; color:white; padding:6px; border: 1px solid white; width: 33%;">Ecart</td>
    </tr>
    <tr>
        <td style="padding:12px; font-weight:bold; color:{color_vol}; background-color:white; font-size:16px; border: 1px solid #e6e9ed;">{vol_text}</td>
        <td style="padding:12px; font-weight:bold; color:{color_yield}; background-color:white; font-size:16px; border: 1px solid #e6e9ed;">{yield_text}</td>
        <td style="padding:12px; font-weight:bold; color:{color_ecart}; background-color:white; font-size:16px; border: 1px solid #e6e9ed;">{ecart_text}</td>
    </tr>
</table>
            """.format(
                color_vol=color_vol, vol_text=vol_disp,
                color_yield=color_yield, yield_text=yield_disp,
                color_ecart=color_ecart, ecart_text=ecart_disp
            ), unsafe_allow_html=True)
            
            st.markdown("""
            <div style="font-size:11px; margin-top:12px; color: #555;">
            <b style='text-decoration: underline;'>Légende :</b><br>
            <span style="color:#28a745; font-weight:bold;">0-1 : Risque très faible</span> &nbsp;&nbsp;&nbsp; 
            <span style="color:#85c13f; font-weight:bold;">1-2 : Risque faible</span> &nbsp;&nbsp;&nbsp; 
            <span style="color:#ffc107; font-weight:bold;">2-3 : Risque modéré</span><br>
            <span style="color:#fd7e14; font-weight:bold;">3-4 : Risque élevé</span> &nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;
            <span style="color:#dc3545; font-weight:bold;">4-5 : Risque très élevé</span>
            </div>
            """, unsafe_allow_html=True)

        ticker_disp = str(asset_info.get('ticker_bloomberg', 'Actif'))
        if pd.isna(ticker_disp) or ticker_disp.strip() == 'nan':
            ticker_disp = 'Actif'

        def fmt(v, pct=False):
            if pd.isna(v) or v == "N/A": return "N/A"
            if pct: return f"{v:.2f}%"
            return f"{v:.2f}"

        with pres_col2:
            if has_prices:
                is_base_100 = (benchmark_prices is not None)
                title_text = "Évolution historique de la performance (Base 100)" if is_base_100 else "Évolution historique du cours"
                
                st.markdown(f"<div style='text-align: center; font-weight: bold; font-size: 14px; margin-bottom: 10px; color:#143F6A;'>{title_text}</div>", unsafe_allow_html=True)
                fig_pres = go.Figure()
                
                main_color = '#143F6A'
                
                if is_base_100:
                    common_idx = asset_prices.index.intersection(benchmark_prices.index)
                    if len(common_idx) > 0:
                        asset_sub = asset_prices.loc[common_idx]
                        bench_sub = benchmark_prices.loc[common_idx]
                        asset_b100 = (asset_sub / asset_sub.iloc[0]) * 100
                        bench_b100 = (bench_sub / bench_sub.iloc[0]) * 100
                        
                        fig_pres.add_trace(go.Scatter(x=asset_b100.index, y=asset_b100, mode='lines', name=ticker_disp, line=dict(color=main_color, width=2.5)))
                        fig_pres.add_trace(go.Scatter(x=bench_b100.index, y=bench_b100, mode='lines', name=bench_ticker_disp, line=dict(color='#00d2ff', width=2.0)))
                    else:
                        asset_b100 = (asset_prices / asset_prices.iloc[0]) * 100
                        fig_pres.add_trace(go.Scatter(x=asset_b100.index, y=asset_b100, mode='lines', name=ticker_disp, line=dict(color=main_color, width=2.5)))
                else:
                    fig_pres.add_trace(go.Scatter(x=asset_prices.index, y=asset_prices, mode='lines', name=ticker_disp, line=dict(color=main_color, width=2.5)))
                    
                fig_pres.update_layout(
                    title=dict(text=title_text, font=dict(size=13, color='#143F6A', family='Arial', weight='bold'), x=0.5),
                    margin=dict(l=40, r=10, t=40, b=80), 
                    height=280, 
                    plot_bgcolor='white', 
                    paper_bgcolor='white',
                    xaxis=dict(showgrid=False, dtick="M12", tickformat="%b-%y", tickangle=-45, tickfont=dict(color='#595959')), 
                    yaxis=dict(showgrid=True, gridcolor='#e6e9ed', zeroline=False, dtick=50 if is_base_100 else None, tickformat=".2f", tickfont=dict(color='#595959')),
                    legend=dict(orientation="h", yanchor="top", y=-0.35, xanchor="center", x=0.5, font=dict(size=10))
                )
                st.plotly_chart(fig_pres, use_container_width=True, config={'displayModeBar': False})
                
                perfs = [asset_model.perf_ann(365*10), asset_model.perf_ann(365*5), asset_model.perf(365)]
                vols = [asset_model.vol(365*10), asset_model.vol(365*5), asset_model.vol(365)]
                sharpes = [asset_model.sharpe_ratio(365*10), asset_model.sharpe_ratio(365*5), asset_model.sharpe_ratio(365)]
                drawdowns = [asset_model.max_drawdown(365*10), asset_model.max_drawdown(365*5), asset_model.max_drawdown(365)]
                
                def get_bench_perf_ann(days):
                    if benchmark_prices is None or benchmark_prices.empty: return np.nan
                    cutoff = benchmark_prices.index.max() - pd.Timedelta(days=days)
                    p = benchmark_prices[benchmark_prices.index >= cutoff]
                    if len(p) < 2: return np.nan
                    tot = (p.iloc[-1] / p.iloc[0]) - 1
                    years = days/365
                    if years <= 1: return tot * 100
                    return ((1 + tot)**(1/years) - 1) * 100

                def get_bench_vol(days):
                    if benchmark_prices is None or benchmark_prices.empty: return np.nan
                    cutoff = benchmark_prices.index.max() - pd.Timedelta(days=days)
                    p = benchmark_prices[benchmark_prices.index >= cutoff]
                    if len(p) < 2: return np.nan
                    rets = p.pct_change().dropna()
                    return rets.std() * np.sqrt(252) * 100
                    
                def get_bench_max_drawdown(days):
                    if benchmark_prices is None or benchmark_prices.empty: return np.nan
                    cutoff = benchmark_prices.index.max() - pd.Timedelta(days=days)
                    p = benchmark_prices[benchmark_prices.index >= cutoff]
                    if len(p) < 2: return np.nan
                    roll_max = p.cummax()
                    dd = (p - roll_max) / roll_max
                    return dd.min() * 100
                    
                def get_bench_sharpe(days):
                    if benchmark_prices is None or benchmark_prices.empty: return np.nan
                    ret = get_bench_perf_ann(days)
                    v = get_bench_vol(days)
                    if pd.isna(ret) or pd.isna(v) or v == 0: return np.nan
                    return ret / v
                    
                def get_correlation(days):
                    if benchmark_prices is None or benchmark_prices.empty: return np.nan
                    common = asset_prices.index.intersection(benchmark_prices.index)
                    cutoff = common.max() - pd.Timedelta(days=days)
                    common = common[common >= cutoff]
                    if len(common) < 2: return np.nan
                    ret_a = asset_prices.loc[common].pct_change().dropna()
                    ret_b = benchmark_prices.loc[common].pct_change().dropna()
                    if len(ret_a) < 2: return np.nan
                    return ret_a.corr(ret_b) * 100

                if benchmark_prices is not None:
                    bench_perfs = [get_bench_perf_ann(365*10), get_bench_perf_ann(365*5), get_bench_perf_ann(365)]
                    bench_vols = [get_bench_vol(365*10), get_bench_vol(365*5), get_bench_vol(365)]
                    bench_sharpes = [get_bench_sharpe(365*10), get_bench_sharpe(365*5), get_bench_sharpe(365)]
                    bench_drawdowns = [get_bench_max_drawdown(365*10), get_bench_max_drawdown(365*5), get_bench_max_drawdown(365)]
                    corrs = [get_correlation(365*10), get_correlation(365*5), get_correlation(365)]

                    table_html = f"""
<table style="width:100%; font-family:sans-serif; font-size:12px; text-align:center; margin-top: 15px; border-collapse: collapse; border: none;">
    <tr>
        <td style="border:none; width: 16%; background-color: white;"></td>
        <th colspan="2" style="background-color:#143F6A; color:white; padding:6px; border: 1px solid white; width: 28%;">10 ans</th>
        <th colspan="2" style="background-color:#143F6A; color:white; padding:6px; border: 1px solid white; width: 28%;">5 ans</th>
        <th colspan="2" style="background-color:#143F6A; color:white; padding:6px; border: 1px solid white; width: 28%;">1 an</th>
    </tr>
    <tr>
        <td style="border:none; background-color: white;"></td>
        <td style="background-color:#22578A; color:white; padding:6px; border: 1px solid white; width: 14%;">{ticker_disp}</td>
        <td style="background-color:#22578A; color:white; padding:6px; border: 1px solid white; width: 14%;">{bench_ticker_disp}</td>
        <td style="background-color:#22578A; color:white; padding:6px; border: 1px solid white; width: 14%;">{ticker_disp}</td>
        <td style="background-color:#22578A; color:white; padding:6px; border: 1px solid white; width: 14%;">{bench_ticker_disp}</td>
        <td style="background-color:#22578A; color:white; padding:6px; border: 1px solid white; width: 14%;">{ticker_disp}</td>
        <td style="background-color:#22578A; color:white; padding:6px; border: 1px solid white; width: 14%;">{bench_ticker_disp}</td>
    </tr>
    <tr>
        <td style="background-color:#e6e9ed; color:black; font-weight:bold; padding:6px; border: 1px solid white; text-align:left;">Performance<br>annualisée</td>
        <td style="background-color:#e6e9ed; color:black; padding:6px; border: 1px solid white; font-weight:bold;">{fmt(perfs[0], True)}</td>
        <td style="background-color:#e6e9ed; color:black; padding:6px; border: 1px solid white; font-weight:bold;">{fmt(bench_perfs[0], True)}</td>
        <td style="background-color:#e6e9ed; color:black; padding:6px; border: 1px solid white; font-weight:bold;">{fmt(perfs[1], True)}</td>
        <td style="background-color:#e6e9ed; color:black; padding:6px; border: 1px solid white; font-weight:bold;">{fmt(bench_perfs[1], True)}</td>
        <td style="background-color:#e6e9ed; color:black; padding:6px; border: 1px solid white; font-weight:bold;">{fmt(perfs[2], True)}</td>
        <td style="background-color:#e6e9ed; color:black; padding:6px; border: 1px solid white; font-weight:bold;">{fmt(bench_perfs[2], True)}</td>
    </tr>
    <tr>
        <td style="background-color:#f4f5f7; color:black; font-weight:bold; padding:6px; border: 1px solid white; text-align:left;">Volatilité<br>annualisée</td>
        <td style="background-color:#f4f5f7; color:black; padding:6px; border: 1px solid white; font-weight:bold;">{fmt(vols[0], True)}</td>
        <td style="background-color:#f4f5f7; color:black; padding:6px; border: 1px solid white; font-weight:bold;">{fmt(bench_vols[0], True)}</td>
        <td style="background-color:#f4f5f7; color:black; padding:6px; border: 1px solid white; font-weight:bold;">{fmt(vols[1], True)}</td>
        <td style="background-color:#f4f5f7; color:black; padding:6px; border: 1px solid white; font-weight:bold;">{fmt(bench_vols[1], True)}</td>
        <td style="background-color:#f4f5f7; color:black; padding:6px; border: 1px solid white; font-weight:bold;">{fmt(vols[2], True)}</td>
        <td style="background-color:#f4f5f7; color:black; padding:6px; border: 1px solid white; font-weight:bold;">{fmt(bench_vols[2], True)}</td>
    </tr>
    <tr>
        <td style="background-color:#e6e9ed; color:black; font-weight:bold; padding:6px; border: 1px solid white; text-align:left;">Sharpe Ratio</td>
        <td style="background-color:#e6e9ed; color:black; padding:6px; border: 1px solid white; font-weight:bold;">{fmt(sharpes[0])}</td>
        <td style="background-color:#e6e9ed; color:black; padding:6px; border: 1px solid white; font-weight:bold;">{fmt(bench_sharpes[0])}</td>
        <td style="background-color:#e6e9ed; color:black; padding:6px; border: 1px solid white; font-weight:bold;">{fmt(sharpes[1])}</td>
        <td style="background-color:#e6e9ed; color:black; padding:6px; border: 1px solid white; font-weight:bold;">{fmt(bench_sharpes[1])}</td>
        <td style="background-color:#e6e9ed; color:black; padding:6px; border: 1px solid white; font-weight:bold;">{fmt(sharpes[2])}</td>
        <td style="background-color:#e6e9ed; color:black; padding:6px; border: 1px solid white; font-weight:bold;">{fmt(bench_sharpes[2])}</td>
    </tr>
    <tr>
        <td style="background-color:#f4f5f7; color:black; font-weight:bold; padding:6px; border: 1px solid white; text-align:left;">Max Drawdown</td>
        <td style="background-color:#f4f5f7; color:black; padding:6px; border: 1px solid white; font-weight:bold;">{fmt(drawdowns[0], True)}</td>
        <td style="background-color:#f4f5f7; color:black; padding:6px; border: 1px solid white; font-weight:bold;">{fmt(bench_drawdowns[0], True)}</td>
        <td style="background-color:#f4f5f7; color:black; padding:6px; border: 1px solid white; font-weight:bold;">{fmt(drawdowns[1], True)}</td>
        <td style="background-color:#f4f5f7; color:black; padding:6px; border: 1px solid white; font-weight:bold;">{fmt(bench_drawdowns[1], True)}</td>
        <td style="background-color:#f4f5f7; color:black; padding:6px; border: 1px solid white; font-weight:bold;">{fmt(drawdowns[2], True)}</td>
        <td style="background-color:#f4f5f7; color:black; padding:6px; border: 1px solid white; font-weight:bold;">{fmt(bench_drawdowns[2], True)}</td>
    </tr>
    <tr>
        <td style="background-color:#e6e9ed; color:black; font-weight:bold; padding:6px; border: 1px solid white; text-align:left;">Corrélation</td>
        <td colspan="2" style="background-color:#e6e9ed; color:black; padding:6px; border: 1px solid white; font-weight:bold;">{fmt(corrs[0], True)}</td>
        <td colspan="2" style="background-color:#e6e9ed; color:black; padding:6px; border: 1px solid white; font-weight:bold;">{fmt(corrs[1], True)}</td>
        <td colspan="2" style="background-color:#e6e9ed; color:black; padding:6px; border: 1px solid white; font-weight:bold;">{fmt(corrs[2], True)}</td>
    </tr>
</table>
"""
                else:
                    table_html = f"""
<table style="width:100%; font-family:sans-serif; font-size:12px; text-align:center; margin-top: 15px; border-collapse: collapse; border: none;">
    <tr>
        <td style="border:none; width: 25%; background-color: white;"></td>
        <th style="background-color:#143F6A; color:white; padding:6px; border: 1px solid white; width: 25%;">10 ans</th>
        <th style="background-color:#143F6A; color:white; padding:6px; border: 1px solid white; width: 25%;">5 ans</th>
        <th style="background-color:#143F6A; color:white; padding:6px; border: 1px solid white; width: 25%;">1 an</th>
    </tr>
    <tr>
        <td style="border:none; background-color: white;"></td>
        <td style="background-color:#22578A; color:white; padding:6px; border: 1px solid white;">{ticker_disp}</td>
        <td style="background-color:#22578A; color:white; padding:6px; border: 1px solid white;">{ticker_disp}</td>
        <td style="background-color:#22578A; color:white; padding:6px; border: 1px solid white;">{ticker_disp}</td>
    </tr>
    <tr>
        <td style="background-color:#e6e9ed; color:black; font-weight:bold; padding:6px; border: 1px solid white; text-align:left;">Performance<br>annualisée</td>
        <td style="background-color:#e6e9ed; color:black; padding:6px; border: 1px solid white;">{fmt(perfs[0], True)}</td>
        <td style="background-color:#e6e9ed; color:black; padding:6px; border: 1px solid white;">{fmt(perfs[1], True)}</td>
        <td style="background-color:#e6e9ed; color:black; padding:6px; border: 1px solid white;">{fmt(perfs[2], True)}</td>
    </tr>
    <tr>
        <td style="background-color:#f4f5f7; color:black; font-weight:bold; padding:6px; border: 1px solid white; text-align:left;">Volatilité<br>annualisée</td>
        <td style="background-color:#f4f5f7; color:black; padding:6px; border: 1px solid white;">{fmt(vols[0], True)}</td>
        <td style="background-color:#f4f5f7; color:black; padding:6px; border: 1px solid white;">{fmt(vols[1], True)}</td>
        <td style="background-color:#f4f5f7; color:black; padding:6px; border: 1px solid white;">{fmt(vols[2], True)}</td>
    </tr>
    <tr>
        <td style="background-color:#e6e9ed; color:black; font-weight:bold; padding:6px; border: 1px solid white; text-align:left;">Sharpe Ratio</td>
        <td style="background-color:#e6e9ed; color:black; padding:6px; border: 1px solid white;">{fmt(sharpes[0])}</td>
        <td style="background-color:#e6e9ed; color:black; padding:6px; border: 1px solid white;">{fmt(sharpes[1])}</td>
        <td style="background-color:#e6e9ed; color:black; padding:6px; border: 1px solid white;">{fmt(sharpes[2])}</td>
    </tr>
    <tr>
        <td style="background-color:#f4f5f7; color:black; font-weight:bold; padding:6px; border: 1px solid white; text-align:left;">Max Drawdown</td>
        <td style="background-color:#f4f5f7; color:black; padding:6px; border: 1px solid white;">{fmt(drawdowns[0], True)}</td>
        <td style="background-color:#f4f5f7; color:black; padding:6px; border: 1px solid white;">{fmt(drawdowns[1], True)}</td>
        <td style="background-color:#f4f5f7; color:black; padding:6px; border: 1px solid white;">{fmt(drawdowns[2], True)}</td>
    </tr>
</table>
"""
                st.markdown(table_html, unsafe_allow_html=True)
            else:
                st.info("Historique de cours non disponible pour cet actif dans la base de données. Le graphique et les performances pluriannuelles nécessitent des cours.")
                fig_pres = None
                perfs = [np.nan, np.nan, np.nan]
                vols = [np.nan, np.nan, np.nan]
                sharpes = [np.nan, np.nan, np.nan]
                drawdowns = [np.nan, np.nan, np.nan]

        st.markdown("<br>", unsafe_allow_html=True)
        with st.spinner("Génération du slide PPTX Client..."):
            left_data_list = []
            left_data_list.append([f"Niveau de l'indice au {date_str}", curr_price_str])
            if dec_val is not None:
                left_data_list.append([f"Taux de décrément au {date_str}", f"{dec_val_pct}"])
                left_data_list.append(["Taux de dividende 2025 avec effet de réinvestissement", f"{div_val_pct}"])
            else:
                left_data_list.append(["Taux de dividende 2025", f"{div_val_pct}"])
                
            nexo_data_list = [
                (vol_disp, color_vol),
                (yield_disp, color_yield),
                (ecart_disp, color_ecart)
            ]
            if has_prices and benchmark_prices is not None:
                df_right = pd.DataFrame({
                    "C1": ["", "Performance annualisée", "Volatilité annualisée", "Sharpe Ratio", "Max Drawdown", "Corrélation"],
                    "C2": [ticker_disp, fmt(perfs[0], True), fmt(vols[0], True), fmt(sharpes[0]), fmt(drawdowns[0], True), fmt(corrs[0], True)],
                    "C3": [bench_ticker_disp, fmt(bench_perfs[0], True), fmt(bench_vols[0], True), fmt(bench_sharpes[0]), fmt(bench_drawdowns[0], True), "MERGE"],
                    "C4": [ticker_disp, fmt(perfs[1], True), fmt(vols[1], True), fmt(sharpes[1]), fmt(drawdowns[1], True), fmt(corrs[1], True)],
                    "C5": [bench_ticker_disp, fmt(bench_perfs[1], True), fmt(bench_vols[1], True), fmt(bench_sharpes[1]), fmt(bench_drawdowns[1], True), "MERGE"],
                    "C6": [ticker_disp, fmt(perfs[2], True), fmt(vols[2], True), fmt(sharpes[2]), fmt(drawdowns[2], True), fmt(corrs[2], True)],
                    "C7": [bench_ticker_disp, fmt(bench_perfs[2], True), fmt(bench_vols[2], True), fmt(bench_sharpes[2]), fmt(bench_drawdowns[2], True), "MERGE"]
                })
                tmpl = "template_nexo_benchmark.pptx"
            else:
                df_right = pd.DataFrame({
                    "1": ["", "Performance annualisée", "Volatilité annualisée", "Sharpe Ratio", "Max Drawdown"],
                    "2": [ticker_disp, fmt(perfs[0], True), fmt(vols[0], True), fmt(sharpes[0]), fmt(drawdowns[0], True)],
                    "3": [ticker_disp, fmt(perfs[1], True), fmt(vols[1], True), fmt(sharpes[1]), fmt(drawdowns[1], True)],
                    "4": [ticker_disp, fmt(perfs[2], True), fmt(vols[2], True), fmt(sharpes[2]), fmt(drawdowns[2], True)]
                })
                tmpl = "template_nexo.pptx"
            
            pptx_buffer = create_nexo_presentation_pptx(asset_name_str, desc, left_data_list, nexo_data_list, df_right, fig_pres, template_name=tmpl)
            
        st.download_button(
            label="Télécharger ce Slide en PPTX natif",
            data=pptx_buffer,
            file_name=f"Presentation_Client_{selected_asset_name}.pptx",
            mime="application/vnd.openxmlformats-officedocument.presentationml.presentation",
            use_container_width=True
        )

        st.divider()
        st.markdown("<div class='section-title'>Exporter le rapport Détaillé</div>", unsafe_allow_html=True)
        with st.expander("Générer les fichiers Excel et PowerPoint"):
            if st.button(f"Préparer l'exportation pour {selected_asset_name}", key="btn_export_detail"):
                with st.spinner("Génération des fichiers..."):
                    perf_data_exp = {
                        "5 Jours": asset_model.perf(days=5) if has_prices else np.nan,
                        "1 Mois": asset_model.perf(days=30) if has_prices else np.nan,
                        "3 Mois": asset_model.perf(days=90) if has_prices else np.nan,
                        "YTD": asset_model.perf(ytd=True) if has_prices else np.nan,
                    }
                    vol_data_exp = {
                        "1 Mois": asset_model.vol(days=30) if has_prices else np.nan,
                        "3 Mois": asset_model.vol(days=90) if has_prices else np.nan,
                        "YTD": asset_model.vol(ytd=True) if has_prices else np.nan,
                        "1 An": asset_model.vol(days=365) if has_prices else np.nan,
                    }
                    beta_data_exp = {
                        "1 An": asset_model.beta(days=365) if has_prices else np.nan,
                        "3 Ans": asset_model.beta(days=365*3) if has_prices else np.nan,
                    }
                    dfs_export = {
                        "Performances": pd.DataFrame([perf_data_exp]).T.reset_index().rename(columns={"index": "Période", 0: "Performance"}),
                        "Volatilité": pd.DataFrame([vol_data_exp]).T.reset_index().rename(columns={"index": "Période", 0: "Volatilité"}),
                        "Bêta": pd.DataFrame([beta_data_exp]).T.reset_index().rename(columns={"index": "Période", 0: "Coefficient"})
                    }
                    
                    figs_export = {}
                    if has_prices and fig_pres is not None:
                        figs_export["Cours"] = fig_pres
                    
                    st.session_state["detail_exports"] = {
                        "excel": create_excel_report(dfs_export, figs_export),
                        "pptx": create_pptx_report(dfs_export, figs_export, title=f"Fiche Détaillée: {selected_asset_name}")
                    }
            if "detail_exports" in st.session_state:
                st.download_button("Télécharger Excel", st.session_state["detail_exports"]["excel"], file_name=f"fiche_detaillee.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
                st.download_button("Télécharger PowerPoint", st.session_state["detail_exports"]["pptx"], file_name=f"fiche_detaillee.pptx", mime="application/vnd.openxmlformats-officedocument.presentationml.presentation")

    # --------------------------------------------------------------------------
    # SOUS-SECTION 2 : ANALYSE TECHNIQUE & MARCHÉ
    # --------------------------------------------------------------------------
    with sub_tab2:
        if not has_prices:
            st.info("L'analyse technique, le suivi des moyennes mobiles (SMA 50 / SMA 200) et la volatilité glissante nécessitent un historique de cours quotidien pour cet actif.")
        else:
            cours_disp = f" (Dernier cours : {current_price:.2f})" if pd.notna(current_price) else ""
            st.markdown(f"<div class='section-title'>Performances et Risques{cours_disp}</div>", unsafe_allow_html=True)

            perf_data = {
                "5 Jours": asset_model.perf(days=5),
                "1 Mois": asset_model.perf(days=30),
                "3 Mois": asset_model.perf(days=90),
                "YTD": asset_model.perf(ytd=True),
            }

            vol_data = {
                "1 Mois": asset_model.vol(days=30),
                "3 Mois": asset_model.vol(days=90),
                "YTD": asset_model.vol(ytd=True),
                "1 An": asset_model.vol(days=365),
            }
            
            beta_data = {
                "1 An": asset_model.beta(days=365),
                "3 Ans": asset_model.beta(days=365*3),
            }

            col_perf, col_vol, col_beta = st.columns(3)

            with col_perf:
                st.markdown("**Performances**")
                perf_df = pd.DataFrame([perf_data]).T.reset_index()
                perf_df.columns = ["Période", "Performance"]
                st.dataframe(perf_df.style.format({"Performance": "{:.2f} %"}), use_container_width=True, hide_index=True)

            with col_vol:
                st.markdown("**Volatilité Annualisée**")
                vol_df = pd.DataFrame([vol_data]).T.reset_index()
                vol_df.columns = ["Période", "Volatilité"]
                st.dataframe(vol_df.style.format({"Volatilité": "{:.2f} %"}), use_container_width=True, hide_index=True)
                
            with col_beta:
                bench_disp = benchmark_ticker if benchmark_ticker else "N/A"
                st.markdown(f"**Bêta (vs {bench_disp})**")
                beta_df = pd.DataFrame([beta_data]).T.reset_index()
                beta_df.columns = ["Période", "Coefficient"]
                st.dataframe(beta_df.style.format({"Coefficient": "{:.2f}"}, na_rep="N/A"), use_container_width=True, hide_index=True)

            st.divider()

            # Graphique Technique du Cours avec SMAs
            st.markdown("<div class='section-title'>Cours & Moyennes Mobiles</div>", unsafe_allow_html=True)

            show_benchmark = False
            if benchmark_asset_id and benchmark_asset_id in prices_pivot.columns:
                show_benchmark = st.checkbox(f"Afficher la comparaison avec le Benchmark {benchmark_ticker} (Rebasé sur le prix de l'actif)", value=True)

            fig = go.Figure()

            if show_benchmark:
                bench_prices = prices_pivot[benchmark_asset_id].dropna()
                bench_prices = bench_prices[bench_prices > 0]
                
                asset_norm = asset_prices
                common_dates = asset_prices.index.intersection(bench_prices.index)
                if len(common_dates) > 0:
                    first_common = common_dates[0]
                    bench_sub = bench_prices[bench_prices.index >= first_common]
                    bench_norm = (bench_sub / bench_prices.loc[first_common]) * asset_prices.loc[first_common]
                    
                    fig.add_trace(go.Scatter(
                        x=bench_norm.index, y=bench_norm, mode='lines', 
                        name=f'Benchmark ({benchmark_ticker})', 
                        line=dict(color='gray', width=1.5, dash='dot')
                    ))
                
                sma50 = asset_model.sma(50)
                sma200 = asset_model.sma(200)
                
                fig.add_trace(go.Scatter(x=asset_norm.index, y=asset_norm, mode='lines', name='Prix', line=dict(color='#143F6A', width=2)))
                fig.add_trace(go.Scatter(x=sma50.index, y=sma50, mode='lines', name='SMA 50', line=dict(color='#00d2ff', width=1.5)))
                fig.add_trace(go.Scatter(x=sma200.index, y=sma200, mode='lines', name='SMA 200', line=dict(color='#ff512f', width=1.5)))
            else:
                sma50 = asset_model.sma(50)
                sma200 = asset_model.sma(200)
                
                fig.add_trace(go.Scatter(x=asset_prices.index, y=asset_prices, mode='lines', name='Prix', line=dict(color='#143F6A', width=2)))
                fig.add_trace(go.Scatter(x=sma50.index, y=sma50, mode='lines', name='SMA 50', line=dict(color='#00d2ff', width=1.5)))
                fig.add_trace(go.Scatter(x=sma200.index, y=sma200, mode='lines', name='SMA 200', line=dict(color='#ff512f', width=1.5)))

            fig.update_layout(
                hovermode="x unified",
                height=480,
                margin=dict(l=0, r=0, t=30, b=0),
                plot_bgcolor='white',
                paper_bgcolor='white',
                xaxis=dict(gridcolor='#e6e9ed'),
                yaxis=dict(gridcolor='#e6e9ed')
            )
            st.plotly_chart(fig, use_container_width=True)

            st.divider()

            # Volatilité Annuelle Glissante
            st.markdown("<div class='section-title'>Volatilité Annualisée (1 An Glissant)</div>", unsafe_allow_html=True)
            roll_vol = asset_model.rolling_vol(window_days=252)
            
            fig_vol = go.Figure()
            fig_vol.add_trace(go.Scatter(
                x=roll_vol.index, y=roll_vol, mode='lines', name='Volatilité', 
                line=dict(color='#ff9900', width=2)
            ))
            fig_vol.update_layout(
                hovermode="x unified",
                height=380,
                margin=dict(l=0, r=0, t=30, b=0), 
                yaxis_title="Volatilité (%)",
                plot_bgcolor='white',
                paper_bgcolor='white',
                xaxis=dict(gridcolor='#e6e9ed'),
                yaxis=dict(gridcolor='#e6e9ed')
            )
            st.plotly_chart(fig_vol, use_container_width=True)

    # --------------------------------------------------------------------------
    # SOUS-SECTION 3 : RELATIONS & CORRÉLATIONS
    # --------------------------------------------------------------------------
    with sub_tab3:
        if not has_prices:
            st.info("L'analyse des corrélations et de sensibilité au benchmark nécessite un historique de cours quotidien pour cet actif.")
        else:
            st.markdown("<div class='section-title'>Analyse des Corrélations (1 An Glissant)</div>", unsafe_allow_html=True)

            subtypes = sorted([str(x) for x in assets_df['asset_subtype'].dropna().unique()])
            sectors = sorted([str(x) for x in assets_df['sector'].dropna().unique()])
            countries = sorted([str(x) for x in assets_df['country'].dropna().unique()])

            col_f1_c, col_f2_c, col_f3_c = st.columns(3)
            with col_f1_c:
                filter_subtype = st.multiselect("Filtre Sous Type", options=subtypes, key="corr_subtype")
            with col_f2_c:
                filter_sector = st.multiselect("Filtre Secteur", options=sectors, key="corr_sector")
            with col_f3_c:
                filter_country = st.multiselect("Filtre Pays", options=countries, key="corr_country")

            with st.spinner("Calcul des corrélations en cours..."):
                one_year_ago = current_date - pd.Timedelta(days=365)
                prices_1y_c = prices_pivot[prices_pivot.index >= one_year_ago]
                
                mask = pd.Series(True, index=assets_df.index)
                if len(filter_subtype) > 0:
                    mask = mask & (assets_df['asset_subtype'].isin(filter_subtype))
                if len(filter_sector) > 0:
                    mask = mask & (assets_df['sector'].isin(filter_sector))
                if len(filter_country) > 0:
                    mask = mask & (assets_df['country'].isin(filter_country))

                valid_ids = assets_df[mask]['asset_id'].tolist()
                
                if selected_asset_id not in valid_ids:
                    valid_ids.append(selected_asset_id)
                valid_ids = [vid for vid in valid_ids if vid in prices_1y_c.columns]
                prices_1y_c = prices_1y_c[valid_ids]
                
                returns_1y_c = prices_1y_c.pct_change(fill_method=None).dropna(how='all')
                if selected_asset_id in returns_1y_c.columns:
                    corr_series = returns_1y_c.corrwith(returns_1y_c[selected_asset_id]).dropna()
                    corr_series = corr_series.drop(index=selected_asset_id, errors='ignore')
                    
                    if len(corr_series) > 0:
                        id_to_name = dict(zip(assets_df['asset_id'], assets_df['display_name']))
                        corr_df = corr_series.reset_index()
                        corr_df.columns = ['asset_id', 'Correlation']
                        corr_df['Nom de l\'actif'] = corr_df['asset_id'].map(id_to_name)
                        
                        top_10 = corr_df.nlargest(10, 'Correlation')[['Nom de l\'actif', 'Correlation']]
                        bottom_10 = corr_df.nsmallest(10, 'Correlation')[['Nom de l\'actif', 'Correlation']]
                        
                        col_top, col_bottom = st.columns(2)
                        with col_top:
                            st.markdown("**Les plus corrélés**")
                            st.dataframe(top_10.style.format({'Correlation': "{:.4f}"}), use_container_width=True, hide_index=True)
                        with col_bottom:
                            st.markdown("**Les moins corrélés**")
                            st.dataframe(bottom_10.style.format({'Correlation': "{:.4f}"}), use_container_width=True, hide_index=True)
                    else:
                        st.info("Pas assez de données pour calculer les corrélations sur cet univers.")
                else:
                    st.warning("L'actif sélectionné n'a pas de données sur la dernière année.")


# ==============================================================================
# MODULE 3 : COMPARAISON MULTI-ACTIFS (Base 100)
# ==============================================================================
elif selected_nav == "Comparaison Multi-Actifs":
    st.markdown("<h1 class='main-header'>Comparaison Multi-Actifs (Base 100)</h1>", unsafe_allow_html=True)
    
    selected_compare_names = st.multiselect(
        "Ajoutez des actifs à comparer :",
        options=sorted(asset_options.keys()),
        default=[],
        key="compare_assets_multiselect"
    )

    if len(selected_compare_names) > 0:
        selected_ids = [asset_options[name] for name in selected_compare_names]
        valid_ids = [aid for aid in selected_ids if aid in prices_pivot.columns]
        
        if len(valid_ids) == 0:
            st.warning("Aucun historique de prix n'est disponible pour les actifs sélectionnés.")
        else:
            compare_prices = prices_pivot[valid_ids].dropna(how='all')
            min_avail_date = compare_prices.index.min().date()
            max_avail_date = compare_prices.index.max().date()

            # Barre de contrôle compacte de la période
            with st.container():
                col_filter_choice, col_custom_dates = st.columns([3, 2])
                with col_filter_choice:
                    time_filter = st.radio(
                        "Période",
                        ["1 Mois", "3 Mois", "YTD", "1 An", "3 Ans", "5 Ans", "Max", "Personnalisée"],
                        index=6,
                        horizontal=True,
                        key="compare_time_filter"
                    )
                
                # Filtre temporel
                current_date = compare_prices.index.max()
                if time_filter == "1 Mois":
                    cutoff_start = current_date - pd.Timedelta(days=30)
                    cutoff_end = current_date
                elif time_filter == "3 Mois":
                    cutoff_start = current_date - pd.Timedelta(days=90)
                    cutoff_end = current_date
                elif time_filter == "YTD":
                    cutoff_start = pd.Timestamp(year=current_date.year - 1, month=12, day=31)
                    cutoff_end = current_date
                elif time_filter == "1 An":
                    cutoff_start = current_date - pd.Timedelta(days=365)
                    cutoff_end = current_date
                elif time_filter == "3 Ans":
                    cutoff_start = current_date - pd.Timedelta(days=365*3)
                    cutoff_end = current_date
                elif time_filter == "5 Ans":
                    cutoff_start = current_date - pd.Timedelta(days=365*5)
                    cutoff_end = current_date
                elif time_filter == "Max":
                    cutoff_start = compare_prices.index.min()
                    cutoff_end = current_date
                else:  # "Personnalisée"
                    with col_custom_dates:
                        col_d1, col_d2 = st.columns(2)
                        with col_d1:
                            default_start = max(min_avail_date, (max_avail_date - pd.Timedelta(days=365).to_pytimedelta()))
                            custom_start = st.date_input(
                                "Date de début :",
                                value=default_start,
                                min_value=min_avail_date,
                                max_value=max_avail_date,
                                key="compare_custom_start"
                            )
                        with col_d2:
                            custom_end = st.date_input(
                                "Date de fin :",
                                value=max_avail_date,
                                min_value=min_avail_date,
                                max_value=max_avail_date,
                                key="compare_custom_end"
                            )
                    cutoff_start = pd.to_datetime(custom_start)
                    cutoff_end = pd.to_datetime(custom_end)
                
            # Instanciation de BasketAnalytics
            basket_model = BasketAnalytics(valid_ids, asset_options, prices_pivot, cutoff_start, cutoff_end)
            
            if pd.isna(basket_model.common_start_date) or basket_model.base_100_prices.empty:
                st.warning("Aucune période commune trouvée entre ces actifs pour la période sélectionnée.")
            else:
                common_start_date = basket_model.common_start_date
                if common_start_date > cutoff_start:
                    st.info(f"Point de départ commun calé au {common_start_date.strftime('%d/%m/%Y')} (première date où tous les actifs sélectionnés cotent ensemble).")

                base_100_prices = basket_model.base_100_prices
                compare_prices_common = basket_model.compare_prices_common

                # -------------------------------------------------------------
                # 3 SOUS-ONGLETS THÉMATIQUES DE COMPARAISON
                # -------------------------------------------------------------
                if len(valid_ids) > 1:
                    comp_tab1, comp_tab2, comp_tab3 = st.tabs([
                        "Trajectoires & Performances",
                        "Panier Équipondéré",
                        "Matrice des Corrélations"
                    ])
                else:
                    comp_tab1 = st.container()
                    comp_tab2 = None
                    comp_tab3 = None

                # --- ONGLET 1 : TRAJECTOIRES & PERFORMANCES ---
                with comp_tab1:
                    st.markdown("<div class='section-title'>Évolution des Cours (Base 100)</div>", unsafe_allow_html=True)
                    
                    fig = go.Figure()
                    for aid in valid_ids:
                        name_disp = [k for k, v in asset_options.items() if v == aid][0]
                        fig.add_trace(go.Scatter(
                            x=base_100_prices.index,
                            y=base_100_prices[aid],
                            mode='lines',
                            name=name_disp,
                            line=dict(width=2)
                        ))
                    
                    fig.update_layout(
                        hovermode="x unified",
                        height=480,
                        margin=dict(l=0, r=0, t=30, b=0),
                        yaxis_title="Base 100",
                        plot_bgcolor='white',
                        paper_bgcolor='white',
                        xaxis=dict(gridcolor='#e6e9ed'),
                        yaxis=dict(gridcolor='#e6e9ed'),
                        legend=dict(
                            orientation="h",
                            yanchor="top",
                            y=-0.1,
                            xanchor="center",
                            x=0.5
                        )
                    )
                    st.plotly_chart(fig, use_container_width=True)
                    
                    # Tableau synthétique côte à côte des actifs
                    st.markdown(f"**Synthèse des performances et risques depuis le point commun ({common_start_date.strftime('%d/%m/%Y')})**")
                    summary_rows = []
                    for aid in valid_ids:
                        name_disp = [k for k, v in asset_options.items() if v == aid][0]
                        p_series = compare_prices_common[aid].dropna()
                        last_p = float(p_series.iloc[-1])
                        perf_pct = float((p_series.iloc[-1] / p_series.iloc[0] - 1.0) * 100.0)
                        rets = p_series.pct_change().dropna()
                        vol_pct = float(rets.std() * np.sqrt(252) * 100.0) if len(rets) > 1 else np.nan
                        cummax = p_series.cummax()
                        dd_pct = float(((p_series - cummax) / cummax).min() * 100.0) if len(p_series) > 0 else np.nan
                        summary_rows.append({
                            "Actif": name_disp,
                            "Dernier Cours": last_p,
                            "Performance Période": perf_pct,
                            "Volatilité Ann.": vol_pct,
                            "Max Drawdown": dd_pct
                        })
                    summary_df = pd.DataFrame(summary_rows)
                    
                    st.dataframe(
                        summary_df.style.format({
                            'Dernier Cours': "{:.2f}",
                            'Performance Période': "{:+.2f} %",
                            'Volatilité Ann.': "{:.2f} %",
                            'Max Drawdown': "{:.2f} %"
                        }, na_rep="N/A"),
                        use_container_width=True,
                        hide_index=True
                    )
                    
                    st.divider()
                    st.markdown("<div class='section-title'>Comparaison des Volatilités (1 An Glissant)</div>", unsafe_allow_html=True)
                    fig_vol_comp = go.Figure()
                    for aid in valid_ids:
                        name_disp = [k for k, v in asset_options.items() if v == aid][0]
                        clean_prices = compare_prices_common[aid].replace(0, np.nan).dropna()
                        asset_returns = clean_prices.pct_change()
                        roll_vol = asset_returns.rolling(window=252, min_periods=252).std() * np.sqrt(252) * 100
                        
                        fig_vol_comp.add_trace(go.Scatter(
                            x=roll_vol.index, y=roll_vol, mode='lines', name=name_disp, line=dict(width=1.5)
                        ))
                    
                    fig_vol_comp.update_layout(
                        hovermode="x unified", height=420, margin=dict(l=0, r=0, t=30, b=0),
                        yaxis_title="Volatilité Annualisée (%)",
                        plot_bgcolor='white',
                        paper_bgcolor='white',
                        xaxis=dict(gridcolor='#e6e9ed'),
                        yaxis=dict(gridcolor='#e6e9ed'),
                        legend=dict(orientation="h", yanchor="top", y=-0.1, xanchor="center", x=0.5)
                    )
                    st.plotly_chart(fig_vol_comp, use_container_width=True)

                # --- VARIABLES POUR LE PANIER & BENCHMARK ---
                fig_basket = None
                fig_basket_bench_corr = None
                fig_heatmap = None
                fig_corr = None
                df_comp = None
                corr_matrix_named = None

                # --- ONGLET 2 : PANIER ÉQUIPONDÉRÉ ---
                if comp_tab2 is not None:
                    with comp_tab2:
                        st.markdown("<div class='section-title'>Performance du Panier Équipondéré</div>", unsafe_allow_html=True)
                        st.markdown("Évolution d'un portefeuille théorique investi à parts égales sur les actifs sélectionnés à la date de départ (sans rebalancement).")
                        
                        # Sélection du benchmark parmi tous les indices disponibles
                        index_mask = (
                            (assets_df['asset_type'].astype(str).str.lower() == 'indice') |
                            (assets_df['asset_subtype'].astype(str).str.lower().str.contains('indice', na=False)) |
                            (assets_df['ticker_bloomberg'].astype(str).str.upper().str.endswith('INDEX'))
                        )
                        bench_df = assets_df[index_mask & assets_df['asset_id'].isin(prices_pivot.columns)]
                        bench_df = bench_df.drop_duplicates(subset=['asset_id']).sort_values(by='name')
                        
                        bench_options = {"(Aucun Benchmark)": None}
                        for _, r in bench_df.iterrows():
                            label = f"{r['name']} ({r['ticker_bloomberg']})" if pd.notna(r['ticker_bloomberg']) else r['name']
                            bench_options[label] = r['asset_id']
                        
                        selected_bench_name = st.selectbox(
                            "Comparer le Panier avec un Benchmark (Indice) :",
                            options=list(bench_options.keys()),
                            index=0,
                            key="basket_bench_select"
                        )
                        selected_bench_id = bench_options[selected_bench_name]

                        basket_prices = basket_model.basket_prices
                        basket_perf = float(basket_prices.iloc[-1] - 100.0)
                        
                        df_comp, bench_base_100, beta_disp, comb_ret = basket_model.compute_basket_comparison(
                            selected_bench_id, selected_bench_name, prices_pivot
                        )

                        # 4 Cartes KPI du Panier
                        col_k1, col_k2, col_k3, col_k4 = st.columns(4)
                        with col_k1:
                            st.metric("Performance Panier", f"{basket_perf:+.2f} %")
                        with col_k2:
                            if bench_base_100 is not None:
                                bench_perf = float(bench_base_100.iloc[-1] - 100.0)
                                st.metric(f"Perf Benchmark", f"{bench_perf:+.2f} %")
                            else:
                                st.metric("Perf Benchmark", "N/A")
                        with col_k3:
                            if bench_base_100 is not None:
                                spread = basket_perf - bench_perf
                                st.metric("Écart Panier - Bench", f"{spread:+.2f} %")
                            else:
                                st.metric("Écart Panier - Bench", "N/A")
                        with col_k4:
                            st.metric("Bêta du Panier (vs Bench)", beta_disp)

                        st.markdown("<br>", unsafe_allow_html=True)
                        
                        # Graphique Panier vs Benchmark
                        fig_basket = go.Figure()
                        fig_basket.add_trace(go.Scatter(
                            x=basket_prices.index,
                            y=basket_prices,
                            mode='lines',
                            name='Panier Équipondéré',
                            line=dict(width=3, color='#FF9900')
                        ))
                        
                        if bench_base_100 is not None:
                            fig_basket.add_trace(go.Scatter(
                                x=bench_base_100.index,
                                y=bench_base_100,
                                mode='lines',
                                name=f"Benchmark ({selected_bench_name})",
                                line=dict(width=2, color='#00d2ff', dash='dash')
                            ))
                        
                        fig_basket.update_layout(
                            hovermode="x unified",
                            height=420,
                            margin=dict(l=0, r=0, t=30, b=0),
                            yaxis_title="Base 100",
                            plot_bgcolor='white',
                            paper_bgcolor='white',
                            xaxis=dict(gridcolor='#e6e9ed'),
                            yaxis=dict(gridcolor='#e6e9ed'),
                            showlegend=True,
                            legend=dict(
                                orientation="h",
                                yanchor="top",
                                y=-0.1,
                                xanchor="center",
                                x=0.5
                            )
                        )
                        st.plotly_chart(fig_basket, use_container_width=True)
                        
                        # Tableau comparatif institutionnel
                        if df_comp is not None:
                            st.markdown("<div class='section-title'>Tableau Comparatif Détaillé</div>", unsafe_allow_html=True)
                            st.dataframe(df_comp, hide_index=True, use_container_width=True)

                # --- ONGLET 3 : MATRICE DES CORRÉLATIONS ---
                if comp_tab3 is not None:
                    with comp_tab3:
                        # 1. Matrice classique et institutionnelle des corrélations croisées directes
                        st.markdown("<div class='section-title'>Matrice Carrée des Corrélations</div>", unsafe_allow_html=True)
                        st.markdown("Corrélations des rendements quotidiens calculées sur la période d'analyse commune.")

                        returns_df = compare_prices_common.pct_change(fill_method=None).dropna()
                        id_to_name = {v: k for k, v in asset_options.items()}
                        corr_matrix_named = returns_df.rename(columns=id_to_name).corr()

                        # Affichage de la table classique avec en-têtes strictement au-dessus
                        corr_table_html = render_classic_corr_table(corr_matrix_named, assets_df=assets_df)
                        st.markdown(corr_table_html, unsafe_allow_html=True)
                        fig_heatmap = None

                        st.divider()

                        # 2. Corrélation Rolling 1 An : Panier vs Benchmark
                        if 'selected_bench_id' in locals() and selected_bench_id is not None and 'comb_ret' in locals() and comb_ret is not None:
                            st.markdown("<div class='section-title'>Corrélation Rolling 1 An : Panier vs Benchmark</div>", unsafe_allow_html=True)
                            st.markdown(f"Évolution de la corrélation glissante des rendements quotidiens sur 1 an (252 jours) entre le Panier Équipondéré et **{selected_bench_name}**.")
                            
                            if len(comb_ret) >= 30:
                                min_periods_corr = 252 if len(comb_ret) >= 252 else max(20, len(comb_ret) // 2)
                                roll_corr_bb = comb_ret['Panier'].rolling(window=252, min_periods=min_periods_corr).corr(comb_ret['Benchmark'])
                                
                                fig_basket_bench_corr = go.Figure()
                                fig_basket_bench_corr.add_hline(
                                    y=0, line_dash="dash", line_color="rgba(128, 128, 128, 0.4)", line_width=1
                                )
                                fig_basket_bench_corr.add_trace(go.Scatter(
                                    x=roll_corr_bb.index,
                                    y=roll_corr_bb,
                                    mode='lines',
                                    name=f"Corrélation Panier vs Benchmark",
                                    line=dict(width=2, color='#00d2ff')
                                ))
                                
                                fig_basket_bench_corr.update_layout(
                                    hovermode="x unified",
                                    height=360,
                                    margin=dict(l=0, r=0, t=30, b=0),
                                    yaxis_title="Corrélation",
                                    yaxis=dict(range=[-1.05, 1.05], gridcolor='#e6e9ed'),
                                    xaxis=dict(gridcolor='#e6e9ed'),
                                    plot_bgcolor='white',
                                    paper_bgcolor='white',
                                    showlegend=True,
                                    legend=dict(
                                        orientation="h",
                                        yanchor="top",
                                        y=-0.1,
                                        xanchor="center",
                                        x=0.5
                                    )
                                )
                                st.plotly_chart(fig_basket_bench_corr, use_container_width=True)
                                
                                valid_corrs = roll_corr_bb.dropna()
                                if not valid_corrs.empty:
                                    c_c1, c_c2 = st.columns(2)
                                    c_c1.metric("Dernière Corrélation Glissante (1 An)", f"{valid_corrs.iloc[-1]:.2f}")
                                    c_c2.metric("Corrélation Moyenne sur la Période", f"{valid_corrs.mean():.2f}")
                            else:
                                st.info("Données insuffisantes sur la période pour calculer la corrélation glissante (minimum 30 jours requis).")

                            st.divider()

                        # 3. Corrélations Croisées Dynamiques (1 An Glissant)
                        st.markdown("<div class='section-title'>Corrélation Croisée Dynamique (1 An Glissant)</div>", unsafe_allow_html=True)
                        st.markdown("Évolution de la corrélation des rendements quotidiens entre les paires d'actifs sur une fenêtre glissante de 1 an (252 jours).")
                        
                        fig_corr = go.Figure()
                        pairs = list(itertools.combinations(valid_ids, 2))
                        
                        for aid1, aid2 in pairs[:10]:
                            name1 = [k for k, v in asset_options.items() if v == aid1][0]
                            name2 = [k for k, v in asset_options.items() if v == aid2][0]
                            
                            roll_corr = returns_df[aid1].rolling(window=252, min_periods=252).corr(returns_df[aid2])
                            
                            fig_corr.add_trace(go.Scatter(
                                x=roll_corr.index, 
                                y=roll_corr, 
                                mode='lines', 
                                name=f"{name1[:15]}... vs {name2[:15]}...", 
                                line=dict(width=1.5)
                            ))
                            
                        fig_corr.update_layout(
                            hovermode="x unified", 
                            height=380, 
                            margin=dict(l=0, r=0, t=30, b=0),
                            yaxis_title="Corrélation",
                            yaxis=dict(range=[-1.1, 1.1], gridcolor='#e6e9ed'),
                            xaxis=dict(gridcolor='#e6e9ed'),
                            plot_bgcolor='white',
                            paper_bgcolor='white',
                            legend=dict(orientation="h", yanchor="top", y=-0.1, xanchor="center", x=0.5)
                        )
                        st.plotly_chart(fig_corr, use_container_width=True)
                        
                        if len(pairs) > 10:
                            st.info("Le graphique est limité aux 10 premières paires pour rester lisible.")

                # --- EXPORTATION DU RAPPORT GLOBAL DE COMPARAISON ---
                st.divider()
                st.markdown("<div class='section-title'>Exporter le rapport de Comparaison</div>", unsafe_allow_html=True)
                with st.expander("Générer les fichiers Excel et PowerPoint"):
                    if st.button("Préparer l'exportation", key="btn_export_compare"):
                        with st.spinner("Génération des fichiers..."):
                            dfs_export = {"Synthèse Actifs": summary_df}
                            figs_export = {"Base 100": fig, "Volatilité": fig_vol_comp}
                            if len(valid_ids) > 1:
                                if df_comp is not None:
                                    dfs_export["Panier vs Benchmark"] = df_comp
                                if corr_matrix_named is not None:
                                    dfs_export["Matrice Corrélations"] = corr_matrix_named.reset_index().rename(columns={"index": "Actif"})
                                if fig_basket is not None:
                                    figs_export["Panier Équipondéré"] = fig_basket
                                if fig_basket_bench_corr is not None:
                                    figs_export["Corrélation Panier vs Benchmark"] = fig_basket_bench_corr
                                if fig_heatmap is not None:
                                    figs_export["Heatmap Corrélations"] = fig_heatmap
                                if fig_corr is not None:
                                    figs_export["Corrélations Croisées"] = fig_corr
                                    
                            st.session_state["compare_exports"] = {
                                "excel": create_excel_report(dfs_export, figs_export),
                                "pptx": create_pptx_report(dfs_export, figs_export, title="Comparaison Multi-Actifs")
                            }
                    if "compare_exports" in st.session_state:
                        st.download_button("Télécharger Excel", st.session_state["compare_exports"]["excel"], file_name="comparaison.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
                        st.download_button("Télécharger PowerPoint", st.session_state["compare_exports"]["pptx"], file_name="comparaison.pptx", mime="application/vnd.openxmlformats-officedocument.presentationml.presentation")
