# -*- coding: utf-8 -*-
"""
Moteur Quantitatif de Backtest Historique pour Produits Structurés (Autocall / Phoenix / Athena)
Issu et unifié des codes historiques de Nexo Capital (Guillaume Feigna, Pauline Urvoas, Thibault).

Conserve 100% des algorithmes, formules mathématiques et payoffs d'origine :
  - Mécanismes de Strike : Standard (t0), Lookback Min (strike au plus bas), Lookback Moyenne (Asian).
  - Profils de Dégressivité : Linéaire, Paliers, Annuel, Trimestrielle ou Profil sur-mesure.
  - Sélection sous-jacent : Worst-of, Médiane, Panier équipondéré.
  - Coupons : Effet Mémoire, Garanti ou Conditionnel simple.
  - Échéance : Barrière PDI (capital à risque), Effet Oxygène et Certificat de participation plafonné.
  - 100% compatible Pandas 3.0+ / NumPy 2.0+ et support de l'export Excel en mémoire (io.BytesIO).
"""

import os
import io
import math
import time
import datetime
from calendar import monthrange
from dateutil.relativedelta import relativedelta

import pandas as pd
import numpy as np


class StructuredProductBacktest:
    """
    Simulateur glissant quotidien (rolling backtest) de produits structurés dérivés actions.
    Prend en entrée une matrice historique de cours (DataFrame ou fichier Excel/CSV).
    """

    def __init__(
        self,
        # Données d'entrée (DataFrame ou chemin de fichier)
        input_data,
        sheet_name=0,
        output_file=None,
        # Caractéristiques du produit
        worst_of=1,
        mediane=0,
        certificat_participation=0,
        cap=1000000,
        duree_vie=5,
        memoire=1,
        garanti=0,
        from_redempt=1,
        from_coupon=1,
        barriere_coupon=100.0,
        barriere_rappel=100.0,
        coupon=2.0,
        pdi=50.0,
        oxygen=100000.0,
        coupon_oxygene=1.0,
        freq_obs=0.25,  # Trimestriel par défaut
        remboursement_value=100.0,
        duree_analyse=20,
        # Dégressivité de la barrière de rappel
        degressivite_mode='lineaire',  # 'lineaire', 'palier', 'annuelle', 'trimestrielle', 'custom'
        degressivite_rappel=0.0,
        degressivite_coupon=0.0,
        degressivite_rappel_ann=0.0,
        degressivite_rappel_trim=0.0,
        i_floor_degr=100,
        barrieres_rappel_custom=None,
        # Mécanisme de Strike (Lookback)
        strike_type='standard',  # 'standard', 'lookback_min', 'lookback_moy'
        nb_dates_min=1,
        freq_min=1,
        nb_dates_moy=1,
        freq_moy=1,
    ):
        self.input_data = input_data
        self.sheet_name = sheet_name
        self.output_file = output_file

        # Paramètres produit
        self.worst_of = worst_of
        self.mediane = mediane
        self.certificat_participation = certificat_participation
        self.cap = cap
        self.duree_vie = duree_vie
        self.memoire = memoire
        self.garanti = garanti
        self.from_redempt = from_redempt
        self.from_coupon = from_coupon
        self.barriere_coupon = float(barriere_coupon)
        self.barriere_rappel = float(barriere_rappel)
        self.coupon = float(coupon)
        self.pdi = float(pdi)
        self.oxygen = float(oxygen)
        self.coupon_oxygene = float(coupon_oxygene)
        self.freq_obs = float(freq_obs)
        self.remboursement_value = float(remboursement_value)
        self.duree_analyse = duree_analyse

        # Dégressivité
        self.degressivite_mode = degressivite_mode
        self.degressivite_rappel = float(degressivite_rappel)
        self.degressivite_coupon = float(degressivite_coupon)
        self.degressivite_rappel_ann = float(degressivite_rappel_ann)
        self.degressivite_rappel_trim = float(degressivite_rappel_trim)
        self.i_floor_degr = i_floor_degr
        self.barrieres_rappel_custom = barrieres_rappel_custom

        # Strike / Lookback
        self.strike_type = strike_type
        self.nb_dates_min = int(nb_dates_min)
        self.freq_min = int(freq_min)
        self.nb_dates_moy = int(nb_dates_moy)
        self.freq_moy = int(freq_moy)

        # Conteneurs de calcul
        self.histo = None
        self.histo_perf = None
        self.strike_perf = None
        self.dates_obs = None
        self.perf_obs = None
        self.worst = None
        self.early_redemption = None
        self.coupon_payment = None
        self.perf_benchmark = None
        self.breakdown = None
        self.analysis = None
        self.analysis_noncalled = None
        self.performance_summary = None
        self.excel_bytes = None

    def _load_data(self):
        """Normalise l'historique des cours."""
        if isinstance(self.input_data, pd.DataFrame):
            histo = self.input_data.copy()
            if not isinstance(histo.index, pd.DatetimeIndex):
                if 'DATES' in histo.columns:
                    histo = histo.rename(columns={'DATES': 'DATES'})
                    histo['DATES'] = pd.to_datetime(histo['DATES'], dayfirst=True)
                    histo = histo.set_index('DATES')
                elif 'Dates' in histo.columns:
                    histo['Dates'] = pd.to_datetime(histo['Dates'], dayfirst=True)
                    histo = histo.set_index('Dates')
                elif 'date' in histo.columns:
                    histo['date'] = pd.to_datetime(histo['date'])
                    histo = histo.set_index('date')
                else:
                    histo = histo.rename(columns={histo.columns[0]: 'DATES'})
                    histo['DATES'] = pd.to_datetime(histo['DATES'], dayfirst=True)
                    histo = histo.set_index('DATES')
        elif isinstance(self.input_data, str):
            if self.input_data.endswith('.csv'):
                try:
                    histo = pd.read_csv(self.input_data, sep=';')
                except Exception:
                    histo = pd.read_csv(self.input_data)
            else:
                histo = pd.read_excel(self.input_data, sheet_name=self.sheet_name)
            histo = histo.rename(columns={histo.columns[0]: "DATES"})
            histo = histo.dropna(axis=0, how='any')
            histo['DATES'] = pd.to_datetime(histo['DATES'], dayfirst=True)
            histo = histo.set_index('DATES')
        else:
            raise ValueError("input_data doit être un DataFrame pandas ou un chemin valide.")

        histo = histo.dropna(axis=0, how='any')
        histo = histo.sort_index()
        self.histo = histo
        return histo

    def _compute_strike_reference(self):
        """
        Calcule les niveaux de strike : Standard (t0), Lookback Min ou Lookback Moyen.
        Formules exactes de backtest_lookbackmin et backtest_lookbackmoy.
        """
        histo = self.histo

        if self.strike_type == 'lookback_min' and self.nb_dates_min > 1:
            offset = (self.nb_dates_min - 1) * self.freq_min
            histo_perf = histo.iloc[offset:].copy()
            mindex = list(histo_perf.index)

            str_min = pd.DataFrame(columns=list(range(int(self.nb_dates_min) * len(histo.columns))), index=mindex)
            for i in str_min.columns:
                stock_idx = int(i / self.nb_dates_min)
                shift = self.freq_min * (self.nb_dates_min - 1 - (i % self.nb_dates_min))
                for j in range(len(mindex)):
                    str_min.iloc[j, i] = histo.iloc[j + shift, stock_idx]

            strike_perf = histo_perf.copy()
            for j in strike_perf.index:
                for k in range(len(histo.columns)):
                    listmin = []
                    for i in range(self.nb_dates_min * k, self.nb_dates_min * (k + 1)):
                        listmin.append(str_min.loc[j][i])
                    col_name = strike_perf.columns[k]
                    strike_perf.at[j, col_name] = min(listmin)

            self.histo_perf = histo_perf
            self.strike_perf = strike_perf

        elif self.strike_type == 'lookback_moy' and self.nb_dates_moy > 1:
            offset = (self.nb_dates_moy - 1) * self.freq_moy
            histo_perf = histo.iloc[offset:].copy()
            mindex = list(histo_perf.index)

            str_moy = pd.DataFrame(columns=list(range(int(self.nb_dates_moy) * len(histo.columns))), index=mindex)
            for i in str_moy.columns:
                stock_idx = int(i / self.nb_dates_moy)
                shift = self.freq_moy * (self.nb_dates_moy - 1 - (i % self.nb_dates_moy))
                for j in range(len(mindex)):
                    str_moy.iloc[j, i] = histo.iloc[j + shift, stock_idx]

            strike_perf = histo_perf.copy()
            for j in strike_perf.index:
                for k in range(len(histo.columns)):
                    listmoy = []
                    for i in range(self.nb_dates_moy * k, self.nb_dates_moy * (k + 1)):
                        listmoy.append(str_moy.loc[j][i])
                    col_name = strike_perf.columns[k]
                    strike_perf.at[j, col_name] = np.mean(listmoy)

            self.histo_perf = histo_perf
            self.strike_perf = strike_perf

        else:
            self.histo_perf = histo.copy()
            self.strike_perf = histo.copy()

    def _compute_observation_dates(self):
        """
        Calcule les dates d'observation futures pour chaque jour de départ.
        Utilise monthrange et binary search pour concilier exactitude de calendrier et vitesse.
        """
        nb_periods = int(self.duree_vie / self.freq_obs)
        dates_obs = pd.DataFrame(columns=list(range(1, nb_periods + 1)), index=self.histo_perf.index)
        worst = pd.DataFrame(columns=list(range(1, nb_periods + 1)), index=self.histo_perf.index)
        perf_benchmark = pd.DataFrame(columns=['Perf'], index=self.histo_perf.index)

        full_index = self.histo.index

        for i in range(1, nb_periods + 1):
            month_step = int(self.freq_obs * 12 * i)
            for j in dates_obs.index:
                try:
                    total_months = j.month + month_step - 1
                    add_year = j.year + int(total_months / 12)
                    add_month = int(total_months % 12 + 1)
                    max_day = monthrange(add_year, add_month)[1]
                    cur_day = j.day
                    add_day = min([0, max_day - cur_day])

                    target_date = datetime.datetime(add_year, add_month, cur_day + add_day)
                    pos = full_index.searchsorted(target_date)
                    if pos < len(full_index):
                        dates_obs.at[j, i] = full_index[pos]
                except Exception:
                    continue

        self.dates_obs = dates_obs
        self.worst = worst
        self.perf_benchmark = perf_benchmark

    def _compute_performances_at_observations(self):
        """
        Calcule la performance du sous-jacent (Worst-of, Médiane ou Panier).
        Formule d'origine : (P_obs / P_strike - 1) * 100
        """
        nb_periods = int(self.duree_vie / self.freq_obs)
        perf_obs = pd.DataFrame(columns=list(range(1, nb_periods + 1)), index=self.histo_perf.index)

        histo = self.histo
        strike_perf = self.strike_perf
        dates_obs = self.dates_obs
        worst = self.worst

        for i in worst.columns:
            for j in dates_obs.index:
                try:
                    obs_date = dates_obs.loc[j, i]
                    if pd.isnull(obs_date):
                        break

                    val = []
                    for k in histo.columns:
                        p_obs = float(histo.loc[obs_date, k])
                        p_strike = float(strike_perf.loc[j, k])
                        val.append(((p_obs / p_strike) - 1.0) * 100.0)

                    if self.worst_of:
                        perf_obs.at[j, i] = min(val)
                        worst.at[j, i] = histo.columns[val.index(min(val))]
                    elif self.mediane:
                        med_val = float(np.median(val))
                        perf_obs.at[j, i] = med_val
                        worst.at[j, i] = histo.columns[val.index(med_val)]
                    else:
                        perf_obs.at[j, i] = float(np.mean(val))
                        worst.at[j, i] = "Panier"
                except Exception:
                    break

        self.perf_obs = perf_obs

    def _get_autocall_barrier(self, i):
        """Définit la dégressivité à la période i selon la formule d'origine."""
        mode = self.degressivite_mode
        if mode == 'palier' or mode == 'daily':
            return max(math.floor((i - 2) / 2) * 4, 0)
        elif mode == 'annuelle':
            if i > (self.from_redempt * 2 - 1):
                ann = min(int(i * self.freq_obs) - 1, self.i_floor_degr)
            else:
                ann = 0
            return self.degressivite_rappel_ann * ann
        elif mode == 'trimestrielle':
            if i > 14:
                trim = int((i - 12) / 3)
            else:
                trim = 0
            return self.degressivite_rappel_trim * trim
        elif mode == 'custom' and self.barrieres_rappel_custom is not None:
            idx = i - 1
            if idx < len(self.barrieres_rappel_custom):
                return 100 - (self.barrieres_rappel_custom[idx] - self.barriere_rappel + 100)
            return 0.0
        else:
            return self.degressivite_rappel * i

    def _simulate_lifecycle(self):
        """Simulation exacte des flux : rappel anticipé, coupons, et règlement final."""
        nb_periods = int(self.duree_vie / self.freq_obs)
        perf_obs = self.perf_obs
        dates_obs = self.dates_obs

        early_redemption = pd.DataFrame(columns=list(range(1, nb_periods + 1)), index=self.histo_perf.index)
        coupon_payment = pd.DataFrame(columns=list(range(1, nb_periods + 1)), index=self.histo_perf.index)

        # 1. RAPPEL ANTICIPÉ (AUTOCALL)
        if self.from_redempt < nb_periods:
            for j in dates_obs.index:
                for i in range(self.from_redempt, nb_periods):
                    if pd.isnull(perf_obs.loc[j, i]):
                        continue
                    degr = self._get_autocall_barrier(i)
                    threshold = self.barriere_rappel - 100.0 - degr
                    if perf_obs.loc[j, i] >= threshold:
                        early_redemption.at[j, i] = self.remboursement_value
                        self.perf_benchmark.at[j, 'Perf'] = perf_obs.loc[j, i]
                        break

        # 2. PAIEMENT DES COUPONS
        if self.garanti:
            for j in dates_obs.index:
                for i in range(self.from_coupon, nb_periods + 1):
                    if not pd.isnull(perf_obs.loc[j, i]):
                        coupon_payment.at[j, i] = self.coupon
                    if not pd.isnull(early_redemption.loc[j, i]):
                        break

        elif self.memoire:
            for j in dates_obs.index:
                a = 1
                for i in range(1, nb_periods + 1):
                    try:
                        val_perf = perf_obs.loc[j, i]
                        if pd.isnull(val_perf):
                            continue
                        threshold_coupon = self.barriere_coupon - 100.0 - self.degressivite_coupon * i
                        if val_perf >= threshold_coupon and i >= self.from_coupon:
                            coupon_payment.at[j, i] = self.coupon * a
                            a = 1
                        else:
                            a += 1
                    except Exception:
                        continue
                    if not pd.isnull(early_redemption.loc[j, i]):
                        break

        else:
            for j in dates_obs.index:
                for i in range(self.from_coupon, nb_periods + 1):
                    try:
                        val_perf = perf_obs.loc[j, i]
                        if pd.isnull(val_perf):
                            continue
                        threshold_coupon = self.barriere_coupon - 100.0 - self.degressivite_coupon * i
                        if val_perf >= threshold_coupon:
                            coupon_payment.at[j, i] = self.coupon
                    except Exception:
                        continue
                    if not pd.isnull(early_redemption.loc[j, i]):
                        break

        # 3. ÉCHÉANCE FINALE (DERNIÈRE PÉRIODE)
        somme_earlyredemption = np.sum(early_redemption.fillna(0), axis=1)

        for j in dates_obs.index:
            if somme_earlyredemption[j] != 0:
                continue

            perf_final = perf_obs.loc[j, nb_periods]
            if pd.isnull(perf_final):
                continue

            if perf_final >= (self.pdi - 100.0):
                if perf_final >= (self.oxygen - 100.0):
                    early_redemption.at[j, nb_periods] = self.remboursement_value + self.coupon_oxygene * nb_periods
                    self.perf_benchmark.at[j, 'Perf'] = perf_final
                else:
                    val_part = max(
                        abs(self.remboursement_value * (self.certificat_participation - 1)),
                        self.certificat_participation * self.remboursement_value / 100.0 * min(self.cap - 100.0, perf_final) + 100.0,
                        100.0
                    )
                    early_redemption.at[j, nb_periods] = val_part
                    self.perf_benchmark.at[j, 'Perf'] = perf_final
            else:
                # Casse de barrière PDI : perte en capital
                early_redemption.at[j, nb_periods] = perf_final + 100.0
                self.perf_benchmark.at[j, 'Perf'] = perf_final

        self.early_redemption = early_redemption
        self.coupon_payment = coupon_payment

    def _compute_statistics_and_kpis(self):
        """Calcul de la distribution des performances et de l'analyse des expirations."""
        perf_obs = self.perf_obs
        dates_obs = self.dates_obs
        early_redemption = self.early_redemption
        coupon_payment = self.coupon_payment
        duree_vie = self.duree_vie
        freq_obs = self.freq_obs
        nb_periods = int(duree_vie / freq_obs)

        last_graph = perf_obs[self.from_redempt].last_valid_index()
        target_first_date = last_graph - pd.Timedelta(self.duree_analyse * 365.25, 'D')
        valid_first = dates_obs.loc[dates_obs.index >= target_first_date].index
        first_graph = valid_first[0] if len(valid_first) > 0 else dates_obs.index[0]

        a = early_redemption.fillna(0)
        b = coupon_payment.fillna(0)
        total = np.sum(a, axis=1) + np.sum(b, axis=1)
        total_window = total[first_graph:last_graph]

        # Breakdown par période de rappel
        window_early = early_redemption.loc[first_graph:last_graph].fillna(0).astype(bool)
        breakdown_series = window_early.sum(axis=0)
        denom = len(window_early) if len(window_early) > 0 else 1
        breakdown = pd.DataFrame(
            breakdown_series / denom * 100.0,
            columns=['Pourcentage de remboursement selon la periode (%)']
        )
        breakdown = breakdown.assign(Periode=list(range(1, nb_periods + 1)))

        sum_breakdown = breakdown['Pourcentage de remboursement selon la periode (%)'].sum()
        if sum_breakdown > 0:
            average_life = (
                (breakdown['Pourcentage de remboursement selon la periode (%)'] / 100.0 * breakdown['Periode']).sum()
                / (sum_breakdown / 100.0)
            )
        else:
            average_life = nb_periods

        non_called_pct = max(0.0, 100.0 - sum_breakdown)
        data_append = pd.DataFrame([{'Periode': 'Pas encore rappelé', 'Pourcentage de remboursement selon la periode (%)': non_called_pct}])
        breakdown = pd.concat([breakdown, data_append], ignore_index=True, sort=False)

        # Tableau récapitulatif
        tab_recap = total_window.copy()
        for i in self.histo_perf.loc[first_graph:last_graph].index:
            if a.loc[i].sum() == 0:
                tab_recap[i] = 0
        tab_recap = pd.to_numeric(tab_recap.replace(0, np.nan), errors='coerce')

        recent_start = last_graph - relativedelta(years=int(duree_vie - 1))
        redemption_value = early_redemption.loc[recent_start:last_graph].sum(axis=1)
        no_redemption = redemption_value[redemption_value != 100]
        prop_en_vie = (len(no_redemption) / len(redemption_value) * 100.0) if len(redemption_value) > 0 else 0.0

        non_nan_count = tab_recap.notna().sum()
        prop_sans_perte = ((tab_recap >= 100.0).sum() / non_nan_count * 100.0) if non_nan_count > 0 else 0.0
        total_numeric = pd.to_numeric(total_window, errors='coerce')
        remb_moyen_perte = tab_recap.where(total_numeric < 100.0).mean(skipna=True)

        analysis = pd.DataFrame({
            'Indicator': [
                'Min of the returns',
                'Max of the returns',
                'Median of the returns',
                'Mean of the returns',
                'Standard deviation of the returns',
                'Proportion qui n a pas perdu de capital (%)',
                'Remboursement moyen given loss in capital',
                'Average life',
                'Proportion de produits encore en vie (%)'
            ],
            'Value': [
                tab_recap.min(),
                tab_recap.max(),
                tab_recap.median(),
                tab_recap.mean(),
                tab_recap.std(),
                prop_sans_perte,
                remb_moyen_perte,
                average_life * freq_obs,
                prop_en_vie
            ]
        })

        # Produits non rappelés
        non_called = total_window.copy()
        redeemed_yn = early_redemption.loc[first_graph:last_graph].sum(axis=1)

        for i in self.histo_perf.loc[first_graph:last_graph].index:
            if redeemed_yn.get(i, 0) == 0:
                count_obs = perf_obs.loc[i].count()
                non_called[i] = perf_obs.loc[i][count_obs] if count_obs in perf_obs.columns else np.nan
            else:
                non_called[i] = np.nan

        non_called = pd.to_numeric(non_called, errors='coerce')
        valid_noncalled = non_called.loc[~non_called.isnull()]
        if valid_noncalled.empty:
            oldest_launch = 'plus de produits en vie'
        else:
            oldest_launch = str(valid_noncalled.index[0].strftime('%d/%m/%Y')) if hasattr(valid_noncalled.index[0], 'strftime') else str(valid_noncalled.index[0])

        analysis_noncalled = pd.DataFrame({
            'Indicator (à dernière date d observation)': [
                'Min of the underlying',
                'Max of the underlying',
                'Median of the underlying',
                'Mean of the underlying',
                'Date de lancement du produit non rappelé le plus ancien'
            ],
            'Value': [
                non_called.min(),
                non_called.max(),
                non_called.median(),
                non_called.mean(),
                oldest_launch
            ]
        })

        performance_summary = pd.DataFrame(
            a.replace(0, np.nan).sum(axis=1) + b.sum(axis=1)
        ).rename(columns={0: "Montant de remboursement"})

        self.breakdown = breakdown
        self.analysis = analysis
        self.analysis_noncalled = analysis_noncalled
        self.performance_summary = performance_summary

    def export_excel(self, destination=None):
        """
        Génère le classeur Excel à 10 onglets.
        Supporte un chemin de fichier ou un flux en mémoire (io.BytesIO).
        """
        target = destination or self.output_file
        is_bytes = isinstance(target, io.BytesIO)

        if not target:
            target = io.BytesIO()
            is_bytes = True

        with pd.ExcelWriter(target, engine='xlsxwriter') as writer:
            self.performance_summary.to_excel(writer, sheet_name='bench_perf')
            self.worst.to_excel(writer, sheet_name='worst')
            self.dates_obs.to_excel(writer, sheet_name='dates_observation')
            self.early_redemption.to_excel(writer, sheet_name='early_redemption')
            self.perf_obs.to_excel(writer, sheet_name='perf_ssjacents')
            self.histo.to_excel(writer, sheet_name='histo_ssjacents')
            self.coupon_payment.to_excel(writer, sheet_name='coupon_payment')
            self.analysis.to_excel(writer, sheet_name='analyse_prdtsexpires')
            self.analysis_noncalled.to_excel(writer, sheet_name='analyse_nonrappeles')
            self.breakdown.to_excel(writer, sheet_name='breakdown_rappel')

        if is_bytes:
            target.seek(0)
            self.excel_bytes = target
            return target
        return target

    def run(self):
        """Lance l'ensemble de la simulation de backtest."""
        t0 = time.time()
        self._load_data()
        self._compute_strike_reference()
        self._compute_observation_dates()
        self._compute_performances_at_observations()
        self._simulate_lifecycle()
        self._compute_statistics_and_kpis()

        if self.output_file is not False and self.output_file is not None:
            self.export_excel(self.output_file)

        return {
            'analysis': self.analysis,
            'breakdown': self.breakdown,
            'analysis_noncalled': self.analysis_noncalled,
            'performance_summary': self.performance_summary,
            'early_redemption': self.early_redemption,
            'worst': self.worst,
            'coupon_payment': self.coupon_payment,
            'perf_obs': self.perf_obs,
            'dates_obs': self.dates_obs,
            'histo': self.histo,
            'execution_time': time.time() - t0
        }
