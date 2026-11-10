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
from financial_core import AssetAnalytics, extract_decrement


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

    # 2. Volatilité annualisée
    vol = 0.20
    if asset_id in prices_pivot.columns:
        s_prices = prices_pivot[asset_id].dropna()
        if len(s_prices) >= 20:
            model = AssetAnalytics(s_prices)
            vol_calc = model.volatility_annualized(min(252, len(s_prices)))
            if pd.notna(vol_calc) and vol_calc > 0:
                vol = float(vol_calc)
    elif pd.notna(info.get('vol_3y')) and float(info.get('vol_3y', 0)) > 0:
        vol = float(info['vol_3y'])

    # 3. Rendement de dividende naturel réinvesti
    div_yield = 0.035
    if pd.notna(info.get('dividend_yield')) and float(info.get('dividend_yield', 0)) > 0:
        div_yield = float(info['dividend_yield'])

    # 4. Décrément annuel
    dec_val, dec_type = extract_decrement(name, isin)
    dec_pts = 50.0
    if dec_val is not None:
        if dec_type == "PERCENT":
            dec_pts = (dec_val / 100.0) * s0
        else:
            dec_pts = float(dec_val)
    else:
        dec_pts = 0.0

    disp_name = f"{name} ({ticker})" if (ticker and ticker != 'nan') else name

    return {
        'nom': disp_name,
        's0': s0,
        'vol': vol,
        'div_yield': div_yield,
        'dec_pts': dec_pts,
        'dec_val_raw': dec_val,
        'dec_type': dec_type
    }


