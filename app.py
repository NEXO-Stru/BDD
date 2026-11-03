import streamlit as st
import numpy as np
import io
import contextlib
import plotly.graph_objects as go
import pandas as pd
import monte_carlo_2
import importlib

importlib.reload(monte_carlo_2)
from monte_carlo_2 import MarketScenario, DecrementIndex, AutocallProduct, AthenaProduct, PhoenixProduct, SimulationEngine

st.set_page_config(page_title="Simulateur Monte Carlo : Stress Test Indice & Pricing Autocall", layout="wide")

# --- SIDEBAR ---
mode = st.sidebar.radio("Module", ["Comparaison Trajectoires", "Pricing"])
st.sidebar.divider()

st.sidebar.header("Paramètres")

with st.sidebar.expander("1. Durée", expanded=True):
    annees = st.number_input("Années totales", value=10, min_value=1, step=1)

with st.sidebar.expander("2. Configuration des Périodes", expanded=True):
    nb_periodes = st.number_input("Nombre de Périodes", value=1, min_value=1, step=1)
    
    mes_regimes_input = []
    somme_annees = 0
    for i in range(int(nb_periodes)):
        st.markdown(f"**Période {i+1}**")
        def_d = 10 if i == 0 else (2 if i == 1 else 5)
        def_rp = 0.0 if i == 0 else (-15.0 if i == 1 else 5.0)
        def_vol = 18.0 if i == 0 else (35.0 if i == 1 else 18.0)
        def_yi = 3.0 if i == 0 else (1.0 if i == 1 else 4.0)
        
        d = st.number_input(f"Durée (ans) P{i+1}", value=def_d, min_value=1, key=f"d_pct_{i}")
        rp = st.number_input(f"Drift Price Return P{i+1} (%)", value=def_rp, format="%.1f", key=f"rp_pct_{i}")
        vol = st.number_input(f"Volatilité P{i+1} (%)", value=def_vol, format="%.1f", key=f"vol_pct_{i}")
        yi = st.number_input(f"Yield Div Naturel P{i+1} (%)", value=def_yi, format="%.2f", key=f"yi_pct_{i}")
        st.divider()
        
        somme_annees += d
        mes_regimes_input.append({
            "duree_annees": int(d),
            "r_perf": rp / 100.0,
            "vol": vol / 100.0,
            "yield_initial": yi / 100.0
        })

with st.sidebar.expander("3. Indice Decrement", expanded=True):
    niveau_initial = st.number_input("Niveau Initial (pts)", value=1000.0, step=100.0)
    decrement_annuel = st.number_input("Décrément Fixe Annuel (pts)", value=50.0, step=5.0)

if mode == "Pricing":
    with st.sidebar.expander("4. Produit Structuré", expanded=True):
        type_produit = st.selectbox("Type de Produit", ["Athéna", "Phoenix"])
        st.caption("Les barrières sont exprimées en pourcentage du niveau initial.")
        barriere_rappel_pct = st.number_input("Barrière Rappel (%)", value=100.0, step=10.0) / 100.0
        
        if type_produit == "Phoenix":
            barriere_coupon_pct = st.number_input("Barrière Coupon (%)", value=70.0, step=5.0) / 100.0
            avec_memoire = st.checkbox("Effet Mémoire des Coupons", value=True)
        else:
            barriere_coupon_pct = None
            avec_memoire = True
            
        niveau_pdi_pct = st.number_input("Niveau PDI (%)", value=50.0, step=10.0) / 100.0
        degressivite = st.number_input("Dégressivité de Rappel (%/obs)", value=0.0, step=1.0, 
                                        help="Baisse de la barrière en points à chaque constatation après la période de non-call.")
        coupon_periode = st.number_input("Coupon par observation (%)", value=2.0, step=0.1)
        non_call_period_mois = st.number_input("Période de Non-Call (mois)", value=11, step=1)
        frequence_obs_mois = st.number_input("Fréquence d'observation (mois)", value=3, step=1)

