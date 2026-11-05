import streamlit as st
import pandas as pd
import numpy as np
from sqlalchemy import create_engine, text
import os
import io
from dotenv import load_dotenv
import plotly.graph_objects as go
import datetime
from pptx import Presentation
from pptx.util import Inches
import itertools

# 1. Configuration de la page
st.set_page_config(page_title="Base de Données", layout="wide")

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
        st.error("⚠️ **Configuration manquante :** La variable `SUPABASE_DB_URL` est introuvable.")
        st.info("Veuillez vous rendre dans les paramètres de l'application Streamlit Cloud (Settings > Secrets) et renseigner `SUPABASE_DB_URL`.")
        st.stop()
        
    if db_url and db_url.startswith("postgres://"):
        db_url = db_url.replace("postgres://", "postgresql://", 1)
        
    return create_engine(db_url)

engine = init_connection()

# --- Fonctions d'exportation (Excel / PPTX) ---
def create_excel_report(dfs_dict, figs_dict):
    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine='xlsxwriter') as writer:
        workbook = writer.book
        worksheet = workbook.add_worksheet('Rapport')
        row = 0
        for title, df in dfs_dict.items():
            worksheet.write(row, 0, title)
            row += 1
            df.to_excel(writer, sheet_name='Rapport', startrow=row, index=False)
            row += len(df) + 2
            
        for title, fig in figs_dict.items():
            try:
                img_bytes = fig.to_image(format="png", width=800, height=500)
                img_buffer = io.BytesIO(img_bytes)
                worksheet.write(row, 0, title)
                row += 1
                worksheet.insert_image(row, 0, title, {'image_data': img_buffer})
                row += 26
            except Exception as e:
                worksheet.write(row, 0, f"Erreur export image {title}: {e}")
                row += 2
    buffer.seek(0)
    return buffer

def create_pptx_report(dfs_dict, figs_dict, title="Rapport"):
    prs = Presentation()
    
    title_slide = prs.slides.add_slide(prs.slide_layouts[0])
    title_slide.shapes.title.text = title
    
    for df_title, df in dfs_dict.items():
        slide = prs.slides.add_slide(prs.slide_layouts[5])
        slide.shapes.title.text = df_title
        rows, cols = df.shape
        table_shape = slide.shapes.add_table(rows + 1, cols, Inches(1), Inches(2), Inches(8), Inches(0.4 * (rows+1))).table
        for c, col_name in enumerate(df.columns):
            table_shape.cell(0, c).text = str(col_name)
        for r in range(rows):
            for c in range(cols):
                val = df.iloc[r, c]
                if pd.isna(val):
                    val = "N/A"
                elif isinstance(val, float):
                    val = f"{val:.4f}"
                table_shape.cell(r + 1, c).text = str(val)
                
    for fig_title, fig in figs_dict.items():
        slide = prs.slides.add_slide(prs.slide_layouts[5])
        slide.shapes.title.text = fig_title
        try:
            img_bytes = fig.to_image(format="png", width=800, height=500)
            img_buffer = io.BytesIO(img_bytes)
            slide.shapes.add_picture(img_buffer, Inches(1), Inches(1.5), width=Inches(8))
        except Exception as e:
            txBox = slide.shapes.add_textbox(Inches(1), Inches(2), Inches(8), Inches(1))
            txBox.text_frame.text = f"Erreur export image: {e}"
        
    buffer = io.BytesIO()
    prs.save(buffer)
    buffer.seek(0)
    return buffer

def create_nexo_presentation_pptx(asset_name, desc, left_data, nexo_data, right_df, fig, template_name="template_nexo.pptx"):
    import os, io
    from pptx import Presentation
    from pptx.util import Inches
    from pptx.dml.color import RGBColor

    def hex_to_rgb(hex_str):
        hex_str = hex_str.lstrip('#')
        if hex_str == "gray": return RGBColor(128, 128, 128)
        return RGBColor(*tuple(int(hex_str[i:i+2], 16) for i in (0, 2, 4)))

    def set_text(obj, text):
        tf = getattr(obj, 'text_frame', None)
        if tf is None: return
        if not tf.paragraphs: return
        p = tf.paragraphs[0]
        if p.runs:
            p.runs[0].text = str(text)
            for r in p.runs[1:]: r.text = ''
        else:
            p.text = str(text)

    template_path = os.path.join(os.path.dirname(__file__), template_name)
    if not os.path.exists(template_path):
        prs = Presentation()
        prs.slides.add_slide(prs.slide_layouts[6])
        buffer = io.BytesIO()
        prs.save(buffer)
        buffer.seek(0)
        return buffer

    prs = Presentation(template_path)
    slide = prs.slides[0]

    try: set_text(slide.shapes[1].shapes[0], asset_name)
    except: pass
        
    try: set_text(slide.shapes[2], desc)
    except: pass

    table_left, table_nexo, table_right, chart_shape = None, None, None, None
    for shape in slide.shapes:
        if shape.has_table:
            cols = len(shape.table.columns)
            if cols == 2: table_left = shape.table
            elif cols == 3: table_nexo = shape.table
            elif cols >= 4: table_right = shape.table
        elif shape.shape_type == 3:
            chart_shape = shape

    try:
        if table_left:
            for r in range(len(table_left.rows)):
                if r < len(left_data):
                    row_data = left_data[r]
                    for c, val in enumerate(row_data):
                        if c < len(table_left.columns):
                            set_text(table_left.cell(r, c), val)
                else:
                    for c in range(len(table_left.columns)):
                        set_text(table_left.cell(r, c), "")
    except: pass

    if nexo_data and table_nexo:
        try:
            if len(table_nexo.rows) > 1 and len(table_nexo.columns) >= 2:
                set_text(table_nexo.cell(1, 1), "Poids du Décrément")
            for c, item in enumerate(nexo_data):
                val, color_hex = item
                if c < len(table_nexo.columns):
                    cell = table_nexo.cell(2, c)
                    set_text(cell, val)
                    if cell.text_frame.paragraphs and cell.text_frame.paragraphs[0].runs:
                        cell.text_frame.paragraphs[0].runs[0].font.color.rgb = hex_to_rgb(color_hex)
        except: pass

    try:
        if table_right:
            rows, cols = right_df.shape
            for r in range(rows):
                for c in range(cols):
                    if r + 1 < len(table_right.rows) and c < len(table_right.columns):
                        val = right_df.iloc[r, c]
                        if val != "MERGE":
                            set_text(table_right.cell(r + 1, c), val)
    except: pass

    try:
        if chart_shape:
            left, top, width, height = chart_shape.left, chart_shape.top, chart_shape.width, chart_shape.height
            
            img_bytes = fig.to_image(format="png", width=600, height=350)
            img_buffer = io.BytesIO(img_bytes)
            
            sp = chart_shape._element
            sp.getparent().remove(sp)
            
            slide.shapes.add_picture(img_buffer, left, top, width, height)
    except Exception as e:
        pass

    buffer = io.BytesIO()
    prs.save(buffer)
    buffer.seek(0)
    return buffer

# 2. Récupération et mise en cache des données
@st.cache_data(ttl=3600*24)
def load_assets():
    with engine.connect() as conn:
        df = pd.read_sql("SELECT * FROM asset", conn)
        df['sector'] = df['sector'].str.strip()
        df.loc[df['sector'].str.contains('multi', case=False, na=False), 'sector'] = 'Multi-secteurs'
        df.loc[df['sector'].str.contains('diversifi', case=False, na=False), 'sector'] = 'Multi-secteurs'
        return df

