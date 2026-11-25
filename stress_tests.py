"""Module de Simulation Monte Carlo & Pricing de Produits Structurés.
Permet d'analyser les trajectoires sous stress et de pricer des produits (Autocall/Phoenix)
sur des indices issus de la base de données ou des indices synthétiques sur-mesure.
"""

import streamlit as st
import numpy as np
import pandas as pd

from monte_carlo_engine import (
    MarketScenario,
    DecrementIndex,
    AthenaProduct,
    PhoenixProduct,
    SimulationEngine
)
from financial_core import AssetAnalytics, extract_decrement, create_excel_report


def get_db_asset_defaults(asset_id, repo, assets_df, prices_pivot):
    """Extrait automatiquement les paramètres de simulation depuis la base de données."""
    info = repo.get_asset_info(asset_id)
    name = str(info.get('name', 'Inconnu'))
    ticker = str(info.get('ticker_bloomberg', ''))
    isin = str(info.get('isin', ''))

    # 1. Niveau initial S0
    s0 = 1000.0
    if asset_id in prices_pivot.columns:
        s_prices = prices_pivot[asset_id].dropna()
        if len(s_prices) > 0:
            s0 = float(s_prices.iloc[-1])
    elif pd.notna(info.get('last_price')) and float(info.get('last_price', 0)) > 0:
        s0 = float(info['last_price'])

    # 2. Volatilité annualisée (priorité à la volatilité implicite si disponible)
    vol = 0.20
    if pd.notna(info.get('implied_vol')) and float(info.get('implied_vol', 0)) > 0:
        raw_v = float(info['implied_vol'])
        vol = raw_v / 100.0 if raw_v > 1.0 else raw_v
    elif asset_id in prices_pivot.columns:
        s_prices = prices_pivot[asset_id].dropna()
        if len(s_prices) >= 20:
            model = AssetAnalytics(asset_id, info, s_prices)
            vol_calc = model.vol(days=252)
            if pd.notna(vol_calc) and vol_calc > 0:
                vol = float(vol_calc) / 100.0
        elif pd.notna(info.get('vol_3y')) and float(info.get('vol_3y', 0)) > 0:
            raw_v = float(info['vol_3y'])
            vol = raw_v / 100.0 if raw_v > 1.0 else raw_v
    elif pd.notna(info.get('vol_3y')) and float(info.get('vol_3y', 0)) > 0:
        raw_v = float(info['vol_3y'])
        vol = raw_v / 100.0 if raw_v > 1.0 else raw_v

    # 3. Rendement de dividende naturel réinvesti
    div_yield = 0.035
    if pd.notna(info.get('dividend_yield')) and float(info.get('dividend_yield', 0)) > 0:
        raw_div = float(info['dividend_yield'])
        div_yield = raw_div / 100.0 if raw_div > 1.0 else raw_div

    # 4. Décrément annuel
    dec_val, dec_type = extract_decrement(name)
    dec_type = dec_type if dec_type in ("PERCENT", "POINTS") else "POINTS"
    if dec_val is not None:
        dec_amount = float(dec_val)
    else:
        dec_amount = 0.0

    disp_name = f"{name} ({ticker})" if (ticker and ticker != 'nan') else name

    is_implied_vol = bool(pd.notna(info.get('implied_vol')) and float(info.get('implied_vol', 0)) > 0)
    impl_mat = str(info.get('implied_vol_mat', 'DEC26')).strip() if is_implied_vol else ""
    impl_date = ""
    if is_implied_vol and pd.notna(info.get('implied_vol_date')):
        try:
            impl_date = pd.to_datetime(info['implied_vol_date']).strftime('%d/%m/%Y')
        except Exception:
            impl_date = str(info['implied_vol_date']).strip()

    return {
        'nom': disp_name,
        's0': s0,
        'vol': vol,
        'div_yield': div_yield,
        'dec_val': dec_amount,
        'dec_type': dec_type,
        'is_implied_vol': is_implied_vol,
        'impl_mat': impl_mat,
        'impl_date': impl_date
    }