with st.sidebar.expander("5. Moteur de Simulation", expanded=False):
    nb_trajectoires = st.number_input("Nombre de Trajectoires", value=10000, step=1000)
    seed = st.number_input("Seed aléatoire", value=42, step=1)
    if mode == "Pricing":
        taux_actualisation_pct = st.number_input("Taux d'actualisation (%)", value=3.0, step=0.1)
        taux_actualisation = taux_actualisation_pct / 100.0
    else:
        taux_actualisation = 0.0

btn_text = "Lancer la Simulation d'Indices" if mode == "Comparaison Trajectoires" else "Lancer le Pricing"
lancer = st.sidebar.button(btn_text, type="primary", use_container_width=True)

# --- MAIN AREA ---
st.title(f"Simulateur Monte Carlo : {mode}")

if lancer:
    if somme_annees != annees:
        st.error(f"Incohérence : la somme des durées des régimes ({somme_annees} ans) doit être égale au total d'années ({annees} ans).")
    else:
        moteur = SimulationEngine(nb_trajectoires=int(nb_trajectoires), seed=int(seed))
        scenario_krach = MarketScenario(config_regimes=mes_regimes_input, annees=int(annees))
        mon_indice_dec = DecrementIndex(niveau_initial=niveau_initial, decrement_annuel=decrement_annuel)

        if mode == "Comparaison Trajectoires":
            with st.spinner(f"Génération de {int(nb_trajectoires)} trajectoires pour l'indice Price Return et Décrément..."):
                traj_pr, traj_dec = moteur.simulate_trajectoires(mon_indice_dec, scenario_krach)
                
                # Métriques macro de l'indice
                valeurs_finales_dec = traj_dec[:, -1]
                valeurs_finales_pr = traj_pr[:, -1]
                moy_dec = np.mean(valeurs_finales_dec)
                moy_pr = np.mean(valeurs_finales_pr)
                ecart_moy_pts = moy_dec - moy_pr
                ecart_moy_pct = (ecart_moy_pts / niveau_initial) * 100.0
                pct_crash_50_dec = np.mean(valeurs_finales_dec < 0.50 * niveau_initial) * 100.0
                pct_crash_50_pr = np.mean(valeurs_finales_pr < 0.50 * niveau_initial) * 100.0
                
                st.subheader("Indicateurs Clés de Marché & Dérive d'Indice à Maturité")
                c1, c2, c3, c4 = st.columns(4)
                c1.metric("Niveau Moyen PR", f"{moy_pr:.1f} pts", f"{(moy_pr/niveau_initial - 1.0)*100:+.1f}% vs Spot")
                c2.metric("Niveau Moyen Décrément", f"{moy_dec:.1f} pts", f"{(moy_dec/niveau_initial - 1.0)*100:+.1f}% vs Spot")
                c3.metric("Écart Moyen (Dec - PR)", f"{ecart_moy_pct:+.2f}% du Spot", f"{ecart_moy_pts:+.1f} pts")
                c4.metric("Probabilité Fin < 50% du Spot", f"{pct_crash_50_dec:.1f}% (Dec)", f"vs {pct_crash_50_pr:.1f}% (PR)", delta_color="inverse")
                
                st.markdown("---")
                
                # 1. Trajectoires Centiles
                st.subheader("1. Trajectoires Temporelles des Indices par Centiles (Top 10% à 90%)")
                st.caption("Évolution comparée du Price Return et du Décrément sur les mêmes chocs aléatoires.")
                _, fig_centiles = moteur.plot_results(
                    f"Trajectoires Comparées (Spot {niveau_initial:.0f})", 
                    traj_pr, traj_dec, reps_scen=[], product=None, scenario=scenario_krach, index=mon_indice_dec
                )
                st.plotly_chart(fig_centiles, use_container_width=True)
                
                st.markdown("---")
                
                # 2. Dispersion des écarts (Violons)
                st.subheader("2. Dispersion des Écarts (Décrément - Price Return) par Année")
                fig_violins_ecart, stats_disp = moteur.plot_dispersion_ecarts_violons(
                    traj_pr, traj_dec, scenario_krach, niveau_initial=niveau_initial, return_stats=True
                )
                st.plotly_chart(fig_violins_ecart, use_container_width=True)
                
                with st.expander("Consulter le tableau quantitatif détaillé des écarts par année (Médiane, Moyenne, Quartiles)", expanded=False):
                    df_disp = pd.DataFrame(stats_disp)
                    df_disp_display = pd.DataFrame({
                        "Horizon": df_disp["Année"],
                        "Médiane (Dec - PR)": df_disp["Médiane"].apply(lambda v: f"{v:+.2f}%"),
                        "Moyenne (Dec - PR)": df_disp["Moyenne"].apply(lambda v: f"{v:+.2f}%"),
                        "25e centile (Q1)": df_disp["Q25"].apply(lambda v: f"{v:+.2f}%"),
                        "75e centile (Q3)": df_disp["Q75"].apply(lambda v: f"{v:+.2f}%"),
                        "Écart interquartile (IQR)": df_disp["IQR"].apply(lambda v: f"{v:.2f}%"),
                        "Écart Min": df_disp["Min"].apply(lambda v: f"{v:+.2f}%"),
                        "Écart Max": df_disp["Max"].apply(lambda v: f"{v:+.2f}%"),
                    })
                    st.dataframe(df_disp_display, use_container_width=True)
                    
                st.markdown("---")
                
                # 3. Distributions globales
                st.subheader("3. Distributions des Niveaux Finaux à Maturité")
                fig_dist_dec, fig_dist_pr, _, _, _ = moteur.plot_distributions(
                    traj_pr, traj_dec, product=None, scenario=scenario_krach
                )
                col_d1, col_d2 = st.columns(2)
                with col_d1:
                    st.plotly_chart(fig_dist_dec, use_container_width=True)
                with col_d2:
                    st.plotly_chart(fig_dist_pr, use_container_width=True)

        elif mode == "Pricing":
            with st.spinner(f"Simulation de {int(nb_trajectoires)} trajectoires et valorisation du contrat en cours..."):
                barriere_rappel = niveau_initial * barriere_rappel_pct
                niveau_pdi = niveau_initial * niveau_pdi_pct
                
                if type_produit == "Athéna":
                    mon_produit = AthenaProduct(
                        barriere_rappel=barriere_rappel,
                        niveau_pdi=niveau_pdi,
                        non_call_period_mois=int(non_call_period_mois),
                        frequence_obs_mois=int(frequence_obs_mois),
                        degressivite=float(degressivite),
                        coupon_periode=float(coupon_periode)
                    )
                else:
                    barriere_coupon = niveau_initial * barriere_coupon_pct
                    mon_produit = PhoenixProduct(
                        barriere_rappel=barriere_rappel,
                        barriere_coupon=barriere_coupon,
                        niveau_pdi=niveau_pdi,
                        non_call_period_mois=int(non_call_period_mois),
                        frequence_obs_mois=int(frequence_obs_mois),
                        degressivite=float(degressivite),
                        coupon_periode=float(coupon_periode),
                        avec_memoire=avec_memoire
                    )
                
                traj_pr, traj_dec, est_rappele_dec, obs_de_rappel_dec, payoffs_dec, est_rappele_pr, obs_de_rappel_pr, payoffs_pr = moteur.run(
                    mon_indice_dec, scenario_krach, mon_produit, taux_actualisation=taux_actualisation
                )
                
                duration_dec = moteur.calculer_duration(est_rappele_dec, obs_de_rappel_dec, mon_produit, scenario_krach)
                duration_pr = moteur.calculer_duration(est_rappele_pr, obs_de_rappel_pr, mon_produit, scenario_krach)
                
                memoire_str = " (Mémoire)" if (type_produit == "Phoenix" and avec_memoire) else (" (Sans Mémoire)" if type_produit == "Phoenix" else "")
                nom_scenario = f"Pricing {type_produit}{memoire_str} (Spot {niveau_initial:.0f})"
                f = io.StringIO()
                with contextlib.redirect_stdout(f):
                    reps_scen, bin_stats, levier_equivalent = moteur.afficher_statistiques(
                        nom_scenario, traj_pr, traj_dec, est_rappele_dec, payoffs_dec, est_rappele_pr, payoffs_pr, mon_produit, scenario_krach
                    )
                stats_text = f.getvalue()
                
                pct_rappel_dec = np.mean(est_rappele_dec) * 100.0
                pct_rappel_pr = np.mean(est_rappele_pr) * 100.0
                moy_payoff_dec = np.mean(payoffs_dec) * 100.0
                moy_payoff_pr = np.mean(payoffs_pr) * 100.0
                
                valeurs_finales_dec = traj_dec[:, -1]
                valeurs_finales_pr = traj_pr[:, -1]
                en_dessous_pdi_dec = (valeurs_finales_dec < mon_produit.niveau_pdi) & (~est_rappele_dec)
                en_dessous_pdi_pr = (valeurs_finales_pr < mon_produit.niveau_pdi) & (~est_rappele_pr)
                pct_pdi_dec = np.mean(en_dessous_pdi_dec) * 100.0
                pct_pdi_pr = np.mean(en_dessous_pdi_pr) * 100.0
                
                st.subheader(f"Indicateurs de Performance et de Risque : {type_produit}{memoire_str}")
                kp1, kp2, kp3, kp4, kp5 = st.columns(5)
                kp1.metric("Duration Espérée", f"{duration_dec:.2f} ans", f"vs {duration_pr:.2f} ans (PR)", delta_color="inverse")
                kp2.metric("Taux d'Autocall", f"{pct_rappel_dec:.1f}%", f"{pct_rappel_dec - pct_rappel_pr:+.1f}% vs PR")
                kp3.metric("Espérance de Gain", f"{moy_payoff_dec:.2f}%", f"{moy_payoff_dec - moy_payoff_pr:+.2f}% vs PR")
                kp4.metric("Probabilité sous PDI", f"{pct_pdi_dec:.2f}%", f"{pct_pdi_dec - pct_pdi_pr:+.2f}% vs PR", delta_color="inverse")
                levier_label = f"{levier_equivalent:.2f}x" if levier_equivalent is not None else "N/A"
                kp5.metric(
                    "Levier Krach vs PR", levier_label, 
                    help="Multiplicateur de perte du Décrément par rapport au Price Return en cas de franchissement de PDI."
                )
                
                st.markdown("---")
                
                # 1. Dates de rappel
                st.subheader("1. Distribution des Dates de Rappel Anticipé")
                fig_dist_dec, fig_dist_pr, fig_dist_rappel, fig_dist_dec_reelle, fig_dist_pr_reelle = moteur.plot_distributions(
                    traj_pr, traj_dec, est_rappele_pr, est_rappele_dec, mon_produit, scenario_krach
                )
                st.plotly_chart(fig_dist_rappel, use_container_width=True)
                
                st.markdown("---")
                
                # 2. Trajectoires sous PDI
                st.subheader("2. Trajectoires Critiques sous PDI")
                fig1, _ = moteur.plot_results(
                    nom_scenario, traj_pr, traj_dec, reps_scen, mon_produit, scenario_krach, mon_indice_dec
                )
                if len(reps_scen) > 0:
                    st.plotly_chart(fig1, use_container_width=True)
                else:
                    st.info("Aucune trajectoire ne finit en dessous du PDI à maturité dans cette simulation.")
                    
                st.markdown("---")
                
                # 3. Analyse détaillée de Krach
                st.subheader("3. Analyse de Sévérité du Krach sous PDI")
                if bin_stats:
                    fig_binned = moteur.plot_binned_averages(bin_stats)
                    st.plotly_chart(fig_binned, use_container_width=True)
                    
                col_r1, col_r2 = st.columns(2)
                with col_r1:
                    st.plotly_chart(fig_dist_dec_reelle, use_container_width=True)
                with col_r2:
                    st.plotly_chart(fig_dist_pr_reelle, use_container_width=True)
                    
                with st.expander("Consulter le détail textuel des statistiques de rappel et de PDI", expanded=False):
                    st.markdown(stats_text)

else:
    st.info("Ajustez les paramètres dans la barre latérale gauche, puis cliquez sur le bouton pour lancer le calcul.")