@st.cache_data(ttl=3600*24)
def load_all_prices():
    with engine.connect() as conn:
        df = pd.read_sql("SELECT asset_id, date, close FROM historical_price", conn)
        df['date'] = pd.to_datetime(df['date'])
        pivot = df.pivot(index='date', columns='asset_id', values='close')
        pivot = pivot.sort_index().ffill()
        return pivot

@st.cache_data(ttl=3600*24)
def compute_screener_metrics(assets_df, prices_pivot):
    if prices_pivot.empty:
        return assets_df
    
    date_now = prices_pivot.index[-1]
    last_prices = prices_pivot.iloc[-1]
    
    # Performances (1M, YTD, 1A)
    dates_1m = prices_pivot.index[prices_pivot.index <= date_now - pd.Timedelta(days=30)]
    p_1m = prices_pivot.loc[dates_1m[-1]] if len(dates_1m) > 0 else pd.Series(np.nan, index=prices_pivot.columns)
    perf_1m = ((last_prices / p_1m) - 1) * 100

    dates_ytd = prices_pivot.index[prices_pivot.index <= pd.Timestamp(year=date_now.year - 1, month=12, day=31)]
    p_ytd = prices_pivot.loc[dates_ytd[-1]] if len(dates_ytd) > 0 else pd.Series(np.nan, index=prices_pivot.columns)
    perf_ytd = ((last_prices / p_ytd) - 1) * 100

    dates_1y = prices_pivot.index[prices_pivot.index <= date_now - pd.Timedelta(days=365)]
    p_1y = prices_pivot.loc[dates_1y[-1]] if len(dates_1y) > 0 else pd.Series(np.nan, index=prices_pivot.columns)
    perf_1y = ((last_prices / p_1y) - 1) * 100

    dates_2y = prices_pivot.index[prices_pivot.index <= date_now - pd.Timedelta(days=365*2)]
    p_2y = prices_pivot.loc[dates_2y[-1]] if len(dates_2y) > 0 else pd.Series(np.nan, index=prices_pivot.columns)
    perf_2y = pd.Series(np.nan, index=prices_pivot.columns)
    valid_mask = (p_2y > 0) & p_2y.notna() & last_prices.notna()
    perf_2y[valid_mask] = ((last_prices[valid_mask] / p_2y[valid_mask]) ** (1/2) - 1) * 100

    # Volatilités annualisées (3 Mois et 1 An)
    daily_returns = prices_pivot.pct_change(fill_method=None)
    returns_3m = daily_returns.loc[daily_returns.index >= date_now - pd.Timedelta(days=90)]
    vol_3m = returns_3m.std() * np.sqrt(252) * 100

    returns_1y = daily_returns.loc[daily_returns.index >= date_now - pd.Timedelta(days=365)]
    vol_1y = returns_1y.std() * np.sqrt(252) * 100

    # Max Drawdown 1 An
    prices_1y = prices_pivot.loc[prices_pivot.index >= date_now - pd.Timedelta(days=365)]
    cummax_1y = prices_1y.cummax()
    drawdown_1y = (prices_1y - cummax_1y) / cummax_1y
    max_dd_1y = drawdown_1y.min() * 100

    # Écartement aux Moyennes Mobiles (SMA 50 et SMA 200)
    sma50 = prices_pivot.rolling(50, min_periods=5).mean().iloc[-1]
    sma200 = prices_pivot.rolling(200, min_periods=20).mean().iloc[-1]
    dist_sma50 = ((last_prices / sma50) - 1) * 100
    dist_sma200 = ((last_prices / sma200) - 1) * 100

    metrics_df = pd.DataFrame({
        'asset_id': prices_pivot.columns,
        'last_price': last_prices.values,
        'perf_1m': perf_1m.values,
        'perf_ytd': perf_ytd.values,
        'perf_1y': perf_1y.values,
        'perf_2y': perf_2y.values,
        'vol_3m': vol_3m.values,
        'vol_1y': vol_1y.values,
        'max_dd_1y': max_dd_1y.values,
        'dist_sma50': dist_sma50.values,
        'dist_sma200': dist_sma200.values
    })

    merged = pd.merge(assets_df, metrics_df, on='asset_id', how='left')
    return merged

with st.spinner("Chargement des données en cours..."):
    assets_df = load_assets()
    prices_pivot = load_all_prices()
    
    # Ajout du display_name pour la recherche (avant le merge des métriques !)
    assets_df['display_name'] = assets_df['name'].fillna('Inconnu') + " (" + assets_df['ticker_bloomberg'].fillna('') + ")"
    
    screener_raw_df = compute_screener_metrics(assets_df, prices_pivot)

asset_options = dict(zip(assets_df['display_name'], assets_df['asset_id']))

last_date = prices_pivot.index.max()
if pd.notna(last_date):
    st.info(f"Dernière mise à jour des cours : {last_date.strftime('%d/%m/%Y')}")

# 3. Onglets principaux de navigation
tab_screener, tab_detail, tab_compare = st.tabs(["Screener Univers", "Fiche Détaillée Actif", "Comparaison de Cours"])

# ==========================================
# ONGLET 1 : SCREENER UNIVERS
# ==========================================
with tab_screener:
    st.header("Screener Univers")

    # Barre de recherche rapide
    search_query = st.text_input("Recherche rapide (Nom, Ticker Bloomberg, ISIN) :", "").strip().lower()

    # Filtres catégoriels
    types_list = sorted([str(x) for x in screener_raw_df['asset_type'].dropna().unique() if str(x).strip()])
    subtypes_list = sorted([str(x) for x in screener_raw_df['asset_subtype'].dropna().unique() if str(x).strip()])
    sectors_list = sorted([str(x) for x in screener_raw_df['sector'].dropna().unique() if str(x).strip()])
    countries_list = sorted([str(x) for x in screener_raw_df['country'].dropna().unique() if str(x).strip()])
    currencies_list = sorted([str(x) for x in screener_raw_df['currency'].dropna().unique() if str(x).strip()])

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

    # Application des filtres
    df_filtered = screener_raw_df.copy()

    if search_query:
        mask_search = (
            df_filtered['name'].astype(str).str.lower().str.contains(search_query, na=False) |
            df_filtered['ticker_bloomberg'].astype(str).str.lower().str.contains(search_query, na=False) |
            df_filtered['isin'].astype(str).str.lower().str.contains(search_query, na=False)
        )
        df_filtered = df_filtered[mask_search]

    if sel_types:
        df_filtered = df_filtered[df_filtered['asset_type'].isin(sel_types)]
    if sel_subtypes:
        df_filtered = df_filtered[df_filtered['asset_subtype'].isin(sel_subtypes)]
    if sel_sectors:
        df_filtered = df_filtered[df_filtered['sector'].isin(sel_sectors)]
    if sel_countries:
        df_filtered = df_filtered[df_filtered['country'].isin(sel_countries)]
    if sel_currencies:
        df_filtered = df_filtered[df_filtered['currency'].isin(sel_currencies)]

    if filter_only_priced:
        df_filtered = df_filtered[df_filtered['last_price'].notna() & (df_filtered['last_price'] > 0)]

    # Sélection et renommage des colonnes épurées
    columns_mapping = {
        'name': 'Nom',
        'ticker_bloomberg': 'Ticker Bloomberg',
        'isin': 'ISIN',
        'sector': 'Secteur',
        'currency': 'Devise',
        'last_price': 'Dernier Cours',
        'perf_1m': 'Perf 1M (%)',
        'perf_ytd': 'Perf YTD (%)',
        'perf_1y': 'Perf 1A (%)',
        'perf_2y': 'Perf 2A (%)',
        'vol_3m': 'Vol 3M (%)',
        'vol_1y': 'Vol 1A (%)',
        'max_dd_1y': 'Max DD 1A (%)',
        'dist_sma50': 'Écart SMA 50 (%)',
        'dist_sma200': 'Écart SMA 200 (%)'
    }

    cols_to_keep = [c for c in columns_mapping.keys() if c in df_filtered.columns]
    table_display = df_filtered[cols_to_keep].rename(columns=columns_mapping)

    # Entête d'information et export
    col_info, col_exp1, col_exp2 = st.columns([3, 1, 1])
    with col_info:
        st.write(f"**Actifs affichés :** {len(table_display)} sur {len(screener_raw_df)}")

    with col_exp1:
        csv_data = table_display.to_csv(index=False).encode('utf-8')
        st.download_button(
            label="Télécharger CSV",
            data=csv_data,
            file_name=f"screener_univers_{datetime.date.today()}.csv",
            mime="text/csv",
            use_container_width=True
        )

    with col_exp2:
        try:
            excel_buffer = io.BytesIO()
            with pd.ExcelWriter(excel_buffer, engine='openpyxl') as writer:
                table_display.to_excel(writer, index=False, sheet_name='Screener')
            st.download_button(
                label="Télécharger Excel",
                data=excel_buffer.getvalue(),
                file_name=f"screener_univers_{datetime.date.today()}.xlsx",
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
        height=600,
        selection_mode="single-row",
        on_select="rerun"
    )

    # Si l'utilisateur clique sur une ligne, on pré-charge l'actif pour l'onglet 2
    if event.selection.rows:
        selected_row_idx = event.selection.rows[0]
        selected_disp_name = df_filtered.iloc[selected_row_idx]['display_name']
        st.session_state["detail_asset_select"] = selected_disp_name