def render_stress_tests_view(repo, assets_df, prices_pivot):
    """Point d'entrée pour le rendu de l'écran Stress Tests & Pricing."""
    st.markdown("<h1 class='main-header'>Pricing de Produits Structurés (Athéna & Phoenix)</h1>", unsafe_allow_html=True)

    mode = st.radio(
        "Mode d'analyse :",
        ["Pricing", "Comparaison Trajectoires"],
        horizontal=True,
        key="st_main_mode"
    )

    st.markdown("<div style='margin-bottom: 15px;'></div>", unsafe_allow_html=True)

    # =========================================================================
    # BRANCHE 1 : PRICING DÉDIÉ PRODUITS STRUCTURÉS (ATHÉNA & PHOENIX)
    # =========================================================================
    if mode == "Pricing":
        # ---------------------------------------------------------------------
        # 1. PARAMÈTRES GLOBAUX DU MARCHÉ ET DE LA SIMULATION
        # ---------------------------------------------------------------------
        with st.expander("1. Paramètres Globaux de Marché & Simulation", expanded=True):
            col_g1, col_g2, col_g3, col_g4, col_g5 = st.columns(5)
            with col_g1:
                taux_sans_risque = st.number_input(
                    "Taux sans risque r (%)", 
                    value=3.0, step=0.25, format="%.2f", 
                    help="Drift du Total Return sous-jacent (mesure risque-neutre).",
                    key="prc_rf"
                ) / 100.0
            with col_g2:
                taux_actualisation = st.number_input(
                    "Taux d'actualisation (%)", 
                    value=3.0, step=0.25, format="%.2f",
                    help="Taux utilisé pour actualiser les flux de coupons et de capital.",
                    key="prc_act"
                ) / 100.0
            with col_g3:
                annees = st.number_input("Maturité totale (années)", value=5, min_value=1, max_value=15, step=1, key="prc_annees")
            with col_g4:
                nb_trajectoires = st.number_input("Nb trajectoires Monte Carlo", value=10000, min_value=1000, max_value=50000, step=1000, key="prc_nb_traj")
            with col_g5:
                seed = st.number_input("Graine aléatoire (Seed)", value=42, step=1, key="prc_seed")

        # ---------------------------------------------------------------------
        # 2. STRUCTURE DU PRODUIT STRUCTURÉ (PAYOFF)
        # ---------------------------------------------------------------------
        with st.expander("2. Caractéristiques du Produit Structuré", expanded=True):
            col_p1, col_p2, col_p3 = st.columns(3)
            with col_p1:
                type_produit = st.selectbox("Type de Produit Structuré", ["Athéna", "Phoenix"], key="prc_type_prod")
                barriere_rappel_pct = st.number_input("Barrière de Rappel Anticipé (%)", value=100.0, step=5.0, key="prc_b_rappel") / 100.0
                degressivite = st.number_input("Dégressivité du rappel (% par observation)", value=0.0, step=0.5, key="prc_degres")
                plancher_rappel_pct = None
                if degressivite > 0.0:
                    plancher_rappel_pct = st.number_input("Plancher de Rappel Dégressif (%)", value=70.0, step=5.0, key="prc_plancher") / 100.0

            with col_p2:
                niveau_pdi_pct = st.number_input("Barrière de Protection du Capital PDI (%)", value=50.0, step=5.0, key="prc_pdi") / 100.0
                coupon_periode = st.number_input("Coupon par période (%)", value=2.0, step=0.1, key="prc_coupon")
                
                freq_dict = {
                    "Trimestrielle (3 mois)": 3,
                    "Semestrielle (6 mois)": 6,
                    "Annuelle (12 mois)": 12,
                    "Mensuelle (1 mois)": 1,
                    "Quotidienne": 0
                }
                frequence_label = st.selectbox("Fréquence d'observation", list(freq_dict.keys()), index=0, key="prc_freq")
                frequence_obs_mois = freq_dict[frequence_label]
                
                obs_par_an = (12 / frequence_obs_mois) if frequence_obs_mois > 0 else 252
                st.caption(f"Coupon annualisé équivalent : **{coupon_periode * obs_par_an:.2f}% p.a.**")

            with col_p3:
                non_call_period_mois = st.number_input("Période de Non-Call (mois)", value=12, min_value=0, step=1, key="prc_non_call")
                if type_produit == "Phoenix":
                    barriere_coupon_pct = st.number_input("Barrière de Coupon (%)", value=70.0, step=5.0, key="prc_b_coup") / 100.0
                    avec_memoire = st.checkbox("Effet Mémoire des Coupons", value=True, key="prc_memoire")
                else:
                    barriere_coupon_pct = None
                    avec_memoire = True

        # ---------------------------------------------------------------------
        # 3. CONFIGURATION DES INDICES À VALORISER
        # ---------------------------------------------------------------------
        with st.expander("3. Configuration des Indices à Valoriser", expanded=True):
            nb_indices = st.number_input("Nombre d'indices à valoriser", min_value=1, max_value=3, value=1, step=1, key="prc_nb_indices")

            asset_options = dict(zip(assets_df['display_name'], assets_df['asset_id']))
            sorted_asset_names = sorted(asset_options.keys())

            liste_indices_pricing = []
            tabs_indices_prc = st.tabs([f"Indice {i+1}" for i in range(int(nb_indices))])

            for i, tab in enumerate(tabs_indices_prc):
                with tab:
                    # 1. Type d'indice D'ABORD (comme spécifié)
                    idx_type_label = st.radio(
                        f"Type d'indice {i+1} :",
                        ["Décrément en Points", "Décrément en Pourcentage", "Price Return"],
                        horizontal=True,
                        key=f"prc_type_{i}"
                    )

                    # 2. Origine de l'indice
                    source_choice = st.radio(
                        f"Origine de l'indice {i+1} :",
                        ["Base de Données", "Synthétique / Sur-mesure"],
                        horizontal=True,
                        key=f"prc_orig_{i}"
                    )

                    if source_choice == "Base de Données":
                        selected_asset_name = st.selectbox(
                            f"Rechercher un actif dans la base (Indice {i+1}) :",
                            options=sorted_asset_names,
                            index=0 if i == 0 else min(i, len(sorted_asset_names) - 1),
                            key=f"prc_db_select_{i}"
                        )
                        asset_id = asset_options[selected_asset_name]
                        db_params = get_db_asset_defaults(asset_id, repo, assets_df, prices_pivot)

                        c1, c2, c3 = st.columns(3)
                        with c1:
                            s0 = st.number_input(f"Niveau Initial S0 (pts)", value=float(db_params['s0']), step=10.0, format="%.2f", key=f"prc_s0_{i}_{asset_id}")
                        with c2:
                            vol = st.number_input(f"Volatilité Annuelle (%)", value=float(db_params['vol'] * 100.0), step=1.0, format="%.2f", key=f"prc_vol_{i}_{asset_id}")
                        with c3:
                            if idx_type_label == "Décrément en Points":
                                def_dec_pts = float(db_params['dec_val']) if (db_params['dec_type'] == "POINTS" and db_params['dec_val'] > 0) else 50.0
                                dec_val = st.number_input(f"Décrément Annuel (pts)", value=def_dec_pts, step=5.0, format="%.2f", key=f"prc_dec_pts_{i}_{asset_id}")
                                dec_type_final = "POINTS"
                                dec_amount_final = dec_val
                                div_yield_final = 0.0
                            elif idx_type_label == "Décrément en Pourcentage":
                                def_dec_pct = float(db_params['dec_val']) if (db_params['dec_type'] == "PERCENT" and db_params['dec_val'] > 0) else 5.0
                                dec_val = st.number_input(f"Décrément Annuel (%)", value=def_dec_pct, step=0.25, format="%.2f", key=f"prc_dec_pct_{i}_{asset_id}")
                                dec_type_final = "PERCENT"
                                dec_amount_final = dec_val
                                div_yield_final = 0.0
                            else:  # Price Return
                                def_div = float(db_params['div_yield'] * 100.0) if db_params['div_yield'] > 0 else 3.5
                                div_val = st.number_input(f"Dividende Annuel Réinvesti Non Perçu (%)", value=def_div, step=0.25, format="%.2f", key=f"prc_div_{i}_{asset_id}")
                                dec_type_final = "PRICE_RETURN"
                                dec_amount_final = 0.0
                                div_yield_final = div_val / 100.0

                        if db_params.get('is_implied_vol'):
                            dt_note = f" au {db_params['impl_date']}" if db_params.get('impl_date') else ""
                            st.caption(f"Volatilité issue du marché des options (Put ATM {db_params['impl_mat']}{dt_note}).")

                        nom_final = db_params['nom']
                    else:
                        nom_def = f"{idx_type_label} Synthétique" if i == 0 else f"{idx_type_label} {i+1}"
                        nom_input = st.text_input(f"Nom de l'indice synthétique {i+1} :", value=nom_def, key=f"prc_cust_name_{i}")

                        c1, c2, c3 = st.columns(3)
                        with c1:
                            s0 = st.number_input(f"Niveau Initial S0 (pts)", value=1000.0, step=100.0, format="%.1f", key=f"prc_cust_s0_{i}")
                        with c2:
                            vol = st.number_input(f"Volatilité Annuelle (%)", value=18.0 if i == 0 else 20.0, step=1.0, format="%.1f", key=f"prc_cust_vol_{i}")
                        with c3:
                            if idx_type_label == "Décrément en Points":
                                dec_val = st.number_input(f"Décrément Annuel (pts)", value=50.0, step=5.0, format="%.2f", key=f"prc_cust_dec_pts_{i}")
                                dec_type_final = "POINTS"
                                dec_amount_final = dec_val
                                div_yield_final = 0.0
                            elif idx_type_label == "Décrément en Pourcentage":
                                dec_val = st.number_input(f"Décrément Annuel (%)", value=5.0, step=0.25, format="%.2f", key=f"prc_cust_dec_pct_{i}")
                                dec_type_final = "PERCENT"
                                dec_amount_final = dec_val
                                div_yield_final = 0.0
                            else:  # Price Return
                                div_val = st.number_input(f"Dividende Annuel Réinvesti Non Perçu (%)", value=3.5, step=0.25, format="%.2f", key=f"prc_cust_div_{i}")
                                dec_type_final = "PRICE_RETURN"
                                dec_amount_final = 0.0
                                div_yield_final = div_val / 100.0

                        nom_final = nom_input

                    nom_affiche = nom_final
                    existing_names = [idx.nom for idx in liste_indices_pricing]
                    if nom_affiche in existing_names:
                        nom_affiche = f"{nom_affiche} ({i+1})"

                    liste_indices_pricing.append(DecrementIndex(
                        niveau_initial=float(s0),
                        decrement_annuel=float(dec_amount_final),
                        decrement_type=dec_type_final,
                        vol=float(vol) / 100.0,
                        dividend_yield=float(div_yield_final),
                        nom=nom_affiche
                    ))

        st.markdown("<div style='margin-bottom: 10px;'></div>", unsafe_allow_html=True)
        lancer_pricing = st.button("Lancer la Valorisation du Produit", type="primary", use_container_width=True, key="prc_btn_launch")

        if lancer_pricing:
            with st.spinner(f"Valorisation financière ({int(nb_trajectoires):,} trajectoires Monte Carlo vectorisées)..."):
                ref_s0 = 1000.0
                barriere_rappel = ref_s0 * barriere_rappel_pct
                niveau_pdi = ref_s0 * niveau_pdi_pct
                plancher_rappel = (ref_s0 * plancher_rappel_pct) if plancher_rappel_pct is not None else None

                if type_produit == "Athéna":
                    mon_produit = AthenaProduct(
                        barriere_rappel=barriere_rappel,
                        niveau_pdi=niveau_pdi,
                        non_call_period_mois=int(non_call_period_mois),
                        frequence_obs_mois=int(frequence_obs_mois),
                        degressivite=float(degressivite),
                        plancher_rappel=plancher_rappel,
                        coupon_periode=float(coupon_periode),
                        ref_s0=ref_s0
                    )
                else:
                    barriere_coupon = ref_s0 * barriere_coupon_pct
                    mon_produit = PhoenixProduct(
                        barriere_rappel=barriere_rappel,
                        barriere_coupon=barriere_coupon,
                        niveau_pdi=niveau_pdi,
                        non_call_period_mois=int(non_call_period_mois),
                        frequence_obs_mois=int(frequence_obs_mois),
                        degressivite=float(degressivite),
                        plancher_rappel=plancher_rappel,
                        coupon_periode=float(coupon_periode),
                        avec_memoire=avec_memoire,
                        ref_s0=ref_s0
                    )

                moteur = SimulationEngine(nb_trajectoires=int(nb_trajectoires), seed=int(seed))
                results_pricing = moteur.run_pricing_simulation(
                    list_indices=liste_indices_pricing,
                    product=mon_produit,
                    annees=int(annees),
                    r_sans_risque=float(taux_sans_risque),
                    taux_actualisation=float(taux_actualisation)
                )

                # --- 1. BANDEAU DE KPIS DE VALORISATION ---
                memoire_str = " (Mémoire)" if (type_produit == "Phoenix" and avec_memoire) else (" (Sans Mémoire)" if type_produit == "Phoenix" else "")
                st.markdown(f"<div class='section-title'>Indicateurs de Performance et de Risque : {type_produit}{memoire_str}</div>", unsafe_allow_html=True)

                def _render_kpi_card(title, value, subtitle=""):
                    sub_text = subtitle if subtitle else "&nbsp;"
                    return f"""<div style="background-color: #f8fafc; border: 1px solid #e2e8f0; border-radius: 8px; padding: 12px 14px; height: 105px; min-height: 105px; max-height: 105px; box-sizing: border-box; display: flex; flex-direction: column; justify-content: space-between; overflow: hidden;">
                        <div style="font-size: 0.72rem; color: #64748b; font-weight: 600; text-transform: uppercase; letter-spacing: 0.04em; height: 18px; line-height: 18px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;" title="{title}">{title}</div>
                        <div style="font-size: 1.45rem; color: #0f172a; font-weight: 700; line-height: 1.2; height: 32px; display: flex; align-items: center; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;">{value}</div>
                        <div style="font-size: 0.76rem; color: #64748b; font-weight: 500; height: 18px; line-height: 18px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;" title="{subtitle}">{sub_text}</div>
                    </div>"""

                for nom_idx, d in results_pricing.items():
                    st.markdown(f"<div style='font-weight: 600; font-size: 1.05rem; margin-top: 10px; margin-bottom: 8px; color: #0f172a;'>{nom_idx}</div>", unsafe_allow_html=True)
                    if type_produit == "Phoenix":
                        c1, c2, c3, c4, c5 = st.columns(5)
                        with c1:
                            st.markdown(_render_kpi_card("Taux d'Autocall", f"{d['pct_rappel']:.1f} %", "Rappel anticipé"), unsafe_allow_html=True)
                        with c2:
                            st.markdown(_render_kpi_card("TRA", f"{d['tri_moyen']:.2f} %", f"Médian {d['tri_median']:.2f}%"), unsafe_allow_html=True)
                        with c3:
                            st.markdown(_render_kpi_card("Duration", f"{d['duration']:.2f} ans", "Durée effective"), unsafe_allow_html=True)
                        with c4:
                            st.markdown(_render_kpi_card("Risque PDI", f"{d['pct_pdi']:.2f} %", f"Perte moy. {d['perte_moy_pdi']:.1f}%"), unsafe_allow_html=True)
                        with c5:
                            st.markdown(_render_kpi_card("Coupons Encaissés", f"{d['taux_coupons_encaisses']:.1f} %", f"Mém. activée {d['efficacite_memoire']:.1f}%"), unsafe_allow_html=True)
                    else:
                        c1, c2, c3, c4, c5 = st.columns(5)
                        with c1:
                            st.markdown(_render_kpi_card("Taux d'Autocall", f"{d['pct_rappel']:.1f} %", "Rappel anticipé"), unsafe_allow_html=True)
                        with c2:
                            st.markdown(_render_kpi_card("TRA", f"{d['tri_moyen']:.2f} %", f"Médian {d['tri_median']:.2f}%"), unsafe_allow_html=True)
                        with c3:
                            st.markdown(_render_kpi_card("Duration", f"{d['duration']:.2f} ans", "Durée effective"), unsafe_allow_html=True)
                        with c4:
                            st.markdown(_render_kpi_card("Risque PDI", f"{d['pct_pdi']:.2f} %", f"Perte moy. {d['perte_moy_pdi']:.1f}%"), unsafe_allow_html=True)
                        with c5:
                            st.markdown(_render_kpi_card("Fair Value", f"{d['moy_payoff']:.2f} %", f"TRA > 0 : {d['pct_tri_positif']:.1f}%"), unsafe_allow_html=True)

                st.divider()

                # --- 2. TABLEAU COMPARATIF CONSOLIDÉ ---
                st.markdown("<div class='section-title'>Tableau Comparatif Consolidé</div>", unsafe_allow_html=True)
                data_pricing_table = []
                for nom_idx, d in results_pricing.items():
                    dec_type_disp = getattr(d['index'], 'decrement_type', 'POINTS')
                    if dec_type_disp == "POINTS":
                        caract_str = f"Dec {d['index'].decrement_annuel:.0f} pts"
                    elif dec_type_disp == "PERCENT":
                        caract_str = f"Dec {d['index'].decrement_annuel:.2f} %"
                    else:
                        caract_str = f"Div {d['index'].dividend_yield*100:.2f} %"

                    row = {
                        "Indice": nom_idx,
                        "Type & Paramètre": caract_str,
                        "Volatilité": f"{d['index'].vol*100:.1f} %",
                        "Taux d'Autocall": f"{d['pct_rappel']:.1f} %",
                        "TRA Moyen": f"{d['tri_moyen']:.2f} %",
                        "TRA Médian": f"{d['tri_median']:.2f} %",
                        "Duration": f"{d['duration']:.2f} ans",
                        "Risque PDI": f"{d['pct_pdi']:.2f} %",
                        "Perte Moyenne si PDI": f"{d['perte_moy_pdi']:.1f} %",
                        "Fair Value (% nom.)": f"{d['moy_payoff']:.2f} %"
                    }
                    if type_produit == "Phoenix":
                        row["Coupons Encaissés"] = f"{d['taux_coupons_encaisses']:.1f} %"
                        row["Efficacité Mémoire"] = f"{d['efficacite_memoire']:.1f} %"
                    data_pricing_table.append(row)

                df_pricing_summary = pd.DataFrame(data_pricing_table)
                st.dataframe(df_pricing_summary, use_container_width=True, hide_index=True)

                st.divider()

                # --- 3. LES 4 GRAPHIQUES PLOTLY ---
                st.markdown("<div class='section-title'>1. Indicateurs Comparés de Risque et de Rendement</div>", unsafe_allow_html=True)
                fig_kpis = moteur.plot_pricing_kpis_bars(results_pricing)
                st.plotly_chart(fig_kpis, use_container_width=True, config={'displayModeBar': False})

                st.divider()
                st.markdown("<div class='section-title'>2. Scénarios de Sortie par Année (Rappels vs Échéance)</div>", unsafe_allow_html=True)
                fig_waterfall = moteur.plot_pricing_waterfall(results_pricing, mon_produit)
                st.plotly_chart(fig_waterfall, use_container_width=True, config={'displayModeBar': False})

                st.divider()
                st.markdown("<div class='section-title'>3. Distribution Comparée du TRA</div>", unsafe_allow_html=True)
                fig_tri_dist = moteur.plot_pricing_distribution_tri(results_pricing)
                st.plotly_chart(fig_tri_dist, use_container_width=True, config={'displayModeBar': False})

                st.divider()
                st.markdown("<div class='section-title'>4. Trajectoires Médianes face aux Barrières du Produit</div>", unsafe_allow_html=True)
                fig_traj_barr = moteur.plot_pricing_trajectoires_avec_barrieres(results_pricing, mon_produit, annees=int(annees))
                st.plotly_chart(fig_traj_barr, use_container_width=True, config={'displayModeBar': False})

                # --- 4. EXPORT EXCEL ---
                st.divider()
                dfs_export = {
                    "Synthèse Pricing": df_pricing_summary
                }
                waterfall_rows = []
                for nom_idx, d in results_pricing.items():
                    for item in d["sorties_obs"]:
                        waterfall_rows.append({
                            "Indice": nom_idx,
                            "Observation": item["obs_num"],
                            "Horizon (ans)": round(item["annee"], 2),
                            "Barrière Rappel (%)": item["barriere_pct"],
                            "Taux de Rappel (%)": round(item["pct_rappel"], 2)
                        })
                    waterfall_rows.append({
                        "Indice": nom_idx,
                        "Observation": "Maturité",
                        "Horizon (ans)": int(annees),
                        "Barrière Rappel (%)": "Pair",
                        "Taux de Rappel (%)": round(d.get("pct_remb_pair", 0.0), 2)
                    })
                    waterfall_rows.append({
                        "Indice": nom_idx,
                        "Observation": "Maturité",
                        "Horizon (ans)": int(annees),
                        "Barrière Rappel (%)": "PDI",
                        "Taux de Rappel (%)": round(d.get("pct_pdi", 0.0), 2)
                    })
                dfs_export["Sorties Temporelles"] = pd.DataFrame(waterfall_rows)

                excel_report_buf = create_excel_report(dfs_export)
                st.download_button(
                    "Télécharger le Rapport Complet de Valorisation (Excel)",
                    data=excel_report_buf.getvalue(),
                    file_name=f"Pricing_{type_produit}_{int(annees)}A.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    use_container_width=True
                )
        else:
            st.info("Ajustez les paramètres du produit et de vos indices ci-dessus, puis cliquez sur le bouton pour lancer la valorisation.")

    # =========================================================================
    # BRANCHE 2 : COMPARAISON DE TRAJECTOIRES MULTI-RÉGIMES (HISTORIQUE)
    # =========================================================================
    else:
        # 1. SCÉNARIO MACROÉCONOMIQUE
        with st.expander("1. Scénario Macroéconomique de Marché", expanded=True):
            col_m1, col_m2 = st.columns([1, 1])
            with col_m1:
                annees = st.number_input("Durée totale de la simulation (années)", value=10, min_value=1, max_value=20, step=1, key="st_annees")
            with col_m2:
                nb_periodes = st.number_input("Nombre de régimes de marché successifs", value=1, min_value=1, max_value=4, step=1, key="st_nb_periodes")

            mes_regimes_input = []
            somme_annees = 0

            cols_regimes = st.columns(int(nb_periodes))
            for i in range(int(nb_periodes)):
                with cols_regimes[i]:
                    st.markdown(f"**Période {i+1}**")
                    def_d = int(annees) if nb_periodes == 1 else (2 if i == 0 else (int(annees) - 2))
                    def_rp = 0.0 if i == 0 else (-15.0 if i == 1 else 5.0)

                    d = st.number_input(f"Durée (ans) P{i+1}", value=max(1, def_d), min_value=1, key=f"st_dur_{i}")
                    rp = st.number_input(f"Drift Price Return P{i+1} (%)", value=def_rp, format="%.1f", step=1.0, key=f"st_rp_{i}")

                    somme_annees += int(d)
                    mes_regimes_input.append({
                        "duree_annees": int(d),
                        "r_perf": rp / 100.0
                    })

            if somme_annees != int(annees):
                st.warning(f"La somme des régimes ({somme_annees} ans) est différente de la durée totale ({int(annees)} ans). Veuillez ajuster les durées.")

        # 2. CONFIGURATION DES INDICES
        with st.expander("2. Configuration des Indices (Référentiel ou Synthétique)", expanded=True):
            nb_indices = st.number_input("Nombre d'indices à comparer", min_value=1, max_value=3, value=1, step=1, key="st_nb_indices")

            asset_options = dict(zip(assets_df['display_name'], assets_df['asset_id']))
            sorted_asset_names = sorted(asset_options.keys())

            liste_indices = []
            tabs_indices = st.tabs([f"Indice {i+1}" for i in range(int(nb_indices))])

            for i, tab in enumerate(tabs_indices):
                with tab:
                    source_choice = st.radio(
                        f"Origine de l'indice {i+1} :",
                        ["Indice de la Base de Données", "Indice Synthétique / Sur-mesure"],
                        horizontal=True,
                        key=f"st_source_choice_{i}"
                    )

                    if source_choice == "Indice de la Base de Données":
                        selected_asset_name = st.selectbox(
                            "Rechercher un actif dans la base (Nom, Ticker) :",
                            options=sorted_asset_names,
                            index=0 if i == 0 else min(i, len(sorted_asset_names) - 1),
                            key=f"st_db_select_{i}"
                        )
                        asset_id = asset_options[selected_asset_name]
                        db_params = get_db_asset_defaults(asset_id, repo, assets_df, prices_pivot)

                        c1, c2, c3, c4 = st.columns(4)
                        with c1:
                            s0 = st.number_input(f"Niveau Initial S0 (pts)", value=float(db_params['s0']), step=10.0, format="%.2f", key=f"st_s0_{i}_{asset_id}")
                        with c2:
                            sub_v, sub_u = st.columns([1.3, 1.0])
                            with sub_u:
                                type_opts = ["pts", "%"]
                                def_u_idx = 1 if db_params['dec_type'] == "PERCENT" else 0
                                dec_unit = st.selectbox("Unité", type_opts, index=def_u_idx, key=f"st_dectype_{i}_{asset_id}")
                            with sub_v:
                                is_pct = (dec_unit == "%")
                                if db_params['dec_val'] == 0.0:
                                    def_dec_val = 0.0
                                elif is_pct and db_params['dec_type'] == "PERCENT":
                                    def_dec_val = float(db_params['dec_val'])
                                elif not is_pct and db_params['dec_type'] == "POINTS":
                                    def_dec_val = float(db_params['dec_val'])
                                else:
                                    def_dec_val = 5.0 if is_pct else 50.0
                                step_dec = 0.25 if is_pct else 5.0
                                dec = st.number_input(f"Décrément ({dec_unit})", value=float(def_dec_val), step=step_dec, format="%.2f", key=f"st_dec_{i}_{asset_id}_{dec_unit}")
                            dec_type_final = "PERCENT" if dec_unit == "%" else "POINTS"
                        with c3:
                            vol = st.number_input(f"Volatilité Annuelle (%)", value=float(db_params['vol'] * 100.0), step=1.0, format="%.2f", key=f"st_vol_{i}_{asset_id}")
                        with c4:
                            yi = st.number_input(f"Dividende Réinvesti (%)", value=float(db_params['div_yield'] * 100.0), step=0.25, format="%.2f", key=f"st_yi_{i}_{asset_id}")

                        if db_params.get('is_implied_vol'):
                            dt_note = f" au {db_params['impl_date']}" if db_params.get('impl_date') else ""
                            st.caption(f"Volatilité issue du marché des options (Put ATM {db_params['impl_mat']}{dt_note}).")

                        nom_final = db_params['nom']
                    else:
                        nom_def = "Indice Décrément 50" if i == 0 else f"Indice Synthétique {i+1}"
                        nom_input = st.text_input("Nom de l'indice synthétique :", value=nom_def, key=f"st_custom_name_{i}")

                        c1, c2, c3, c4 = st.columns(4)
                        with c1:
                            s0 = st.number_input(f"Niveau Initial S0 (pts)", value=1000.0, step=100.0, format="%.1f", key=f"st_cust_s0_{i}")
                        with c2:
                            sub_v, sub_u = st.columns([1.3, 1.0])
                            with sub_u:
                                type_opts = ["pts", "%"]
                                dec_unit = st.selectbox("Unité", type_opts, index=0, key=f"st_cust_dectype_{i}")
                            with sub_v:
                                is_pct = (dec_unit == "%")
                                def_val = 5.0 if is_pct else 50.0
                                step_dec = 0.25 if is_pct else 5.0
                                dec = st.number_input(f"Décrément ({dec_unit})", value=float(def_val), step=step_dec, format="%.2f", key=f"st_cust_dec_{i}_{dec_unit}")
                            dec_type_final = "PERCENT" if dec_unit == "%" else "POINTS"
                        with c3:
                            vol = st.number_input(f"Volatilité Annuelle (%)", value=18.0 if i == 0 else 20.0, step=1.0, format="%.1f", key=f"st_cust_vol_{i}")
                        with c4:
                            yi = st.number_input(f"Dividende Réinvesti (%)", value=3.0 if i == 0 else 3.5, step=0.25, format="%.2f", key=f"st_cust_yi_{i}")

                        nom_final = nom_input

                    nom_affiche = nom_final
                    existing_names = [idx.nom for idx in liste_indices]
                    if nom_affiche in existing_names:
                        nom_affiche = f"{nom_affiche} ({i+1})"

                    liste_indices.append(DecrementIndex(
                        niveau_initial=float(s0),
                        decrement_annuel=float(dec),
                        decrement_type=dec_type_final,
                        vol=float(vol) / 100.0,
                        dividend_yield=float(yi) / 100.0,
                        nom=nom_affiche
                    ))

        # Paramètres avancés
        with st.expander("Paramètres avancés de simulation", expanded=False):
            c_sim1, c_sim2 = st.columns(2)
            with c_sim1:
                nb_trajectoires = st.number_input("Nombre de trajectoires Monte Carlo", value=10000, min_value=1000, max_value=50000, step=1000, key="st_nb_traj")
            with c_sim2:
                seed = st.number_input("Graine aléatoire (Seed)", value=42, step=1, key="st_seed")

        st.markdown("<div style='margin-bottom: 10px;'></div>", unsafe_allow_html=True)
        lancer_traj = st.button("Lancer la Simulation de Trajectoires", type="primary", use_container_width=True, key="st_btn_launch")

        if lancer_traj:
            if somme_annees != int(annees):
                st.error(f"Incohérence : la somme des durées de régimes ({somme_annees} ans) doit être égale à la durée totale ({int(annees)} ans).")
                return

            moteur = SimulationEngine(nb_trajectoires=int(nb_trajectoires), seed=int(seed))
            scenario_krach = MarketScenario(config_regimes=mes_regimes_input, annees=int(annees))

            with st.spinner(f"Génération de {int(nb_trajectoires):,} trajectoires Monte Carlo vectorisées..."):
                results_multi = moteur.simulate_multi_indices(liste_indices, scenario_krach)

                st.markdown(f"<div class='section-title'>Indicateurs Clés & Niveaux Moyens (1 An, 5 Ans et Maturité)</div>", unsafe_allow_html=True)

                data_macro = []
                for nom_idx, d in results_multi.items():
                    dec_unit_str = "%" if getattr(d['index'], 'decrement_type', 'POINTS') == "PERCENT" else "pts"
                    row = {
                        "Indice": nom_idx,
                        "Spot Initial S0": f"{d['index'].niveau_initial:.2f} pts",
                        "Décrément Annuel": f"{d['index'].decrement_annuel:.2f} {dec_unit_str}",
                        "Volatilité": f"{d['index'].vol*100:.1f} %",
                        "Dividende Réinvesti": f"{d['index'].dividend_yield*100:.2f} %",
                        "Niveau Moyen 1 An": f"{d['moy_1an_dec']:.1f} pts ({d['moy_1an_dec_pct']:+.1f}%) [vs {d['moy_1an_pr']:.1f} pts | {d['moy_1an_pr_pct']:+.1f}% PR]",
                    }
                    if d.get("has_5ans", True):
                        row["Niveau Moyen 5 Ans"] = f"{d['moy_5ans_dec']:.1f} pts ({d['moy_5ans_dec_pct']:+.1f}%) [vs {d['moy_5ans_pr']:.1f} pts | {d['moy_5ans_pr_pct']:+.1f}% PR]"

                    row[f"Niveau Moyen Final ({scenario_krach.annees} ans)"] = f"{d['moy_dec']:.1f} pts ({d['moy_dec_pct']:+.1f}%) [vs {d['moy_pr']:.1f} pts | {d['moy_pr_pct']:+.1f}% PR]"
                    row["Écart Final (Dec - PR)"] = f"{d['ecart_moy_pct']:+.2f} % ({d['ecart_moy_pts']:+.1f} pts)"
                    row["Risque Crash < 50%"] = f"{d['pct_crash_50_dec']:.1f} % (vs {d['pct_crash_50_pr']:.1f} % PR)"
                    data_macro.append(row)
                st.dataframe(pd.DataFrame(data_macro), use_container_width=True, hide_index=True)

                st.divider()

                # Graphique 1 : Trajectoires Médianes
                st.markdown("<div class='section-title'>1. Trajectoires Médianes & Fuseaux Inter-centiles [P10 - P90]</div>", unsafe_allow_html=True)
                fig_multi_traj = moteur.plot_multi_trajectoires(results_multi, scenario_krach)
                st.plotly_chart(fig_multi_traj, use_container_width=True, config={'displayModeBar': False})

                st.divider()

                # Graphique 2 : Dynamique temporelle des écarts
                st.markdown("<div class='section-title'>2. Dynamique Temporelle des Écarts (Décrément - Price Return)</div>", unsafe_allow_html=True)
                fig_multi_ecarts = moteur.plot_multi_courbes_ecarts(results_multi, scenario_krach, filter_active=False)
                st.plotly_chart(fig_multi_ecarts, use_container_width=True, config={'displayModeBar': False})

                st.divider()

                # Graphique 3 : Dispersion des écarts à maturité
                st.markdown("<div class='section-title'>3. Dispersion Comparée des Écarts à Maturité</div>", unsafe_allow_html=True)
                st.caption("Distribution de l'écart (Dec - PR) / S0 à maturité bornée entre les centiles P1 et P99.")
                fig_multi_disp = moteur.plot_multi_dispersion_ecarts(results_multi, scenario_krach)
                st.plotly_chart(fig_multi_disp, use_container_width=True, config={'displayModeBar': False})

