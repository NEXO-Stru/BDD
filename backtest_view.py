# -*- coding: utf-8 -*-
"""
backtest_view.py
================
Interface utilisateur Streamlit pour le Backtest Historique de Produits Structurés.
Intégré à projet-db : consomme directement les séries temporelles de Supabase (prices_pivot).
"""

import io
import datetime
import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go

from backtest_engine import StructuredProductBacktest


def render_backtest_view(repo, assets_df, prices_pivot):
    """Point d'entrée de la vue Streamlit pour le Backtest Historique."""
    st.markdown("<h1 class='main-header'>Backtest Historique (Autocall / Phoenix)</h1>", unsafe_allow_html=True)
    st.markdown(
        "Simulation quantitative glissante quotidienne (*Rolling Inception*) sur l'historique réel "
        "des cours stockés dans **Supabase**."
    )

    if prices_pivot is None or prices_pivot.empty:
        st.error("Aucune donnée de cours disponible dans Supabase.")
        return

    # -------------------------------------------------------------------------
    # 1. SÉLECTION DES SOUS-JACENTS (BRANCHÉ SUR SUPABASE)
    # -------------------------------------------------------------------------
    st.markdown("<div class='section-title'>1. Sélection des Sous-Jacents</div>", unsafe_allow_html=True)

    # Création du dictionnaire d'options lisible {Nom (Ticker): asset_id}
    priced_asset_ids = [c for c in prices_pivot.columns if c in assets_df['asset_id'].values]
    priced_assets_df = assets_df[assets_df['asset_id'].isin(priced_asset_ids)].copy()

    asset_options = {}
    for _, row in priced_assets_df.iterrows():
        disp_name = row.get('display_name')
        if not disp_name or pd.isna(disp_name):
            name = row.get('name', 'Inconnu')
            ticker = row.get('ticker_bloomberg', '')
            disp_name = f"{name} ({ticker})" if ticker else name
        asset_options[disp_name] = row['asset_id']

    # Présélection par défaut (ex: 2 premières actions)
    default_selection = list(asset_options.keys())[:3] if len(asset_options) >= 3 else list(asset_options.keys())

    selected_names = st.multiselect(
        "Choisissez les sous-jacents du produit structuré :",
        options=list(asset_options.keys()),
        default=default_selection,
        help="Recherchez par nom d'entreprise ou ticker Bloomberg."
    )

    if not selected_names:
        st.warning("Veuillez sélectionner au moins un sous-jacent pour lancer la simulation.")
        return

    selected_ids = [asset_options[name] for name in selected_names]

    # Alignement sur l'historique commun le plus récent (common_start_date)
    sub_prices = prices_pivot[selected_ids].dropna()
    if sub_prices.empty or len(sub_prices) < 252:
        st.error("Historique commun insuffisant pour ces sous-jacents (minimum 1 an requis).")
        return

    # Renommage des colonnes avec les noms d'affichage pour la lisibilité
    id_to_disp = {v: k.split(' (')[0] for k, v in asset_options.items()}
    sub_prices_named = sub_prices.rename(columns=id_to_disp)

    date_min = sub_prices.index.min()
    date_max = sub_prices.index.max()
    nb_dates = len(sub_prices)
    nb_years = nb_dates / 252.0

    st.info(
        f"**Historique commun d'évaluation :** du **{date_min.strftime('%d/%m/%Y')}** au **{date_max.strftime('%d/%m/%Y')}** "
        f"({nb_dates:,} séances boursières, soit environ **{nb_years:.1f} ans** de profondeur de simulation)."
    )

    # -------------------------------------------------------------------------
    # 2. PARAMÈTRES DU PRODUIT STRUCTURÉ
    # -------------------------------------------------------------------------
    st.markdown("<div class='section-title'>2. Caractéristiques Financières du Produit</div>", unsafe_allow_html=True)

    with st.expander("Configurer les paramètres du produit", expanded=True):
        col1, col2, col3 = st.columns(3)

        with col1:
            st.markdown("##### Durée & Fréquence")
            duree_vie = st.number_input("Durée de vie maximale (ans)", min_value=1, max_value=12, value=5, step=1)
            
            freq_choice = st.selectbox(
                "Fréquence de constatation",
                options=["Trimestrielle (3 mois)", "Semestrielle (6 mois)", "Annuelle (1 an)", "Mensuelle (1 mois)"],
                index=0
            )
            freq_mapping = {
                "Trimestrielle (3 mois)": 0.25,
                "Semestrielle (6 mois)": 0.5,
                "Annuelle (1 an)": 1.0,
                "Mensuelle (1 mois)": 1.0 / 12.0
            }
            freq_obs = freq_mapping[freq_choice]
            total_periods = int(duree_vie / freq_obs)

            from_redempt = st.number_input(
                f"1ère constatation de rappel (période sur {total_periods})",
                min_value=1,
                max_value=max(1, total_periods - 1),
                value=int(1.0 / freq_obs),  # Par défaut après 1 an
                help="Ex: 4 pour un rappel démarrant après 1 an en fréquence trimestrielle."
            )

            from_coupon = st.number_input(
                f"1ère constatation de coupon (période sur {total_periods})",
                min_value=1,
                max_value=total_periods,
                value=1
            )

        with col2:
            st.markdown("##### Coupons & Protection PDI")
            coupon_val = st.number_input("Coupon par période (%)", min_value=0.1, max_value=25.0, value=2.0, step=0.1)
            coupon_ann = coupon_val / freq_obs
            st.caption(f"Équivalent annualisé brut : **{coupon_ann:.2f} % par an**")

            coupon_type = st.radio("Mécanisme de coupon :", ["Avec Effet Mémoire", "Garanti", "Sans Mémoire"], index=0)
            memoire = 1 if coupon_type == "Avec Effet Mémoire" else 0
            garanti = 1 if coupon_type == "Garanti" else 0

            barriere_coupon = st.number_input("Barrière de coupon (%)", min_value=10.0, max_value=120.0, value=100.0, step=5.0)
            pdi = st.number_input("Barrière de protection du capital PDI (%)", min_value=10.0, max_value=100.0, value=50.0, step=5.0)

        with col3:
            st.markdown("##### Dégressivité & Lookback")
            rule_underlying = st.selectbox(
                "Règle de performance sous-jacents :",
                ["Worst-of (Action la plus basse)", "Panier équipondéré (Moyenne)", "Médiane"],
                index=0
            )
            worst_of = 1 if rule_underlying.startswith("Worst-of") else 0
            mediane = 1 if rule_underlying.startswith("Médiane") else 0

            strike_choice = st.selectbox(
                "Mécanisme de Strike initial :",
                ["Standard (Spot au jour t0)", "Lookback Min (Cours le plus bas)", "Lookback Moyen (Moyenne asiatique)"],
                index=0
            )
            if strike_choice.startswith("Lookback Min"):
                strike_type = 'lookback_min'
                c_lb1, c_lb2 = st.columns(2)
                nb_dates_min = c_lb1.number_input("Nb de dates", min_value=2, max_value=12, value=3, step=1)
                freq_min = c_lb2.number_input("Intervalle (j. bourse)", min_value=1, max_value=60, value=20, step=5)
            elif strike_choice.startswith("Lookback Moyen"):
                strike_type = 'lookback_moy'
                c_lb1, c_lb2 = st.columns(2)
                nb_dates_min = c_lb1.number_input("Nb de dates", min_value=2, max_value=12, value=3, step=1)
                freq_min = c_lb2.number_input("Intervalle (j. bourse)", min_value=1, max_value=60, value=20, step=5)
            else:
                strike_type = 'standard'
                nb_dates_min = 1
                freq_min = 1

            degr_choice = st.selectbox(
                "Dégressivité de la barrière de rappel :",
                ["Aucune (Barrière fixe à 100%)", "Linéaire (Baisse par période)", "Paliers semestriels", "Annuelle (Step-down)"],
                index=0
            )
            if degr_choice.startswith("Linéaire"):
                degressivite_mode = 'lineaire'
                degressivite_rappel = st.number_input("Baisse par période (%)", min_value=0.1, max_value=10.0, value=1.0, step=0.5)
                degressivite_rappel_ann = 0.0
            elif degr_choice.startswith("Paliers"):
                degressivite_mode = 'palier'
                degressivite_rappel = 0.0
                degressivite_rappel_ann = 0.0
            elif degr_choice.startswith("Annuelle"):
                degressivite_mode = 'annuelle'
                degressivite_rappel = 0.0
                degressivite_rappel_ann = st.number_input("Baisse annuelle (%)", min_value=1.0, max_value=15.0, value=5.0, step=1.0)
            else:
                degressivite_mode = 'lineaire'
                degressivite_rappel = 0.0
                degressivite_rappel_ann = 0.0

    # -------------------------------------------------------------------------
    # 3. BOUTON DE DÉCLENCHEMENT DU CALCUL
    # -------------------------------------------------------------------------
    st.divider()
    btn_run = st.button("Lancer le Backtest Historique", type="primary", use_container_width=True)

    if btn_run:
        with st.spinner(f"Simulation glissante de {len(sub_prices):,} lancements sur l'historique Supabase en cours..."):
            engine = StructuredProductBacktest(
                input_data=sub_prices_named,
                duree_vie=duree_vie,
                freq_obs=freq_obs,
                from_redempt=from_redempt,
                from_coupon=from_coupon,
                barriere_coupon=barriere_coupon,
                barriere_rappel=100.0,
                coupon=coupon_val,
                pdi=pdi,
                memoire=memoire,
                garanti=garanti,
                worst_of=worst_of,
                mediane=mediane,
                degressivite_mode=degressivite_mode,
                degressivite_rappel=degressivite_rappel,
                degressivite_rappel_ann=degressivite_rappel_ann,
                strike_type=strike_type,
                nb_dates_min=nb_dates_min,
                freq_min=freq_min,
                nb_dates_moy=nb_dates_min,
                freq_moy=freq_min,
                output_file=False
            )
            results = engine.run()
            # Génération du classeur Excel en mémoire pour le téléchargement
            excel_buffer = engine.export_excel(io.BytesIO())
            
            st.session_state["backtest_results"] = results
            st.session_state["backtest_excel"] = excel_buffer
            st.session_state["backtest_engine"] = engine

    # -------------------------------------------------------------------------
    # 4. RESTITUTION DES RÉSULTATS
    # -------------------------------------------------------------------------
    if "backtest_results" in st.session_state:
        res = st.session_state["backtest_results"]
        analysis_df = res['analysis']
        breakdown_df = res['breakdown']
        summary_series = res['performance_summary']
        exec_time = res.get('execution_time', 0)

        st.success(f"Simulation terminée avec succès en **{exec_time:.2f} secondes**.")

        # --- A. KPI CARDS ---
        st.markdown("<div class='section-title'>3. Indicateurs Clés de Performance & Risque</div>", unsafe_allow_html=True)

        val_map = dict(zip(analysis_df['Indicator'], analysis_df['Value']))

        kpi1, kpi2, kpi3, kpi4, kpi5 = st.columns(5)
        kpi1.metric(
            "Préservation du Capital",
            f"{val_map.get('Proportion qui n a pas perdu de capital (%)', 0):.1f} %",
            help="% des produits ayant remboursé 100% ou plus du capital investi."
        )
        kpi2.metric(
            "Durée de Vie Moyenne",
            f"{val_map.get('Average life', 0):.2f} ans",
            help="Durée effective moyenne avant remboursement anticipé."
        )
        kpi3.metric(
            "Rendement Moyen Final",
            f"{val_map.get('Mean of the returns', 0):.1f} %",
            help="Montant total moyen remboursé (Capital + Coupons cumulés)."
        )
        kpi4.metric(
            "Remboursement si Perte",
            f"{val_map.get('Remboursement moyen given loss in capital', 0):.1f} %",
            help="Montant moyen récupéré lorsque la barrière PDI a été cassée."
        )
        kpi5.metric(
            "Produits Encore en Vie",
            f"{val_map.get('Proportion de produits encore en vie (%)', 0):.1f} %",
            help="% de produits lancés récemment et n'ayant pas encore été rappelés."
        )

        st.divider()

        # --- B. GRAPHIQUES PLOTLY ---
        st.markdown("<div class='section-title'>4. Analyse Visuelle des Rappels et Rendements</div>", unsafe_allow_html=True)

        tab_g1, tab_g2 = st.tabs(["Répartition des Rappels Anticipés", "Historique des Remboursements Finaux"])

        with tab_g1:
            # Bar chart du breakdown de rappel
            bd_plot = breakdown_df.copy()
            bd_plot['Label'] = bd_plot['Periode'].apply(lambda x: f"Période {x}" if isinstance(x, (int, float)) and x > 0 else str(x))
            
            fig_bd = go.Figure()
            fig_bd.add_trace(go.Bar(
                x=bd_plot['Label'],
                y=bd_plot['Pourcentage de remboursement selon la periode (%)'],
                marker_color='#143F6A',
                text=bd_plot['Pourcentage de remboursement selon la periode (%)'].apply(lambda v: f"{v:.1f}%"),
                textposition='auto'
            ))
            fig_bd.update_layout(
                title="Pourcentage de produits rappelés par date d'observation",
                xaxis_title="Période de constatation",
                yaxis_title="Part des produits (%)",
                plot_bgcolor='white',
                paper_bgcolor='white',
                height=420,
                margin=dict(l=0, r=0, t=40, b=0)
            )
            st.plotly_chart(fig_bd, use_container_width=True)

        with tab_g2:
            # Courbe chronologique des remboursements finaux selon date de lancement
            clean_summary = summary_series.dropna()
            fig_ts = go.Figure()
            fig_ts.add_trace(go.Scatter(
                x=clean_summary.index,
                y=clean_summary['Montant de remboursement'],
                mode='lines',
                line=dict(color='#143F6A', width=1.5),
                name="Montant remboursé (%)"
            ))
            # Ligne seuil 100%
            fig_ts.add_hline(y=100, line_dash="dash", line_color="#28a745", annotation_text="Capital Garanti (100%)")
            # Ligne seuil PDI
            fig_ts.add_hline(y=pdi, line_dash="dot", line_color="#dc3545", annotation_text=f"Barrière PDI ({pdi}%)")
            
            fig_ts.update_layout(
                title="Montant final remboursé selon la date de souscription du produit",
                xaxis_title="Date de lancement du produit",
                yaxis_title="Remboursement total (% du nominal)",
                plot_bgcolor='white',
                paper_bgcolor='white',
                height=420,
                margin=dict(l=0, r=0, t=40, b=0)
            )
            st.plotly_chart(fig_ts, use_container_width=True)

        st.divider()

        # --- C. TABLEAUX DE SIMULATION DÉTAILLÉS ---
        st.markdown("<div class='section-title'>5. Données et Tableaux de Simulation Détaillés</div>", unsafe_allow_html=True)
        st.markdown(
            "Consultez ci-dessous l'ensemble des tables de calcul et matrices de simulation générées par le moteur."
        )

        dt_tab1, dt_tab2, dt_tab3, dt_tab4, dt_tab5, dt_tab6, dt_tab7 = st.tabs([
            "Indicateurs Statistiques",
            "Breakdown Rappels",
            "Pire Sous-Jacent",
            "Performances Constatées",
            "Flux de Coupons",
            "Rappels Anticipés",
            "Remboursements Globaux"
        ])

        with dt_tab1:
            st.markdown("##### Produits Expirés (Historique Complet)")
            st.dataframe(analysis_df, use_container_width=True)
            st.markdown("##### Produits Non Rappelés (Toujours en Vie)")
            st.dataframe(res.get('analysis_noncalled', pd.DataFrame()), use_container_width=True)

        with dt_tab2:
            st.markdown("##### Répartition des Remboursements selon la Période (%)")
            st.dataframe(breakdown_df, use_container_width=True)

        with dt_tab3:
            st.markdown("##### Sous-Jacent le Moins Performant à Chaque Période (Worst-of)")
            worst_df = res.get('worst', pd.DataFrame())
            if isinstance(worst_df.index, pd.DatetimeIndex):
                worst_disp = worst_df.copy()
                worst_disp.index = worst_disp.index.strftime('%d/%m/%Y')
                st.dataframe(worst_disp, use_container_width=True)
            else:
                st.dataframe(worst_df, use_container_width=True)

        with dt_tab4:
            st.markdown("##### Performance du Sous-Jacent Retenu (%) à Chaque Constatation")
            perf_df = res.get('perf_obs', pd.DataFrame())
            if isinstance(perf_df.index, pd.DatetimeIndex):
                perf_disp = perf_df.copy()
                perf_disp.index = perf_disp.index.strftime('%d/%m/%Y')
                st.dataframe(perf_disp.round(2), use_container_width=True)
            else:
                st.dataframe(perf_df.round(2), use_container_width=True)

        with dt_tab5:
            st.markdown("##### Montant des Coupons Payés (%) à Chaque Période")
            coupon_df = res.get('coupon_payment', pd.DataFrame())
            if isinstance(coupon_df.index, pd.DatetimeIndex):
                coupon_disp = coupon_df.copy()
                coupon_disp.index = coupon_disp.index.strftime('%d/%m/%Y')
                st.dataframe(coupon_disp, use_container_width=True)
            else:
                st.dataframe(coupon_df, use_container_width=True)

        with dt_tab6:
            st.markdown("##### Remboursements Anticipés Constatés (100% ou Valeur de Rappel)")
            early_df = res.get('early_redemption', pd.DataFrame())
            if isinstance(early_df.index, pd.DatetimeIndex):
                early_disp = early_df.copy()
                early_disp.index = early_disp.index.strftime('%d/%m/%Y')
                st.dataframe(early_disp, use_container_width=True)
            else:
                st.dataframe(early_df, use_container_width=True)

        with dt_tab7:
            st.markdown("##### Montant Total Remboursé (Capital + Coupons) par Date de Lancement")
            summary_disp = summary_series.copy()
            if isinstance(summary_disp.index, pd.DatetimeIndex):
                summary_disp.index = summary_disp.index.strftime('%d/%m/%Y')
            st.dataframe(summary_disp.round(2), use_container_width=True)

        st.divider()

        # --- D. EXPORT DU RAPPORT EXCEL OFFICIEL ---
        st.markdown("<div class='section-title'>6. Téléchargement du Rapport Institutionnel</div>", unsafe_allow_html=True)
        st.markdown(
            "Téléchargez le classeur Excel officiel complet comprenant les **10 onglets de simulation détaillés** "
            "(Performances, pire sous-jacent, dates de constatation, flux de coupons, ventilation des rappels)."
        )

        excel_data = st.session_state.get("backtest_excel")
        if excel_data:
            st.download_button(
                label="Télécharger le Rapport Excel Complet (10 Onglets)",
                data=excel_data.getvalue(),
                file_name=f"Backtest_Autocall_{datetime.datetime.now().strftime('%Y%m%d_%H%M')}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                use_container_width=True
            )