# ==========================================
# ONGLET 3 : COMPARAISON DE COURS
# ==========================================
with tab_compare:
    st.header("Comparaison de Cours (Base 100)")
    
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
                
            compare_prices = compare_prices[(compare_prices.index >= cutoff_start) & (compare_prices.index <= cutoff_end)]
            
            # Trouver la date de départ commune (max des dates de début individuelles)
            start_dates = compare_prices.apply(lambda x: x.first_valid_index())
            common_start_date = start_dates.max()
            
            if pd.isna(common_start_date):
                st.warning("Aucune période commune trouvée entre ces actifs pour la période sélectionnée.")
            else:
                if common_start_date > cutoff_start:
                    st.info(f"Point de départ commun calé au {common_start_date.strftime('%d/%m/%Y')} (première date où tous les actifs sélectionnés cotent ensemble).")

                # Filtrer depuis la date de départ commune
                compare_prices_common = compare_prices[compare_prices.index >= common_start_date]
                
                # Rebaser en base 100
                first_prices = compare_prices_common.iloc[0]
                base_100_prices = (compare_prices_common / first_prices) * 100
                
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
                    height=600,
                    margin=dict(l=0, r=0, t=30, b=0),
                    yaxis_title="Base 100",
                    legend=dict(
                        orientation="h",
                        yanchor="top",
                        y=-0.1,
                        xanchor="center",
                        x=0.5
                    )
                )
                
                st.plotly_chart(fig, use_container_width=True)
                
                # Petit tableau récapitulatif des performances
                st.markdown(f"**Performance depuis le point commun ({common_start_date.strftime('%d/%m/%Y')})**")
                perf_series = (base_100_prices.iloc[-1] - 100)
                perf_df = perf_series.reset_index()
                perf_df.columns = ['asset_id', 'Performance']
                id_to_name = {v: k for k, v in asset_options.items()}
                perf_df['Actif'] = perf_df['asset_id'].map(id_to_name)
                perf_df = perf_df[['Actif', 'Performance']].sort_values(by='Performance', ascending=False)
                
                st.dataframe(
                    perf_df.style.format({'Performance': "{:.2f} %"}),
                    use_container_width=True,
                    hide_index=True
                )
                
                st.divider()
                st.subheader("Comparaison des Volatilités (1 An Glissant)")
                fig_vol_comp = go.Figure()
                for aid in valid_ids:
                    name_disp = [k for k, v in asset_options.items() if v == aid][0]
                    # Retrait des zéros éventuels (absence de données) avant le calcul
                    clean_prices = compare_prices_common[aid].replace(0, np.nan).dropna()
                    asset_returns = clean_prices.pct_change()
                    # min_periods=252 garantit que le graph ne commence qu'après 1 an complet de données
                    roll_vol = asset_returns.rolling(window=252, min_periods=252).std() * np.sqrt(252) * 100
                    
                    fig_vol_comp.add_trace(go.Scatter(
                        x=roll_vol.index, y=roll_vol, mode='lines', name=name_disp, line=dict(width=1.5)
                    ))
                
                fig_vol_comp.update_layout(
                    hovermode="x unified", height=500, margin=dict(l=0, r=0, t=30, b=0),
                    yaxis_title="Volatilité Annualisée (%)",
                    legend=dict(orientation="h", yanchor="top", y=-0.1, xanchor="center", x=0.5)
                )
                st.plotly_chart(fig_vol_comp, use_container_width=True)

                # --- Panier équipondéré ---
                fig_basket_bench_corr = None
                df_comp = None
                if len(valid_ids) > 1:
                    st.divider()
                    st.subheader("Performance du Panier Équipondéré")
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

                    basket_prices = base_100_prices.mean(axis=1)
                    
                    fig_basket = go.Figure()
                    fig_basket.add_trace(go.Scatter(
                        x=basket_prices.index,
                        y=basket_prices,
                        mode='lines',
                        name='Panier Équipondéré',
                        line=dict(width=3, color='#FF9900')
                    ))
                    
                    bench_series_sub = None
                    if selected_bench_id is not None:
                        bench_raw = prices_pivot[selected_bench_id].dropna()
                        bench_sub = bench_raw[(bench_raw.index >= common_start_date) & (bench_raw.index <= compare_prices_common.index.max())]
                        
                        if len(bench_sub) > 0:
                            bench_base_100 = (bench_sub / bench_sub.iloc[0]) * 100
                            bench_series_sub = bench_sub
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
                    
                    basket_perf = basket_prices.iloc[-1] - 100
                    if selected_bench_id is not None and bench_series_sub is not None and len(bench_series_sub) > 0:
                        bench_perf = (bench_series_sub.iloc[-1] / bench_series_sub.iloc[0] - 1) * 100
                        spread_perf = basket_perf - bench_perf
                        
                        # Calcul du Bêta du Panier vs Benchmark sur la période
                        basket_ret = basket_prices.pct_change(fill_method=None).dropna()
                        bench_ret = bench_series_sub.pct_change(fill_method=None).dropna()
                        comb_ret = pd.DataFrame({'Panier': basket_ret, 'Benchmark': bench_ret}).dropna()
                        
                        if len(comb_ret) >= 5 and comb_ret['Benchmark'].var() > 0:
                            basket_beta = comb_ret['Panier'].cov(comb_ret['Benchmark']) / comb_ret['Benchmark'].var()
                            beta_disp = f"{basket_beta:.2f}"
                        else:
                            beta_disp = "N/A"
                        # Volatilité Historique Annualisée
                        basket_vol = basket_ret.std(ddof=1) * np.sqrt(252) * 100 if len(basket_ret) > 1 else np.nan
                        bench_vol = bench_ret.std(ddof=1) * np.sqrt(252) * 100 if len(bench_ret) > 1 else np.nan
                        spread_vol = basket_vol - bench_vol if pd.notna(basket_vol) and pd.notna(bench_vol) else np.nan
                        
                        # Max Drawdown
                        cummax_basket = basket_prices.cummax()
                        dd_basket = (basket_prices - cummax_basket) / cummax_basket
                        basket_mdd = dd_basket.min() * 100
                        
                        cummax_bench = bench_series_sub.cummax()
                        dd_bench = (bench_series_sub - cummax_bench) / cummax_bench
                        bench_mdd = dd_bench.min() * 100
                        spread_mdd = basket_mdd - bench_mdd

                        # Bêta affiché en dehors du tableau
                        col_beta_box, _ = st.columns([1, 2])
                        with col_beta_box:
                            st.metric("Bêta du Panier (vs Benchmark)", beta_disp)

                        # Tableau comparatif
                        bench_col_title = f"Benchmark ({selected_bench_name})"
                        comp_data = {
                            "Métrique": [
                                "Performance Globale",
                                "Volatilité Historique (ann.)",
                                "Max Drawdown"
                            ],
                            "Panier Équipondéré": [
                                f"{basket_perf:+.2f} %",
                                f"{basket_vol:.2f} %" if pd.notna(basket_vol) else "N/A",
                                f"{basket_mdd:.2f} %" if pd.notna(basket_mdd) else "N/A"
                            ],
                            bench_col_title: [
                                f"{bench_perf:+.2f} %",
                                f"{bench_vol:.2f} %" if pd.notna(bench_vol) else "N/A",
                                f"{bench_mdd:.2f} %" if pd.notna(bench_mdd) else "N/A"
                            ],
                            "Écart": [
                                f"{spread_perf:+.2f} %",
                                f"{spread_vol:+.2f} %" if pd.notna(spread_vol) else "N/A",
                                f"{spread_mdd:+.2f} %" if pd.notna(spread_mdd) else "N/A"
                            ]
                        }
                        df_comp = pd.DataFrame(comp_data)
                        st.dataframe(df_comp, hide_index=True, use_container_width=True)
                    else:
                        st.metric(label="Performance globale du Panier", value=f"{basket_perf:+.2f} %")

                    # --- Corrélation Rolling 1 An : Panier vs Benchmark ---
                    if selected_bench_id is not None and bench_series_sub is not None and len(bench_series_sub) > 0:
                        st.subheader("Corrélation Rolling 1 An : Panier vs Benchmark")
                        st.markdown(f"Évolution de la corrélation glissante des rendements quotidiens sur 1 an (252 jours) entre le Panier Équipondéré et **{selected_bench_name}**.")
                        
                        basket_ret = basket_prices.pct_change(fill_method=None).dropna()
                        bench_ret = bench_series_sub.pct_change(fill_method=None).dropna()
                        comb_ret = pd.DataFrame({'Panier': basket_ret, 'Benchmark': bench_ret}).dropna()
                        
                        if len(comb_ret) >= 30:
                            min_periods_corr = 252 if len(comb_ret) >= 252 else max(20, len(comb_ret) // 2)
                            roll_corr_bb = comb_ret['Panier'].rolling(window=252, min_periods=min_periods_corr).corr(comb_ret['Benchmark'])
                            
                            fig_basket_bench_corr = go.Figure()
                            # Ligne horizontale de référence à 0
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
                                height=380,
                                margin=dict(l=0, r=0, t=30, b=0),
                                yaxis_title="Corrélation",
                                yaxis=dict(range=[-1.05, 1.05]),
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

                    # --- Corrélation Glissante Croisée ---
                    st.divider()
                    st.subheader("Corrélation Croisée (1 An Glissant)")
                    st.markdown("Évolution de la corrélation des rendements quotidiens entre les actifs sur une fenêtre glissante de 1 an (252 jours).")
                    
                    returns_df = compare_prices_common.pct_change(fill_method=None).dropna()
                    
                    fig_corr = go.Figure()
                    pairs = list(itertools.combinations(valid_ids, 2))
                    
                    # On limite à 10 paires pour éviter un graphique illisible si on sélectionne trop d'actifs
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
                        height=400, 
                        margin=dict(l=0, r=0, t=30, b=0),
                        yaxis_title="Corrélation",
                        yaxis=dict(range=[-1.1, 1.1]),
                        legend=dict(orientation="h", yanchor="top", y=-0.1, xanchor="center", x=0.5)
                    )
                    
                    st.plotly_chart(fig_corr, use_container_width=True)
                    
                    if len(pairs) > 10:
                        st.info("Le graphique est limité aux 10 premières paires pour rester lisible.")

                st.divider()
                st.subheader("Exporter le rapport de Comparaison")
                with st.expander("Générer les fichiers Excel et PowerPoint"):
                    if st.button("Préparer l'exportation", key="btn_export_compare"):
                        with st.spinner("Génération des fichiers..."):
                            dfs_export = {"Performance": perf_df}
                            figs_export = {"Base 100": fig, "Volatilité": fig_vol_comp}
                            if len(valid_ids) > 1:
                                if df_comp is not None:
                                    dfs_export["Panier vs Benchmark"] = df_comp
                                figs_export["Panier Équipondéré"] = fig_basket
                                if fig_basket_bench_corr is not None:
                                    figs_export["Corrélation Panier vs Benchmark"] = fig_basket_bench_corr
                                figs_export["Corrélations Croisées"] = fig_corr
                                
                            st.session_state["compare_exports"] = {
                                "excel": create_excel_report(dfs_export, figs_export),
                                "pptx": create_pptx_report(dfs_export, figs_export, title="Comparaison de Cours")
                            }
                    if "compare_exports" in st.session_state:
                        st.download_button("Télécharger Excel", st.session_state["compare_exports"]["excel"], file_name="comparaison.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
                        st.download_button("Télécharger PowerPoint", st.session_state["compare_exports"]["pptx"], file_name="comparaison.pptx", mime="application/vnd.openxmlformats-officedocument.presentationml.presentation")

# ==========================================
# ONGLET 2 : FICHE DETAILLEE ACTIF
# ==========================================
with tab_detail:
    st.header("Vue Détaillée Actif")

    selected_asset_name = st.selectbox(
        "Recherchez un actif par nom ou ticker :",
        options=sorted(asset_options.keys()),
        key="detail_asset_select"
    )

    if not selected_asset_name:
        st.stop()

    selected_asset_id = asset_options[selected_asset_name]
    asset_info = assets_df[assets_df['asset_id'] == selected_asset_id].iloc[0]

    st.divider()

    # --- 1. Fiche d'Identité ---
    st.subheader("Fiche d'Identité")

    is_index = asset_info.get('asset_type') == 'Indice' or pd.notna(asset_info.get('issuer'))

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
            st.metric("Dividende distribué en 2025 avec effet de réinvestissement", div_str)
            
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

    # --- Préparation des séries de prix pour l'actif ---
    if selected_asset_id not in prices_pivot.columns:
        st.warning("Aucun historique de prix disponible pour cet actif (base de données vide pour ce ticker).")
        st.stop()

    asset_prices = prices_pivot[selected_asset_id].dropna()
    asset_prices = asset_prices[asset_prices > 0]
    if len(asset_prices) == 0:
        st.warning("Aucun historique de prix valide (non nul) disponible pour cet actif.")
        st.stop()

    daily_returns = asset_prices.pct_change(fill_method=None).dropna()
    current_date = asset_prices.index.max()
    current_price = asset_prices.iloc[-1]
    start_of_year = pd.Timestamp(year=current_date.year, month=1, day=1)

    def get_price_at(date_target):
        available_dates = asset_prices[asset_prices.index <= date_target]
        if len(available_dates) == 0:
            return np.nan
        return available_dates.iloc[-1]

    def get_perf(days=None, ytd=False):
        if ytd:
            end_of_prev_year = pd.Timestamp(year=current_date.year - 1, month=12, day=31)
            old_price = get_price_at(end_of_prev_year)
        else:
            old_price = get_price_at(current_date - pd.Timedelta(days=days))
        
        if pd.isna(old_price): return np.nan
        return ((current_price / old_price) - 1) * 100

    def get_vol(days=None, ytd=False):
        if ytd:
            end_of_prev_year = pd.Timestamp(year=current_date.year - 1, month=12, day=31)
            sub_returns = daily_returns[daily_returns.index > end_of_prev_year]
        else:
            sub_returns = daily_returns[daily_returns.index >= current_date - pd.Timedelta(days=days)]
        
        if len(sub_returns) < 2: return np.nan
        return sub_returns.std() * np.sqrt(252) * 100

    # --- Résolution du Benchmark (pour le Bêta et le Graphique) ---
    benchmark_mapping = {
        'FRANCE': 'CAC Index',
        'GERMANY': 'DAX Index', 'ALLEMAGNE': 'DAX Index',
        'US': 'SPX Index', 'USA': 'SPX Index', 'UNITED STATES': 'SPX Index', 'AMÉRIQUE DU NORD': 'SPX Index',
        'ÉTATS-UNIS': 'SPX Index', 'ÉTATS UNIS': 'SPX Index', 'ETATS-UNIS': 'SPX Index', 'ETATS UNIS': 'SPX Index',
        'BRITAIN': 'UKX Index', 'ROYAUME-UNI': 'UKX Index',
        'SWITZERLAND': 'SMI Index', 'SUISSE': 'SMI Index',
        'JAPAN': 'NKY Index', 'JAPON': 'NKY Index',
        'CHINE': 'SHSZ300 INDEX', 'CHINA': 'SHSZ300 INDEX',
        'HONG KONG': 'HSI Index', 'MACAU': 'HSI Index',
        'EUROPE': 'SX5E Index', 'EURO ZONE': 'SX5E Index', 'ZONE EURO': 'SX5E Index',
        'ITALY': 'SX5E Index', 'ITALIE': 'SX5E Index',
        'SPAIN': 'SX5E Index', 'ESPAGNE': 'SX5E Index',
        'PORTUGAL': 'SX5E Index', 'MALTA': 'SX5E Index',
        'BELGIQUE': 'SX5E Index', 'BELGIUM': 'SX5E Index',
        'NETHERLANDS': 'SX5E Index', 'PAYS-BAS': 'SX5E Index',
        'LUXEMBOURG': 'SX5E Index',
        'SWEDEN': 'SX5E Index', 'SUÈDE': 'SX5E Index', 'SUEDE': 'SX5E Index',
        'DENMARK': 'SX5E Index', 'DANEMARK': 'SX5E Index',
        'NORWAY': 'SX5E Index', 'NORVÈGE': 'SX5E Index', 'NORVEGE': 'SX5E Index',
        'FINLAND': 'SX5E Index', 'FINLANDE': 'SX5E Index',
        'FAROE ISLANDS': 'SX5E Index', 'ÎLES FÉROÉ': 'SX5E Index', 'ILES FEROE': 'SX5E Index',
        'AUSTRIA': 'SX5E Index', 'AUTRICHE': 'SX5E Index',
        'CZECH': 'SX5E Index', 'RÉPUBLIQUE TCHÈQUE': 'SX5E Index', 'REPUBLIQUE TCHEQUE': 'SX5E Index',
        'POLAND': 'SX5E Index', 'POLOGNE': 'SX5E Index',
        'HUNGARY': 'SX5E Index', 'HONGRIE': 'SX5E Index',
        'IRELAND': 'SX5E Index', 'IRLANDE': 'SX5E Index',
        'MONDE': 'MSCI WORLD Index', 
        'WORLD': 'MSCI WORLD Index', 
        'MONDE - MARCHÉS ÉMERGENTS': 'MSCI WORLD Index',
        'BERMUDA': 'MSCI WORLD Index', 
        'TRANSATLANTIC': 'MSCI WORLD Index', 
        'TRANSATLANTIQUE': 'MSCI WORLD Index',
        'EUROPE - US - JAPON': 'MSCI WORLD Index', 'EUROPE - ÉTATS-UNIS - JAPON': 'MSCI WORLD Index', 'EUROPE - ETATS-UNIS - JAPON': 'MSCI WORLD Index',
        'ASIE - US': 'MSCI WORLD Index', 'ASIE - ÉTATS-UNIS': 'MSCI WORLD Index', 'ASIE - ETATS-UNIS': 'MSCI WORLD Index',
        'EURASIE': 'MSCI WORLD Index',
        'EURO-ASIE': 'MSCI WORLD Index',
        'EUROPE - ASIE': 'MSCI WORLD Index',
        'CHINE - EUROPE': 'MSCI WORLD Index',
        'ASIE': 'MSCI AC ASIA PACIFIC Index', 
        'AUSTRALIA': 'MSCI AC ASIA PACIFIC Index',
        'MARCHÉS ÉMERGENTS': 'MSCI EM Index', 'MARCHES EMERGENTS': 'MSCI EM Index',
        'BRAZIL': 'MSCI EM Index', 'BRÉSIL': 'MSCI EM Index', 'BRESIL': 'MSCI EM Index',
        'CHILE': 'MSCI EM Index', 'CHILI': 'MSCI EM Index',
        'JORDAN': 'MSCI EM Index', 
        'KAZAKHSTAN': 'MSCI EM Index', 
        'RUSSIA': 'MSCI EM Index', 'RUSSIE': 'MSCI EM Index'
    }

    asset_country = str(asset_info.get('country', '')).strip().upper()
    benchmark_ticker = benchmark_mapping.get(asset_country)
    benchmark_asset_id = None

    if benchmark_ticker:
        bench_match = assets_df[assets_df['ticker_bloomberg'] == benchmark_ticker]
        if not bench_match.empty:
            benchmark_asset_id = bench_match.iloc[0]['asset_id']

    def get_beta(days=365):
        if not benchmark_asset_id or benchmark_asset_id not in prices_pivot.columns:
            return np.nan
        bench_prices = prices_pivot[benchmark_asset_id].dropna()
        bench_prices = bench_prices[bench_prices > 0]
        if len(bench_prices) == 0: return np.nan
        bench_returns = bench_prices.pct_change(fill_method=None).dropna()
        
        # Aligner les dates
        cutoff_date = current_date - pd.Timedelta(days=days)
        sub_asset = daily_returns[daily_returns.index >= cutoff_date]
        sub_bench = bench_returns[bench_returns.index >= cutoff_date]
        
        common_dates = sub_asset.index.intersection(sub_bench.index)
        if len(common_dates) < 20: # Il faut un minimum de jours
            return np.nan
            
        aligned_asset = sub_asset.loc[common_dates]
        aligned_bench = sub_bench.loc[common_dates]
        
        cov = aligned_asset.cov(aligned_bench)
        var = aligned_bench.var()
        if var == 0: return np.nan
        return cov / var

    # --- Scoring Décrément ---
    def extract_decrement(name):
        import re
        m_pct = re.search(r'(\d+(?:[.,]\d+)?)\s*%', name)
        if m_pct: return float(m_pct.group(1).replace(',', '.')), 'PERCENT'
        m_dnp = re.search(r'(?i)d\s*(\d+(?:[.,]\d+)?)\s*p', name)
        if m_dnp: return float(m_dnp.group(1).replace(',', '.')), 'POINTS'
        m_dec = re.search(r'(?i)(?:decrement|decr\.?)\s*(\d+(?:[.,]\d+)?)', name)
        if m_dec: return float(m_dec.group(1).replace(',', '.')), 'POINTS'
        m_num = re.search(r'(?i)(\d+(?:[.,]\d+)?)\s*(?:points?|pts?|pt|point\(s\))?\s*decr', name)
        if m_num: return float(m_num.group(1).replace(',', '.')), 'POINTS'
        return None, None

    asset_name_str = str(asset_info.get('name', ''))
    asset_type_str = str(asset_info.get('asset_type', '')).strip().lower()
    asset_subtype_str = str(asset_info.get('asset_subtype', '')).strip().lower()
    
    # Ne calculer le décrément et le score Nexo QUE pour les indices ou s'il s'agit explicitement d'un sous-type "décrément"
    is_indice_or_decrement = (
        'indice' in asset_type_str or 
        'indice' in asset_subtype_str or 
        'décrément' in asset_subtype_str or 
        'decrement' in asset_subtype_str
    )
    
    if is_indice_or_decrement:
        dec_val, dec_type = extract_decrement(asset_name_str)
    else:
        dec_val, dec_type = None, None
    


    # --- 2. Tableaux Perf / Vol / Bêta ---
    st.subheader(f"Performances et Risques (Dernier cours : {current_price:.2f})")

    perf_data = {
        "5 Jours": get_perf(days=5),
        "1 Mois": get_perf(days=30),
        "3 Mois": get_perf(days=90),
        "YTD": get_perf(ytd=True),
    }

    vol_data = {
        "1 Mois": get_vol(days=30),
        "3 Mois": get_vol(days=90),
        "YTD": get_vol(ytd=True),
        "1 An": get_vol(days=365),
    }
    
    beta_data = {
        "1 An": get_beta(days=365),
        "3 Ans": get_beta(days=365*3),
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
        # Streamlit style for handling NaN gracefully
        st.dataframe(beta_df.style.format({"Coefficient": "{:.2f}"}, na_rep="N/A"), use_container_width=True, hide_index=True)

    st.divider()

    # --- 3. Graphique Technique ---
    st.subheader("Cours")

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
        
        sma50 = asset_norm.rolling(window=50, min_periods=1).mean()
        sma200 = asset_norm.rolling(window=200, min_periods=1).mean()
        
        fig.add_trace(go.Scatter(x=asset_norm.index, y=asset_norm, mode='lines', name='Prix', line=dict(width=2)))
        fig.add_trace(go.Scatter(x=sma50.index, y=sma50, mode='lines', name='SMA 50', line=dict(color='#00d2ff', width=1.5)))
        fig.add_trace(go.Scatter(x=sma200.index, y=sma200, mode='lines', name='SMA 200', line=dict(color='#ff512f', width=1.5)))
    else:
        sma50 = asset_prices.rolling(window=50, min_periods=1).mean()
        sma200 = asset_prices.rolling(window=200, min_periods=1).mean()
        
        fig.add_trace(go.Scatter(x=asset_prices.index, y=asset_prices, mode='lines', name='Prix', line=dict(width=2)))
        fig.add_trace(go.Scatter(x=sma50.index, y=sma50, mode='lines', name='SMA 50', line=dict(color='#00d2ff', width=1.5)))
        fig.add_trace(go.Scatter(x=sma200.index, y=sma200, mode='lines', name='SMA 200', line=dict(color='#ff512f', width=1.5)))

    fig.update_layout(hovermode="x unified", height=500, margin=dict(l=0, r=0, t=30, b=0))
    st.plotly_chart(fig, use_container_width=True)

    st.divider()

    # --- 3.5 Volatilité Annuelle Glissante ---
    st.subheader("Volatilité Annualisée (1 An Glissant)")
    clean_asset_prices = asset_prices.replace(0, np.nan).dropna()
    asset_returns = clean_asset_prices.pct_change()
    roll_vol = asset_returns.rolling(window=252, min_periods=252).std() * np.sqrt(252) * 100
    
    fig_vol = go.Figure()
    fig_vol.add_trace(go.Scatter(
        x=roll_vol.index, y=roll_vol, mode='lines', name='Volatilité', 
        line=dict(color='#ff9900', width=2)
    ))
    fig_vol.update_layout(
        hovermode="x unified", height=400, margin=dict(l=0, r=0, t=30, b=0), 
        yaxis_title="Volatilité (%)"
    )
    st.plotly_chart(fig_vol, use_container_width=True)

    st.divider()

    # --- 4. Analyse des Corrélations (1 an glissant) ---
    st.subheader("Corrélations sur 1 An Glissant")

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

    st.divider()
    
    st.markdown(f"<h2 style='text-align: left; color: #003366; border-bottom: 2px solid #003366; padding-bottom: 10px;'>PRÉSENTATION DE L'ACTIF</h2>", unsafe_allow_html=True)
    
    col_bench, _ = st.columns([1, 2])
    with col_bench:
        benchmark_name = st.selectbox("Sélectionnez un benchmark pour le graphique :", options=["Aucun"] + sorted(asset_options.keys()), index=0, key="pres_benchmark")
        
    benchmark_prices = None
    bench_ticker_disp = str(benchmark_name)[:15] if benchmark_name != "Aucun" else ""
    if benchmark_name != "Aucun":
        bench_id = asset_options[benchmark_name]
        if bench_id in prices_pivot.columns:
            benchmark_prices = prices_pivot[bench_id].dropna()
            bench_info = assets_df[assets_df['asset_id'] == bench_id].iloc[0]
            bt = str(bench_info.get('ticker_bloomberg', benchmark_name))
            if pd.notna(bt) and bt.strip() != 'nan':
                bench_ticker_disp = bt

    st.markdown(f"<h4 style='color: #003366; margin-bottom: 30px;'>{asset_name_str}</h4>", unsafe_allow_html=True)
    
    # Fonctions pour la présentation
    def get_perf_ann(days):
        if len(asset_prices) == 0: return np.nan
        start_date = current_date - pd.Timedelta(days=days)
        sub = asset_prices[asset_prices.index >= start_date]
        if len(sub) == 0: return np.nan
        old_price = sub.iloc[0]
        years = days / 365.25
        if old_price <= 0: return np.nan
        return ((current_price / old_price) ** (1 / years) - 1) * 100

    def get_max_drawdown(days):
        start_date = current_date - pd.Timedelta(days=days)
        sub = asset_prices[asset_prices.index >= start_date]
        if len(sub) == 0: return np.nan
        roll_max = sub.cummax()
        drawdown = sub / roll_max - 1.0
        return drawdown.min() * 100

    def get_sharpe(days):
        perf = get_perf_ann(days) if days > 365 else get_perf(days=days)
        vol = get_vol(days)
        if pd.isna(perf) or pd.isna(vol) or vol == 0: return np.nan
        return perf / vol
        
    def color_score(score):
        if score == "N/A": return "gray"
        if score <= 1: return "#28a745"
        if score <= 2: return "#85c13f"
        if score <= 3: return "#ffc107"
        if score <= 4: return "#fd7e14"
        return "#dc3545"

    # Notes NEXO (Formules calibrées - Documentation Méthodologique)
    import math
    note_yield = "N/A"
    note_vol = "N/A"
    note_ecart = "N/A"
    dec_yield_pct = "N/A"
    div_2025 = asset_info.get('dividend_yield')

    # 1. Note Volatilité (basée sur la vol annualisée 1 an)
    vol_1y = get_vol(days=365)
    if pd.notna(vol_1y):
        try:
            x_vol = float(vol_1y)
            if x_vol <= 15.0:
                note_vol = 0.0
            elif x_vol >= 40.0:
                note_vol = 5.0
            else:
                val = 8.68 - 14.53 * math.exp(-0.0343 * x_vol)
                note_vol = max(0.0, min(5.0, val))
        except Exception:
            pass

    # 2. Note Yield & Note Écart (si décrément)
    if dec_val is not None and pd.notna(current_price) and current_price > 0:
        if dec_type == 'PERCENT':
            dec_yield = float(dec_val) / 100.0
            dec_yield_pct = float(dec_val)
        else:
            dec_yield = float(dec_val) / float(current_price)
            dec_yield_pct = dec_yield * 100.0

        # Note Yield : fittée sur le poids du décrément en %
        try:
            x_yield = float(dec_yield_pct)
            if x_yield <= 4.0:
                note_yield = 0.0
            elif x_yield >= 6.90:
                note_yield = 5.0
            else:
                val = -0.69 + 0.0370 * math.exp(0.73 * x_yield)
                note_yield = max(0.0, min(5.0, val))
        except Exception:
            pass

        # Note Écart : fittée sur l'écart de dividende en %
        if pd.notna(div_2025):
            try:
                x_ecart = (float(div_2025) - dec_yield) * 100.0
                if x_ecart >= 1.0:
                    note_ecart = 0.0
                elif x_ecart <= -4.5:
                    note_ecart = 5.0
                else:
                    val = -1.57 + 2.04 * math.exp(-0.26 * x_ecart)
                    note_ecart = max(0.0, min(5.0, val))
            except Exception:
                pass

    pres_col1, pres_col2 = st.columns([1, 1], gap="large")
    
    with pres_col1:
        desc = str(asset_info.get('construction', '')) + " " + str(asset_info.get('specificities', ''))
        desc = desc.strip()
        if not desc or desc == "N/A N/A" or desc == "nan nan":
            desc = "Description de l'actif non disponible."
        st.markdown(f"<p style='font-size: 13px; text-align: justify; margin-bottom: 25px;'>{desc}</p>", unsafe_allow_html=True)
        
        div_val_pct = f"{float(div_2025)*100:.2f}%".replace('.', ',') if pd.notna(div_2025) else "N/A"
        date_str = current_date.strftime('%d/%m/%Y')
        curr_price_str = f"{current_price:.2f}".replace('.', ',') + " pts"
        
        if dec_val is not None:
            dec_val_pct = f"{dec_yield_pct:.2f}%".replace('.', ',') if dec_yield_pct != "N/A" else "N/A"
            table_rows = (
                f"<tr><td style='background-color:#003366; color:white; padding:10px; font-weight:bold; border: 1px solid white;'>Niveau de l'indice au {date_str}</td>"
                f"<td style='background-color:#e6e9ed; color:black; padding:10px; text-align:center; font-weight:bold; border: 1px solid white;'>{curr_price_str}</td></tr>\n"
                f"<tr><td style='background-color:#003366; color:white; padding:10px; font-weight:bold; border: 1px solid white;'>Taux de décrément au {date_str}</td>"
                f"<td style='background-color:#f4f5f7; color:black; padding:10px; text-align:center; font-weight:bold; border: 1px solid white;'>{dec_val_pct}</td></tr>\n"
                f"<tr><td style='background-color:#003366; color:white; padding:10px; font-weight:bold; border: 1px solid white;'>Taux de dividende 2025 avec effet de réinvestissement</td>"
                f"<td style='background-color:#e6e9ed; color:black; padding:10px; text-align:center; font-weight:bold; border: 1px solid white;'>{div_val_pct}</td></tr>"
            )
        else:
            table_rows = (
                f"<tr><td style='background-color:#003366; color:white; padding:10px; font-weight:bold; border: 1px solid white;'>Niveau de l'indice au {date_str}</td>"
                f"<td style='background-color:#e6e9ed; color:black; padding:10px; text-align:center; font-weight:bold; border: 1px solid white;'>{curr_price_str}</td></tr>\n"
                f"<tr><td style='background-color:#003366; color:white; padding:10px; font-weight:bold; border: 1px solid white;'>Taux de dividende 2025</td>"
                f"<td style='background-color:#f4f5f7; color:black; padding:10px; text-align:center; font-weight:bold; border: 1px solid white;'>{div_val_pct}</td></tr>"
            )
            
        st.markdown(f"""
<table style="width:100%; font-family:sans-serif; font-size:13px; margin-bottom: 30px; border-collapse: collapse; border: none;">
{table_rows}
</table>
        """, unsafe_allow_html=True)
        
        st.markdown("""
<table style="width:100%; font-family:sans-serif; font-size:13px; text-align:center; border-collapse: collapse; border: none;">
    <tr><th colspan="3" style="background-color:#003366; color:white; padding:8px; border: 1px solid white;">Score NEXO™</th></tr>
    <tr>
        <td style="background-color:#1c4b78; color:white; padding:6px; border: 1px solid white; width: 33%;">Volatilité</td>
        <td style="background-color:#1c4b78; color:white; padding:6px; border: 1px solid white; width: 33%;">Poids du Décrément</td>
        <td style="background-color:#1c4b78; color:white; padding:6px; border: 1px solid white; width: 33%;">Ecart</td>
    </tr>
    <tr>
        <td style="padding:12px; font-weight:bold; color:{color_vol}; background-color:white; font-size:16px; border: 1px solid #e6e9ed;">{vol_text}</td>
        <td style="padding:12px; font-weight:bold; color:{color_yield}; background-color:white; font-size:16px; border: 1px solid #e6e9ed;">{yield_text}</td>
        <td style="padding:12px; font-weight:bold; color:{color_ecart}; background-color:white; font-size:16px; border: 1px solid #e6e9ed;">{ecart_text}</td>
    </tr>
</table>
        """.format(
            color_vol=color_score(note_vol), vol_text=f"{note_vol:.2f}/5" if note_vol!="N/A" else "N/A",
            color_yield=color_score(note_yield), yield_text=f"{note_yield:.2f}/5" if note_yield!="N/A" else "N/A",
            color_ecart=color_score(note_ecart), ecart_text=f"{note_ecart:.2f}/5" if note_ecart!="N/A" else "N/A"
        ), unsafe_allow_html=True)
        
        st.markdown("""
        <div style="font-size:11px; margin-top:15px; color: #555;">
        <b style='text-decoration: underline;'>Légende :</b><br>
        <span style="color:#28a745; font-weight:bold;">0-1 : Risque très faible</span> &nbsp;&nbsp;&nbsp; 
        <span style="color:#85c13f; font-weight:bold;">1-2 : Risque faible</span> &nbsp;&nbsp;&nbsp; 
        <span style="color:#ffc107; font-weight:bold;">2-3 : Risque modéré</span><br>
        <span style="color:#fd7e14; font-weight:bold;">3-4 : Risque élevé</span> &nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;
        <span style="color:#dc3545; font-weight:bold;">4-5 : Risque très élevé</span>
        </div>
        """, unsafe_allow_html=True)
        
    with pres_col2:
        is_base_100 = (benchmark_prices is not None)
        title_text = "Evolution historique de la performance (Base 100)" if is_base_100 else "Evolution historique du cours"
        
        st.markdown(f"<div style='text-align: center; font-weight: bold; font-size: 14px; margin-bottom: 10px;'>{title_text}</div>", unsafe_allow_html=True)
        fig_pres = go.Figure()
        
        ticker_disp = str(asset_info.get('ticker_bloomberg', 'Actif'))
        if pd.isna(ticker_disp) or ticker_disp.strip() == 'nan': ticker_disp = 'Actif'
        
        main_color = '#4f81bd'
        
        if is_base_100:
            common_idx = asset_prices.index.intersection(benchmark_prices.index)
            if len(common_idx) > 0:
                asset_sub = asset_prices.loc[common_idx]
                bench_sub = benchmark_prices.loc[common_idx]
                asset_b100 = (asset_sub / asset_sub.iloc[0]) * 100
                bench_b100 = (bench_sub / bench_sub.iloc[0]) * 100
                
                fig_pres.add_trace(go.Scatter(x=asset_b100.index, y=asset_b100, mode='lines', name=ticker_disp, line=dict(color=main_color, width=2.5)))
                fig_pres.add_trace(go.Scatter(x=bench_b100.index, y=bench_b100, mode='lines', name=bench_ticker_disp, line=dict(color='#95b3d7', width=2.0)))
            else:
                asset_b100 = (asset_prices / asset_prices.iloc[0]) * 100
                fig_pres.add_trace(go.Scatter(x=asset_b100.index, y=asset_b100, mode='lines', name=ticker_disp, line=dict(color=main_color, width=2.5)))
        else:
            fig_pres.add_trace(go.Scatter(x=asset_prices.index, y=asset_prices, mode='lines', name=ticker_disp, line=dict(color=main_color, width=2.5)))
            
        fig_pres.update_layout(
            title=dict(text=title_text, font=dict(size=14, color='black', family='Arial', weight='bold'), x=0.5),
            margin=dict(l=40, r=10, t=40, b=80), 
            height=280, 
            plot_bgcolor='white', 
            xaxis=dict(showgrid=False, dtick="M12", tickformat="%b-%y", tickangle=-45, tickfont=dict(color='#595959')), 
            yaxis=dict(showgrid=True, gridcolor='#d9d9d9', zeroline=False, dtick=50 if is_base_100 else None, tickformat=".2f", tickfont=dict(color='#595959')),
            legend=dict(orientation="h", yanchor="top", y=-0.35, xanchor="center", x=0.5, font=dict(size=10))
        )
        st.plotly_chart(fig_pres, use_container_width=True, config={'displayModeBar': False})
        
        perfs = [get_perf_ann(365*10), get_perf_ann(365*5), get_perf(365)]
        vols = [get_vol(365*10), get_vol(365*5), get_vol(365)]
        sharpes = [get_sharpe(365*10), get_sharpe(365*5), get_sharpe(365)]
        drawdowns = [get_max_drawdown(365*10), get_max_drawdown(365*5), get_max_drawdown(365)]
        
        def fmt(v, pct=False):
            if pd.isna(v): return "N/A"
            if pct: return f"{v:.2f}%"
            return f"{v:.2f}"
        
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
        <th colspan="2" style="background-color:#003366; color:white; padding:6px; border: 1px solid white; width: 28%;">10 ans</th>
        <th colspan="2" style="background-color:#003366; color:white; padding:6px; border: 1px solid white; width: 28%;">5 ans</th>
        <th colspan="2" style="background-color:#003366; color:white; padding:6px; border: 1px solid white; width: 28%;">1 an</th>
    </tr>
    <tr>
        <td style="border:none; background-color: white;"></td>
        <td style="background-color:#1c4b78; color:white; padding:6px; border: 1px solid white; width: 14%;">{ticker_disp}</td>
        <td style="background-color:#1c4b78; color:white; padding:6px; border: 1px solid white; width: 14%;">{bench_ticker_disp}</td>
        <td style="background-color:#1c4b78; color:white; padding:6px; border: 1px solid white; width: 14%;">{ticker_disp}</td>
        <td style="background-color:#1c4b78; color:white; padding:6px; border: 1px solid white; width: 14%;">{bench_ticker_disp}</td>
        <td style="background-color:#1c4b78; color:white; padding:6px; border: 1px solid white; width: 14%;">{ticker_disp}</td>
        <td style="background-color:#1c4b78; color:white; padding:6px; border: 1px solid white; width: 14%;">{bench_ticker_disp}</td>
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
        <th style="background-color:#003366; color:white; padding:6px; border: 1px solid white; width: 25%;">10 ans</th>
        <th style="background-color:#003366; color:white; padding:6px; border: 1px solid white; width: 25%;">5 ans</th>
        <th style="background-color:#003366; color:white; padding:6px; border: 1px solid white; width: 25%;">1 an</th>
    </tr>
    <tr>
        <td style="border:none; background-color: white;"></td>
        <td style="background-color:#1c4b78; color:white; padding:6px; border: 1px solid white;">{ticker_disp}</td>
        <td style="background-color:#1c4b78; color:white; padding:6px; border: 1px solid white;">{ticker_disp}</td>
        <td style="background-color:#1c4b78; color:white; padding:6px; border: 1px solid white;">{ticker_disp}</td>
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
            (f"{note_vol:.2f}/5" if note_vol!="N/A" else "N/A", color_score(note_vol)),
            (f"{note_yield:.2f}/5" if note_yield!="N/A" else "N/A", color_score(note_yield)),
            (f"{note_ecart:.2f}/5" if note_ecart!="N/A" else "N/A", color_score(note_ecart))
        ]
        if benchmark_prices is not None:
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
    st.subheader("Exporter le rapport Détaillé")
    with st.expander("Générer les fichiers Excel et PowerPoint"):
        if st.button(f"Préparer l'exportation pour {selected_asset_name}", key="btn_export_detail"):
            with st.spinner("Génération des fichiers..."):
                dfs_export = {
                    "Performances": perf_df,
                    "Volatilité": vol_df,
                    "Bêta": beta_df
                }
                if 'top_10' in locals() and top_10 is not None:
                    dfs_export["Top Corrélations"] = top_10
                    dfs_export["Flop Corrélations"] = bottom_10
                    
                figs_export = {
                    "Cours": fig,
                    "Volatilité Glissante": fig_vol
                }
                
                st.session_state["detail_exports"] = {
                    "excel": create_excel_report(dfs_export, figs_export),
                    "pptx": create_pptx_report(dfs_export, figs_export, title=f"Fiche Détaillée: {selected_asset_name}")
                }
        if "detail_exports" in st.session_state:
            st.download_button("Télécharger Excel", st.session_state["detail_exports"]["excel"], file_name=f"fiche_detaillee.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
            st.download_button("Télécharger PowerPoint", st.session_state["detail_exports"]["pptx"], file_name=f"fiche_detaillee.pptx", mime="application/vnd.openxmlformats-officedocument.presentationml.presentation")