def render_stress_tests_view(repo, assets_df, prices_pivot):
    """Point d'entrée pour le rendu de l'écran Stress Tests & Pricing."""
    st.markdown("<h1 class='main-header'>Stress Tests & Pricing Autocall</h1>", unsafe_allow_html=True)

    mode = st.radio(
        "Mode d'analyse :",
        ["Comparaison Trajectoires", "Pricing"],
        horizontal=True,
        key="st_main_mode"
    )

    st.markdown("<div style='margin-bottom: 15px;'></div>", unsafe_allow_html=True)

    # -------------------------------------------------------------------------
    # 1. SCÉNARIO MACROÉCONOMIQUE
    # -------------------------------------------------------------------------
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

    # -------------------------------------------------------------------------
    # 2. CARACTÉRISTIQUES DES INDICES (Base de données vs Synthétique)
    # -------------------------------------------------------------------------
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
                        s0 = st.number_input(f"Niveau Initial S0 (pts)", value=float(db_params['s0']), step=10.0, format="%.2f", key=f"st_s0_{i}")
                    with c2:
                        dec = st.number_input(f"Décrément Annuel D (pts)", value=float(db_params['dec_pts']), step=5.0, format="%.2f", key=f"st_dec_{i}")
                    with c3:
                        vol = st.number_input(f"Volatilité Annuelle (%)", value=float(db_params['vol'] * 100.0), step=1.0, format="%.2f", key=f"st_vol_{i}")
                    with c4:
                        yi = st.number_input(f"Dividende Réinvesti (%)", value=float(db_params['div_yield'] * 100.0), step=0.25, format="%.2f", key=f"st_yi_{i}")

                    nom_final = db_params['nom']
                else:
                    nom_def = "Indice Décrément 50" if i == 0 else f"Indice Synthétique {i+1}"
                    nom_input = st.text_input("Nom de l'indice synthétique :", value=nom_def, key=f"st_custom_name_{i}")

                    c1, c2, c3, c4 = st.columns(4)
                    with c1:
                        s0 = st.number_input(f"Niveau Initial S0 (pts)", value=1000.0, step=100.0, format="%.1f", key=f"st_cust_s0_{i}")
                    with c2:
                        dec = st.number_input(f"Décrément Annuel D (pts)", value=50.0 if i == 0 else 40.0, step=5.0, format="%.1f", key=f"st_cust_dec_{i}")
                    with c3:
                        vol = st.number_input(f"Volatilité Annuelle (%)", value=18.0 if i == 0 else 20.0, step=1.0, format="%.1f", key=f"st_cust_vol_{i}")
                    with c4:
                        yi = st.number_input(f"Dividende Réinvesti (%)", value=3.0 if i == 0 else 3.5, step=0.25, format="%.2f", key=f"st_cust_yi_{i}")

                    nom_final = nom_input

                liste_indices.append(DecrementIndex(
                    niveau_initial=float(s0),
                    decrement_annuel=float(dec),
                    vol=float(vol) / 100.0,
                    dividend_yield=float(yi) / 100.0,
                    nom=nom_final
                ))

    # -------------------------------------------------------------------------
    # 3. PARAMÈTRES DU PRODUIT STRUCTURÉ (Mode Pricing uniquement)
    # -------------------------------------------------------------------------
    mon_produit = None
    type_produit = "Athéna"
    avec_memoire = True
    taux_actualisation = 0.03

    if mode == "Pricing":
        with st.expander("3. Caractéristiques du Produit Structuré (Payoff)", expanded=True):
            col_p1, col_p2, col_p3 = st.columns(3)
            with col_p1:
                type_produit = st.selectbox("Type de Produit Structuré", ["Athéna", "Phoenix"], key="st_type_produit")
                barriere_rappel_pct = st.number_input("Barrière de Rappel Anticipé (%)", value=100.0, step=5.0, key="st_b_rappel") / 100.0
            with col_p2:
                niveau_pdi_pct = st.number_input("Barrière de Protection du Capital PDI (%)", value=50.0, step=5.0, key="st_pdi") / 100.0
                coupon_periode = st.number_input("Coupon par observation (%)", value=2.0, step=0.1, key="st_coupon")
            with col_p3:
                frequence_obs_mois = st.number_input("Fréquence d'observation (mois)", value=3, min_value=1, max_value=12, step=1, key="st_freq")
                non_call_period_mois = st.number_input("Période de Non-Call (mois)", value=12, min_value=0, step=1, key="st_non_call")

            col_p4, col_p5 = st.columns(2)
            with col_p4:
                degressivite = st.number_input("Dégressivité du rappel (% par observation)", value=0.0, step=0.5, key="st_degres")
            with col_p5:
                if type_produit == "Phoenix":
                    barriere_coupon_pct = st.number_input("Barrière de Coupon (%)", value=70.0, step=5.0, key="st_b_coup") / 100.0
                    avec_memoire = st.checkbox("Effet Mémoire des Coupons", value=True, key="st_memoire")
                else:
                    barriere_coupon_pct = None
                    avec_memoire = True

    # -------------------------------------------------------------------------
    # 4. PARAMÈTRES AVANCÉS DU MOTEUR (Replié par défaut)
    # -------------------------------------------------------------------------
    with st.expander("Paramètres avancés de simulation", expanded=False):
        c_sim1, c_sim2, c_sim3 = st.columns(3)
        with c_sim1:
            nb_trajectoires = st.number_input("Nombre de trajectoires Monte Carlo", value=10000, min_value=1000, max_value=50000, step=1000, key="st_nb_traj")
        with c_sim2:
            seed = st.number_input("Graine aléatoire (Seed)", value=42, step=1, key="st_seed")
        with c_sim3:
            if mode == "Pricing":
                taux_act_pct = st.number_input("Taux sans risque d'actualisation (%)", value=3.0, step=0.25, key="st_tx_act")
                taux_actualisation = taux_act_pct / 100.0

    st.markdown("<div style='margin-bottom: 10px;'></div>", unsafe_allow_html=True)
    btn_label = "Lancer la Simulation de Trajectoires" if mode == "Comparaison Trajectoires" else "Lancer la Valorisation du Produit"
    lancer = st.button(btn_label, type="primary", use_container_width=True, key="st_btn_launch")

    # -------------------------------------------------------------------------
    # 5. EXÉCUTION DE LA SIMULATION & RENDUS GRAPHIQUES
    # -------------------------------------------------------------------------
    if lancer:
        if somme_annees != int(annees):
            st.error(f"Incohérence : la somme des durées de régimes ({somme_annees} ans) doit être égale à la durée totale ({int(annees)} ans).")
            return

        moteur = SimulationEngine(nb_trajectoires=int(nb_trajectoires), seed=int(seed))
        scenario_krach = MarketScenario(config_regimes=mes_regimes_input, annees=int(annees))

        # --- A. MODE COMPARAISON TRAJECTOIRES ---
        if mode == "Comparaison Trajectoires":
            with st.spinner(f"Génération de {int(nb_trajectoires):,} trajectoires Monte Carlo vectorisées..."):
                results_multi = moteur.simulate_multi_indices(liste_indices, scenario_krach)

                st.markdown(f"<div class='section-title'>Indicateurs Clés à Maturité (Année {scenario_krach.annees})</div>", unsafe_allow_html=True)

                data_macro = []
                for nom_idx, d in results_multi.items():
                    data_macro.append({
                        "Indice": nom_idx,
                        "Spot Initial S0": f"{d['index'].niveau_initial:.2f} pts",
                        "Décrément Annuel": f"{d['index'].decrement_annuel:.2f} pts",
                        "Volatilité": f"{d['index'].vol*100:.1f} %",
                        "Dividende Réinvesti": f"{d['index'].dividend_yield*100:.2f} %",
                        "Niveau Final Décrément": f"{d['moy_dec']:.1f} pts ({d['moy_dec_pct']:+.1f} %)",
                        "Niveau Final Price Return": f"{d['moy_pr']:.1f} pts ({d['moy_pr_pct']:+.1f} %)",
                        "Écart Moyen (Dec - PR)": f"{d['ecart_moy_pct']:+.2f} % ({d['ecart_moy_pts']:+.1f} pts)",
                        "Risque Crash < 50%": f"{d['pct_crash_50_dec']:.1f} % (vs {d['pct_crash_50_pr']:.1f} % PR)"
                    })
                st.dataframe(pd.DataFrame(data_macro), use_container_width=True, hide_index=True)

                st.divider()

                # Graphique 1 : Trajectoires Médianes
                st.markdown("<div class='section-title'>1. Trajectoires Médianes & Fuseaux Inter-centiles [P10 - P90]</div>", unsafe_allow_html=True)
                st.caption("Évolution comparée des indices normalisés en % de S0 sur la même matrice de tirages aléatoires.")
                fig_multi_traj = moteur.plot_multi_trajectoires(results_multi, scenario_krach)
                st.plotly_chart(fig_multi_traj, use_container_width=True, config={'displayModeBar': False})

                st.divider()

                # Graphique 2 : Dynamique temporelle des écarts
                st.markdown("<div class='section-title'>2. Dynamique Temporelle des Écarts (Décrément - Price Return)</div>", unsafe_allow_html=True)
                st.caption("Médiane en trait plein et couloir interquartile [Q25 - Q75] en voile pour chaque indice au fil des ans.")
                fig_multi_ecarts = moteur.plot_multi_courbes_ecarts(results_multi, scenario_krach, filter_active=False)
                st.plotly_chart(fig_multi_ecarts, use_container_width=True, config={'displayModeBar': False})

                st.divider()

                # Graphique 3 : Dispersion des écarts à maturité
                st.markdown("<div class='section-title'>3. Dispersion Comparée des Écarts à Maturité</div>", unsafe_allow_html=True)
                st.caption("Distribution de l'écart (Dec - PR) / S0 à maturité bornée entre les centiles P1 et P99.")
                fig_multi_disp = moteur.plot_multi_dispersion_ecarts(results_multi, scenario_krach)
                st.plotly_chart(fig_multi_disp, use_container_width=True, config={'displayModeBar': False})

        # --- B. MODE PRICING DE PRODUITS STRUCTURÉS ---
        elif mode == "Pricing":
            with st.spinner(f"Valorisation financière du produit ({int(nb_trajectoires):,} trajectoires appariées)..."):
                ref_s0 = 1000.0
                barriere_rappel = ref_s0 * barriere_rappel_pct
                niveau_pdi = ref_s0 * niveau_pdi_pct

                if type_produit == "Athéna":
                    mon_produit = AthenaProduct(
                        barriere_rappel=barriere_rappel,
                        niveau_pdi=niveau_pdi,
                        non_call_period_mois=int(non_call_period_mois),
                        frequence_obs_mois=int(frequence_obs_mois),
                        degressivite=float(degressivite),
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
                        coupon_periode=float(coupon_periode),
                        avec_memoire=avec_memoire,
                        ref_s0=ref_s0
                    )

                results_multi_pricing = moteur.run_multi_indices(
                    liste_indices, scenario_krach, mon_produit, taux_actualisation=taux_actualisation
                )

                memoire_str = " (Mémoire)" if (type_produit == "Phoenix" and avec_memoire) else (" (Sans Mémoire)" if type_produit == "Phoenix" else "")
                st.markdown(f"<div class='section-title'>Indicateurs de Performance et de Risque : {type_produit}{memoire_str}</div>", unsafe_allow_html=True)

                data_pricing = []
                for nom_idx, d in results_multi_pricing.items():
                    lev_str = f"{d['levier_equivalent']:.2f}x" if d['levier_equivalent'] is not None else "N/A"
                    data_pricing.append({
                        "Indice": nom_idx,
                        "Taux d'Autocall Global": f"{d['pct_rappel_dec']:.1f} % (vs {d['pct_rappel_pr']:.1f} % PR)",
                        "Espérance de Gain Annuelle": f"{d['moy_payoff_dec']:.2f} % (vs {d['moy_payoff_pr']:.2f} % PR)",
                        "Duration Espérée": f"{d['duration_dec']:.2f} ans (vs {d['duration_pr']:.2f} ans PR)",
                        "Probabilité sous PDI (Perte)": f"{d['pct_pdi_dec']:.2f} % (vs {d['pct_pdi_pr']:.2f} % PR)",
                        "Levier de Krach vs PR": lev_str
                    })
                st.dataframe(pd.DataFrame(data_pricing), use_container_width=True, hide_index=True)

                st.divider()

                # Graphique 1 : Indicateurs comparés de performance et risque
                st.markdown("<div class='section-title'>1. Indicateurs Comparés de Performance et de Risque</div>", unsafe_allow_html=True)
                fig_kpis = moteur.plot_multi_pricing_kpis(results_multi_pricing)
                st.plotly_chart(fig_kpis, use_container_width=True, config={'displayModeBar': False})

                st.divider()

                # Graphique 2 : Distribution comparée des dates de rappel
                st.markdown("<div class='section-title'>2. Distribution Comparée des Dates de Rappel Anticipé</div>", unsafe_allow_html=True)
                fig_rappels = moteur.plot_multi_pricing_rappels(results_multi_pricing, scenario_krach, mon_produit)
                st.plotly_chart(fig_rappels, use_container_width=True, config={'displayModeBar': False})

                st.divider()

                # Graphique 3 : Écarts sur trajectoires non rappelées
                st.markdown("<div class='section-title'>3. Dynamique Temporelle des Écarts sur Trajectoires Non Rappelées</div>", unsafe_allow_html=True)
                st.caption("Écart subi par un investisseur encore investi dans le produit (médiane et couloir [Q25 - Q75]).")
                fig_multi_ecarts_pricing = moteur.plot_multi_courbes_ecarts(
                    results_multi_pricing, scenario_krach, filter_active=True, product=mon_produit
                )
                st.plotly_chart(fig_multi_ecarts_pricing, use_container_width=True, config={'displayModeBar': False})

                st.divider()

                # Graphique 4 : Dispersion à maturité
                st.markdown("<div class='section-title'>4. Dispersion Comparée des Écarts à Maturité</div>", unsafe_allow_html=True)
                st.caption("Distribution de l'écart (Dec - PR) / S0 à maturité bornée entre les centiles P1 et P99.")
                fig_disp_pricing = moteur.plot_multi_dispersion_ecarts(results_multi_pricing, scenario_krach)
                st.plotly_chart(fig_disp_pricing, use_container_width=True, config={'displayModeBar': False})
    else:
        st.info("Ajustez les paramètres du scénario et de l'indice ci-dessus, puis cliquez sur le bouton pour lancer la simulation.")

