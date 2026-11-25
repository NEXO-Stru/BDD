import numpy as np
import plotly.graph_objects as go
import matplotlib.pyplot as plt

class MarketScenario:
    """Gère l'environnement macro de marché de manière dynamique (N périodes).
    Définit uniquement la ligne de temps et la dérive de marché du Price Return (r_perf).
    La volatilité et le rendement de dividende appartiennent exclusivement aux indices.
    """
    def __init__(self, config_regimes, annees=10, jours_par_an=252):
        self.annees = annees
        self.jours_par_an = jours_par_an
        self.total_jours = annees * jours_par_an
        self.dt = 1.0 / jours_par_an
        
        self.config_regimes = config_regimes
        
        jour_actuel = 0
        annee_actuelle = 0
        # configure les régimes
        for i, regime in enumerate(self.config_regimes):
            regime['jour_debut'] = jour_actuel
            regime['annee_debut'] = annee_actuelle
            annee_actuelle += regime["duree_annees"]
            jour_actuel += int(regime["duree_annees"] * self.jours_par_an)
            regime['jour_fin'] = min(jour_actuel, self.total_jours)
            regime['annee_fin'] = min(annee_actuelle, self.annees)

        self.r_perf_dyn = np.zeros(self.total_jours)
        self.build_regimes()
        
    def build_regimes(self):
        for regime in self.config_regimes:
            j_deb = regime['jour_debut']
            j_fin = regime['jour_fin']
            if j_deb < self.total_jours:
                self.r_perf_dyn[j_deb:j_fin] = regime.get("r_perf", 0.0)
                

class DecrementIndex:
    """Modélise spécifiquement la mécanique mathématique d'un indice Décrément et ses caractéristiques propres :
    - niveau initial (S0)
    - décrément annuel (en points ou en pourcentage)
    - type de décrément ('POINTS' ou 'PERCENT')
    - volatilité propre (vol)
    - rendement de dividende réinvesti propre (dividend_yield)
    - nom / libellé
    """
    def __init__(self, niveau_initial=1000.0, decrement_annuel=50.0, vol=0.18, dividend_yield=0.03, nom="Indice Décrément", decrement_type="POINTS"):
        self.niveau_initial = float(niveau_initial)
        self.decrement_annuel = float(decrement_annuel)
        self.decrement_type = str(decrement_type).upper() if decrement_type else "POINTS"
        self.vol = vol
        self.dividend_yield = dividend_yield
        self.nom = str(nom)
        
    def get_auto_label(self, idx_num=None):
        s0_str = f"S0 {self.niveau_initial:.0f} | " if abs(self.niveau_initial - 1000.0) > 1e-4 else ""
        vol_val = self.vol[0] if isinstance(self.vol, (list, tuple, np.ndarray)) else self.vol
        div_val = self.dividend_yield[0] if isinstance(self.dividend_yield, (list, tuple, np.ndarray)) else self.dividend_yield
        vol_str = f"{vol_val*100:.0f}%"
        div_str = f"{div_val*100:.1f}%"
        dec_str = f"{self.decrement_annuel:.1f}%" if self.decrement_type == "PERCENT" else f"{self.decrement_annuel:.0f} pts"
        prefix = f"Indice {idx_num} " if idx_num is not None else ""
        return f"{prefix}({s0_str}Dec {dec_str} | Vol {vol_str} | Div {div_str})"
        
    def _get_vol_dyn(self, scenario: MarketScenario):
        if self.vol is None:
            raise ValueError("La volatilité (vol) doit être définie sur l'indice DecrementIndex.")
        if isinstance(self.vol, (list, tuple, np.ndarray)):
            vol_dyn = np.zeros(scenario.total_jours)
            cumul_j = 0
            for i, v in enumerate(self.vol):
                reg = scenario.config_regimes[i] if i < len(scenario.config_regimes) else None
                nb_j = reg['duree_annees'] * scenario.jours_par_an if reg else (scenario.total_jours - cumul_j)
                j_deb = cumul_j
                j_fin = min(scenario.total_jours, j_deb + nb_j)
                vol_dyn[j_deb:j_fin] = float(v)
                cumul_j = j_fin
            if cumul_j < scenario.total_jours:
                vol_dyn[cumul_j:] = float(self.vol[-1])
            return vol_dyn
        else:
            return np.full(scenario.total_jours, float(self.vol))

    def _get_yield_dyn(self, scenario: MarketScenario):
        if self.dividend_yield is None:
            raise ValueError("Le rendement dividende (dividend_yield) doit être défini sur l'indice DecrementIndex.")
        if isinstance(self.dividend_yield, (list, tuple, np.ndarray)):
            yield_dyn = np.zeros(scenario.total_jours)
            cumul_j = 0
            for i, y in enumerate(self.dividend_yield):
                reg = scenario.config_regimes[i] if i < len(scenario.config_regimes) else None
                nb_j = reg['duree_annees'] * scenario.jours_par_an if reg else (scenario.total_jours - cumul_j)
                j_deb = cumul_j
                j_fin = min(scenario.total_jours, j_deb + nb_j)
                yield_dyn[j_deb:j_fin] = float(y)
                cumul_j = j_fin
            if cumul_j < scenario.total_jours:
                yield_dyn[cumul_j:] = float(self.dividend_yield[-1])
            return yield_dyn
        else:
            return np.full(scenario.total_jours, float(self.dividend_yield))

    def simulate(self, scenario: MarketScenario, nb_trajectoires, Z_chocs):
        is_percent = (self.decrement_type == "PERCENT")
        if is_percent:
            d_rate = (self.decrement_annuel / 100.0) if self.decrement_annuel > 1.0 else self.decrement_annuel
        else:
            d_points = self.decrement_annuel / scenario.jours_par_an

        dt = scenario.dt
        total_jours = scenario.total_jours
        
        trajectoires_dec = np.zeros((nb_trajectoires, total_jours + 1))
        trajectoires_pr = np.zeros((nb_trajectoires, total_jours + 1))
        
        trajectoires_dec[:, 0] = self.niveau_initial
        trajectoires_pr[:, 0] = self.niveau_initial
        
        vol_dyn = self._get_vol_dyn(scenario)
        yield_dyn = self._get_yield_dyn(scenario)
        
        for t in range(1, total_jours + 1):
            z = Z_chocs[:, t-1]
            vol_j = vol_dyn[t-1]
            r_perf_j = scenario.r_perf_dyn[t-1]  # Drift Price Return macro
            yield_j = yield_dyn[t-1]             # Rendement dividende de l'indice
            
            choc_jour = vol_j * np.sqrt(dt) * z
            
            # --- Indice Total Return (Base : Drift PR + Yield) ---
            evol_tr = np.exp((r_perf_j + yield_j - 0.5 * vol_j**2) * dt + choc_jour)
            
            # --- Indice Price Return (Drift PR direct) ---
            evol_pr = np.exp((r_perf_j - 0.5 * vol_j**2) * dt + choc_jour)
            
            # Application
            n_niv_pr = trajectoires_pr[:, t-1] * evol_pr
            
            if is_percent:
                # Décrément continu en pourcentage : prélèvement proportionnel au cours du jour
                evol_dec = np.exp((r_perf_j + yield_j - d_rate - 0.5 * vol_j**2) * dt + choc_jour)
                n_niv_dec = trajectoires_dec[:, t-1] * evol_dec
            else:
                # Décrément en points fixes :
                n_niv_dec = (trajectoires_dec[:, t-1] * evol_tr) - d_points
                # Plancher à 0
                n_niv_dec = np.maximum(0.0, n_niv_dec)
            
            trajectoires_dec[:, t] = n_niv_dec
            trajectoires_pr[:, t] = n_niv_pr
            
        return trajectoires_pr, trajectoires_dec

    def simulate_single(self, r_rf: float, total_jours: int, dt: float, nb_trajectoires: int, Z_chocs: np.ndarray, jours_par_an: int = 252):
        """Simule la trajectoire propre de l'indice sous drift risque-neutre r_rf."""
        dec_type = str(self.decrement_type).upper()
        vol_val = float(self.vol[0] if isinstance(self.vol, (list, tuple, np.ndarray)) else self.vol)
        div_val = float(self.dividend_yield[0] if isinstance(self.dividend_yield, (list, tuple, np.ndarray)) else (self.dividend_yield or 0.0))
        
        trajectoires = np.zeros((nb_trajectoires, total_jours + 1))
        trajectoires[:, 0] = self.niveau_initial
        
        if dec_type == "PERCENT":
            d_rate = (self.decrement_annuel / 100.0) if self.decrement_annuel > 1.0 else self.decrement_annuel
            drift_dec = r_rf - d_rate - 0.5 * vol_val**2
            chocs_cum = np.cumsum(vol_val * np.sqrt(dt) * Z_chocs, axis=1)
            t_steps = np.arange(1, total_jours + 1)
            evol = np.exp(drift_dec * dt * t_steps + chocs_cum)
            trajectoires[:, 1:] = self.niveau_initial * evol
            
        elif dec_type == "PRICE_RETURN":
            drift_pr = r_rf - div_val - 0.5 * vol_val**2
            chocs_cum = np.cumsum(vol_val * np.sqrt(dt) * Z_chocs, axis=1)
            t_steps = np.arange(1, total_jours + 1)
            evol = np.exp(drift_pr * dt * t_steps + chocs_cum)
            trajectoires[:, 1:] = self.niveau_initial * evol
            
        elif dec_type == "TOTAL_RETURN":
            drift_tr = r_rf - 0.5 * vol_val**2
            chocs_cum = np.cumsum(vol_val * np.sqrt(dt) * Z_chocs, axis=1)
            t_steps = np.arange(1, total_jours + 1)
            evol = np.exp(drift_tr * dt * t_steps + chocs_cum)
            trajectoires[:, 1:] = self.niveau_initial * evol
            
        else:  # "POINTS"
            d_points = self.decrement_annuel / jours_par_an
            drift_tr = r_rf - 0.5 * vol_val**2
            for t in range(1, total_jours + 1):
                z = Z_chocs[:, t-1]
                evol_tr = np.exp(drift_tr * dt + vol_val * np.sqrt(dt) * z)
                n_niv = (trajectoires[:, t-1] * evol_tr) - d_points
                trajectoires[:, t] = np.maximum(0.0, n_niv)
                
        return trajectoires


def _resoudre_tri_vectorise(cf_matrix: np.ndarray, capitals: np.ndarray, exit_times: np.ndarray, t_obs_array: np.ndarray) -> np.ndarray:
    """Calcule le Taux de Rendement Interne (TRI / IRR) annualisé exact par trajectoire via Newton-Raphson vectorisé."""
    total_cash = np.sum(cf_matrix, axis=1) + capitals
    # Initialisation robuste : TRI composé estimé sur la durée de vie effective
    safe_exits = np.maximum(0.08, exit_times)
    r = np.where(total_cash > 0, (total_cash) ** (1.0 / safe_exits) - 1.0, -1.0)
    r = np.clip(r, -0.99, 1.5)
    
    for _ in range(8):
        one_plus_r = np.maximum(0.01, 1.0 + r)
        val = -1.0
        der = 0.0
        for k, t in enumerate(t_obs_array):
            mask = (t <= exit_times)
            cf_k = cf_matrix[:, k]
            denom = (one_plus_r) ** t
            val += mask * (cf_k / denom)
            der -= mask * (t * cf_k / (denom * one_plus_r))
            
        denom_cap = (one_plus_r) ** exit_times
        val += capitals / denom_cap
        der -= exit_times * capitals / (denom_cap * one_plus_r)
        
        der = np.where(np.abs(der) < 1e-12, -1e-12, der)
        diff = np.clip(val / der, -0.4, 0.4)
        r = r - diff
        r = np.maximum(-0.999, r)
        if np.max(np.abs(diff)) < 1e-5:
            break
            
    return r


class AutocallProduct:
    """Modélise le produit structuré et ses règles de marché (classe de base)."""
    def __init__(self, barriere_rappel=1000.0, niveau_pdi=500.0, non_call_period_mois=12, 
                 frequence_obs_mois=3, degressivite=0.0, plancher_rappel=None, coupon_periode=2.0, ref_s0=None):
        self.barriere_rappel = float(barriere_rappel)
        self.niveau_pdi = float(niveau_pdi)
        self.non_call_period_mois = int(non_call_period_mois)
        self.frequence_obs_mois = int(frequence_obs_mois)
        self.degressivite = float(degressivite)
        self.coupon_periode = float(coupon_periode) / 100.0
        self.ref_s0 = float(ref_s0) if ref_s0 is not None else self.barriere_rappel
        self.plancher_rappel = float(plancher_rappel) if plancher_rappel is not None else None
        
    def clone_for_spot(self, new_s0):
        ratio = float(new_s0) / self.ref_s0
        return AutocallProduct(
            barriere_rappel=self.barriere_rappel * ratio,
            niveau_pdi=self.niveau_pdi * ratio,
            non_call_period_mois=self.non_call_period_mois,
            frequence_obs_mois=self.frequence_obs_mois,
            degressivite=self.degressivite,
            plancher_rappel=self.plancher_rappel * ratio if self.plancher_rappel is not None else None,
            coupon_periode=self.coupon_periode * 100.0,
            ref_s0=float(new_s0)
        )

    def get_barrieres_schedule(self, total_jours: int, jours_par_an: int = 252):
        """Calcule le calendrier des dates d'observation et les barrières de rappel associées."""
        jours_par_mois = jours_par_an // 12
        if self.frequence_obs_mois == 0:
            jours_entre_obs = 1  # Quotidien
        else:
            jours_entre_obs = max(1, jours_par_mois * self.frequence_obs_mois)
            
        dates_obs_jours = list(range(jours_entre_obs, total_jours + 1, jours_entre_obs))
        # Sécurité mathématique : forcer la date de maturité finale
        if total_jours not in dates_obs_jours:
            dates_obs_jours.append(total_jours)
            
        baisse_pts = self.barriere_rappel * (self.degressivite / 100.0)
        plancher_pts = self.plancher_rappel if self.plancher_rappel is not None else 0.0
        non_call_jours = jours_par_mois * self.non_call_period_mois
        
        schedule = []
        nb_obs_deg = 0
        for k, t in enumerate(dates_obs_jours):
            annee = t / float(jours_par_an)
            is_eligible = (t >= non_call_jours)
            if is_eligible:
                barr = max(plancher_pts, self.barriere_rappel - (nb_obs_deg * baisse_pts))
                nb_obs_deg += 1
            else:
                barr = np.nan
                
            schedule.append({
                "obs_num": k + 1,
                "jour": t,
                "annee": annee,
                "eligible": is_eligible,
                "barriere_pts": barr,
                "barriere_pct": (barr / self.ref_s0 * 100.0) if np.isfinite(barr) else np.nan
            })
        return schedule
        
    def evaluate(self, trajectoires, scenario=None, nb_trajectoires=None, total_jours=None, jours_par_an=252):
        if nb_trajectoires is None:
            nb_trajectoires = trajectoires.shape[0]
        if total_jours is None:
            total_jours = scenario.total_jours if scenario is not None else (trajectoires.shape[1] - 1)
        if scenario is not None and hasattr(scenario, 'jours_par_an'):
            jours_par_an = scenario.jours_par_an
            
        est_rappele = np.zeros(nb_trajectoires, dtype=bool)
        obs_de_rappel = np.zeros(nb_trajectoires, dtype=int)
        
        schedule = self.get_barrieres_schedule(total_jours, jours_par_an)
        for item in schedule:
            if not item["eligible"]:
                continue
            k_obs = item["obs_num"]
            t_j = item["jour"]
            barr = item["barriere_pts"]
            
            nouveaux_rappels = (~est_rappele) & (trajectoires[:, t_j] >= barr)
            obs_de_rappel[nouveaux_rappels] = k_obs
            est_rappele = est_rappele | nouveaux_rappels
            
        return est_rappele, obs_de_rappel
        
    def calculate_payoff(self, trajectoires, est_rappele, obs_de_rappel, niveau_initial, scenario=None, taux_actualisation: float = 0.0, total_jours=None, jours_par_an=252):
        # Payoff de type Athéna (comportement par défaut)
        nb_trajectoires = trajectoires.shape[0]
        if total_jours is None:
            total_jours = scenario.total_jours if scenario is not None else (trajectoires.shape[1] - 1)
        if scenario is not None and hasattr(scenario, 'jours_par_an'):
            jours_par_an = scenario.jours_par_an
        annees_totales = total_jours / float(jours_par_an)
        
        schedule = self.get_barrieres_schedule(total_jours, jours_par_an)
        annees_map = {item["obs_num"]: item["annee"] for item in schedule}
        
        payoffs = np.zeros(nb_trajectoires)
        cashflows_nom = np.zeros(nb_trajectoires)
        tri_annualise = np.zeros(nb_trajectoires)
        duree_effective = np.zeros(nb_trajectoires)
        coupons_touches = np.zeros(nb_trajectoires)
        capital_rembourse = np.zeros(nb_trajectoires)
        
        # 1. Rappelés
        rappeles_idx = np.where(est_rappele)[0]
        if len(rappeles_idx) > 0:
            obs_r = obs_de_rappel[rappeles_idx]
            temps_r = np.array([annees_map.get(o, annees_totales) for o in obs_r])
            duree_effective[rappeles_idx] = temps_r
            
            coupons_val = self.coupon_periode * obs_r
            coupons_touches[rappeles_idx] = coupons_val
            capital_rembourse[rappeles_idx] = 1.0
            
            cash_tot = 1.0 + coupons_val
            cashflows_nom[rappeles_idx] = cash_tot
            payoffs[rappeles_idx] = cash_tot * np.exp(-taux_actualisation * temps_r)
            
            tri_annualise[rappeles_idx] = np.where(
                temps_r > 0,
                (cash_tot) ** (1.0 / temps_r) - 1.0,
                coupons_val
            )
            
        # 2. Non rappelés
        non_rappeles_idx = np.where(~est_rappele)[0]
        if len(non_rappeles_idx) > 0:
            duree_effective[non_rappeles_idx] = annees_totales
            facteur_actu_mat = np.exp(-taux_actualisation * annees_totales)
            valeurs_finales = trajectoires[non_rappeles_idx, -1]
            
            pdi_ok = valeurs_finales >= self.niveau_pdi
            idx_pdi_ok = non_rappeles_idx[pdi_ok]
            idx_pdi_ko = non_rappeles_idx[~pdi_ok]
            
            if len(idx_pdi_ok) > 0:
                capital_rembourse[idx_pdi_ok] = 1.0
                cashflows_nom[idx_pdi_ok] = 1.0
                payoffs[idx_pdi_ok] = 1.0 * facteur_actu_mat
                tri_annualise[idx_pdi_ok] = 0.0
                
            if len(idx_pdi_ko) > 0:
                vals_ko = trajectoires[idx_pdi_ko, -1]
                ratio_remb = np.maximum(0.0, vals_ko / niveau_initial)
                capital_rembourse[idx_pdi_ko] = ratio_remb
                cashflows_nom[idx_pdi_ko] = ratio_remb
                payoffs[idx_pdi_ko] = ratio_remb * facteur_actu_mat
                tri_annualise[idx_pdi_ko] = np.where(
                    ratio_remb > 0,
                    (ratio_remb) ** (1.0 / annees_totales) - 1.0,
                    -1.0
                )
                
        metrics = {
            "payoffs": payoffs,
            "cashflows_nom": cashflows_nom,
            "tri_annualise": tri_annualise,
            "duree_effective": duree_effective,
            "coupons_touches": coupons_touches,
            "capital_rembourse": capital_rembourse
        }
        return payoffs, metrics


class AthenaProduct(AutocallProduct):
    """Produit structuré de type Athéna.
    Le coupon n'est versé qu'au moment du rappel anticipé (effet mémoire automatique).
    Aucun flux intermédiaire n'est détaché en cours de vie.
    """
    def __init__(self, barriere_rappel=1000.0, niveau_pdi=500.0, non_call_period_mois=12, 
                 frequence_obs_mois=3, degressivite=0.0, plancher_rappel=None, coupon_periode=2.0, ref_s0=None):
        super().__init__(
            barriere_rappel=barriere_rappel,
            niveau_pdi=niveau_pdi,
            non_call_period_mois=non_call_period_mois,
            frequence_obs_mois=frequence_obs_mois,
            degressivite=degressivite,
            plancher_rappel=plancher_rappel,
            coupon_periode=coupon_periode,
            ref_s0=ref_s0
        )

    def clone_for_spot(self, new_s0):
        ratio = float(new_s0) / self.ref_s0
        return AthenaProduct(
            barriere_rappel=self.barriere_rappel * ratio,
            niveau_pdi=self.niveau_pdi * ratio,
            non_call_period_mois=self.non_call_period_mois,
            frequence_obs_mois=self.frequence_obs_mois,
            degressivite=self.degressivite,
            plancher_rappel=self.plancher_rappel * ratio if self.plancher_rappel is not None else None,
            coupon_periode=self.coupon_periode * 100.0,
            ref_s0=float(new_s0)
        )


class PhoenixProduct(AutocallProduct):
    """Produit structuré de type Phoenix (avec ou sans mémoire).
    Comporte deux barrières distinctes :
    - Barrière de rappel anticipé (Autocall)
    - Barrière de coupon (détachement périodique au fil de l'eau)
    Chaque coupon est actualisé à sa propre date de versement.
    """
    def __init__(self, barriere_rappel=1000.0, barriere_coupon=700.0, niveau_pdi=500.0, 
                 non_call_period_mois=12, frequence_obs_mois=3, degressivite=0.0, plancher_rappel=None,
                 coupon_periode=2.0, avec_memoire=True, ref_s0=None):
        super().__init__(
            barriere_rappel=barriere_rappel,
            niveau_pdi=niveau_pdi,
            non_call_period_mois=non_call_period_mois,
            frequence_obs_mois=frequence_obs_mois,
            degressivite=degressivite,
            plancher_rappel=plancher_rappel,
            coupon_periode=coupon_periode,
            ref_s0=ref_s0
        )
        self.barriere_coupon = float(barriere_coupon)
        self.avec_memoire = bool(avec_memoire)

    def clone_for_spot(self, new_s0):
        ratio = float(new_s0) / self.ref_s0
        return PhoenixProduct(
            barriere_rappel=self.barriere_rappel * ratio,
            barriere_coupon=self.barriere_coupon * ratio,
            niveau_pdi=self.niveau_pdi * ratio,
            non_call_period_mois=self.non_call_period_mois,
            frequence_obs_mois=self.frequence_obs_mois,
            degressivite=self.degressivite,
            plancher_rappel=self.plancher_rappel * ratio if self.plancher_rappel is not None else None,
            coupon_periode=self.coupon_periode * 100.0,
            avec_memoire=self.avec_memoire,
            ref_s0=float(new_s0)
        )

    def calculate_payoff(self, trajectoires, est_rappele, obs_de_rappel, niveau_initial, scenario=None, taux_actualisation: float = 0.0, total_jours=None, jours_par_an=252):
        nb_trajectoires = trajectoires.shape[0]
        if total_jours is None:
            total_jours = scenario.total_jours if scenario is not None else (trajectoires.shape[1] - 1)
        if scenario is not None and hasattr(scenario, 'jours_par_an'):
            jours_par_an = scenario.jours_par_an
        annees_totales = total_jours / float(jours_par_an)
        
        schedule = self.get_barrieres_schedule(total_jours, jours_par_an)
        nb_obs = len(schedule)
        t_obs_array = np.array([item["annee"] for item in schedule])
        
        payoffs = np.zeros(nb_trajectoires)
        cashflows_nom = np.zeros(nb_trajectoires)
        coupons_total = np.zeros(nb_trajectoires)
        capital_rembourse = np.zeros(nb_trajectoires)
        duree_effective = np.zeros(nb_trajectoires)
        
        cf_matrix = np.zeros((nb_trajectoires, nb_obs))
        en_vie = np.ones(nb_trajectoires, dtype=bool)
        coupons_memoire = np.zeros(nb_trajectoires, dtype=float)
        
        nb_coupons_encaisses = np.zeros(nb_trajectoires, dtype=float)
        nb_coupons_sauves_memoire = np.zeros(nb_trajectoires, dtype=float)
        nb_obs_actives = np.zeros(nb_trajectoires, dtype=int)
        
        for k_idx, item in enumerate(schedule):
            t_j = item["jour"]
            obs_num = item["obs_num"]
            t_annee = item["annee"]
            facteur_actu = np.exp(-taux_actualisation * t_annee)
            
            masque_actifs = en_vie
            if not np.any(masque_actifs):
                break
                
            nb_obs_actives[masque_actifs] += 1
            niveaux_actifs = trajectoires[masque_actifs, t_j]
            coupon_condition = (niveaux_actifs >= self.barriere_coupon)
            
            indices_actifs = np.where(masque_actifs)[0]
            indices_coupon_ok = indices_actifs[coupon_condition]
            indices_coupon_ko = indices_actifs[~coupon_condition]
            
            # 1. Gestion des coupons
            if self.avec_memoire:
                mem_prec = coupons_memoire[indices_coupon_ok]
                montant_coupons = self.coupon_periode + mem_prec
                payoffs[indices_coupon_ok] += montant_coupons * facteur_actu
                cf_matrix[indices_coupon_ok, k_idx] = montant_coupons
                coupons_total[indices_coupon_ok] += montant_coupons
                
                # Suivi coupons sauvés par mémoire
                sauves_masque = (mem_prec > 1e-6)
                if np.any(sauves_masque):
                    idx_sauves = indices_coupon_ok[sauves_masque]
                    nb_coupons_sauves_memoire[idx_sauves] += np.round(mem_prec[sauves_masque] / self.coupon_periode)
                
                nb_coupons_encaisses[indices_coupon_ok] += np.round(montant_coupons / self.coupon_periode)
                coupons_memoire[indices_coupon_ok] = 0.0
                
                # Mise en mémoire pour ceux sous la barrière
                coupons_memoire[indices_coupon_ko] += self.coupon_periode
            else:
                payoffs[indices_coupon_ok] += self.coupon_periode * facteur_actu
                cf_matrix[indices_coupon_ok, k_idx] = self.coupon_periode
                coupons_total[indices_coupon_ok] += self.coupon_periode
                nb_coupons_encaisses[indices_coupon_ok] += 1.0
                
            # 2. Gestion du rappel anticipé à cette observation
            rappel_a_cette_obs = est_rappele & (obs_de_rappel == obs_num) & en_vie
            if np.any(rappel_a_cette_obs):
                payoffs[rappel_a_cette_obs] += 1.0 * facteur_actu
                capital_rembourse[rappel_a_cette_obs] = 1.0
                duree_effective[rappel_a_cette_obs] = t_annee
                en_vie[rappel_a_cette_obs] = False
                
        # 3. Remboursement du capital à maturité pour les trajectoires non rappelées
        non_rappeles = ~est_rappele
        if np.any(non_rappeles):
            facteur_actu_maturite = np.exp(-taux_actualisation * annees_totales)
            valeurs_finales = trajectoires[non_rappeles, -1]
            indices_non_rappeles = np.where(non_rappeles)[0]
            duree_effective[indices_non_rappeles] = annees_totales
            
            au_dessus_pdi = valeurs_finales >= self.niveau_pdi
            indices_pdi_ok = indices_non_rappeles[au_dessus_pdi]
            payoffs[indices_pdi_ok] += 1.0 * facteur_actu_maturite
            capital_rembourse[indices_pdi_ok] = 1.0
            
            indices_pdi_ko = indices_non_rappeles[~au_dessus_pdi]
            ratio_perte = np.maximum(0.0, valeurs_finales[~au_dessus_pdi] / niveau_initial)
            payoffs[indices_pdi_ko] += ratio_perte * facteur_actu_maturite
            capital_rembourse[indices_pdi_ko] = ratio_perte
            
        cashflows_nom = coupons_total + capital_rembourse
        
        # 4. Résolution vectorisée exacte du TRI (IRR)
        tri_annualise = _resoudre_tri_vectorise(cf_matrix, capital_rembourse, duree_effective, t_obs_array)
        
        # Métriques riches de flux Phoenix
        taux_coupons_encaisses = float(np.mean(nb_coupons_encaisses / np.maximum(1, nb_obs_actives)) * 100.0)
        efficacite_memoire = float(np.mean(nb_coupons_sauves_memoire > 0) * 100.0)
        coupons_total_moyen = float(np.mean(coupons_total) * 100.0)
        nb_coupons_encaisses_moy = float(np.mean(nb_coupons_encaisses))
        
        metrics = {
            "payoffs": payoffs,
            "cashflows_nom": cashflows_nom,
            "tri_annualise": tri_annualise,
            "duree_effective": duree_effective,
            "coupons_touches": coupons_total,
            "capital_rembourse": capital_rembourse,
            "taux_coupons_encaisses": taux_coupons_encaisses,
            "efficacite_memoire": efficacite_memoire,
            "coupons_total_moyen": coupons_total_moyen,
            "nb_coupons_encaisses_moy": nb_coupons_encaisses_moy
        }
        return payoffs, metrics

class SimulationEngine:
    """Le chef d'orchestre qui lance les calculs globaux"""
    def __init__(self, nb_trajectoires=10000, seed=42):
        self.nb_trajectoires = nb_trajectoires
        self.seed = seed
        
    def simulate_trajectoires(self, index: DecrementIndex, scenario: MarketScenario):
        """Simule uniquement les trajectoires PR et Décrément (pur stress test sous-jacent)"""
        np.random.seed(self.seed)
        print(f"Simulation de {self.nb_trajectoires} trajectoires d'indices en cours...")
        Z_chocs = np.random.normal(0, 1, size=(self.nb_trajectoires, scenario.total_jours))
        traj_pr, traj_dec = index.simulate(scenario, self.nb_trajectoires, Z_chocs)
        return traj_pr, traj_dec

    def evaluer_produit(self, product: AutocallProduct, traj_pr, traj_dec, scenario: MarketScenario, niveau_initial=None, taux_actualisation=0.0):
        """Évalue les payoffs d'un produit structuré sur des trajectoires existantes"""
        if niveau_initial is None:
            niveau_initial = traj_dec[0, 0]
            
        # Sur le Decrement
        est_rappele_dec, obs_de_rappel_dec = product.evaluate(traj_dec, scenario, self.nb_trajectoires)
        res_dec = product.calculate_payoff(traj_dec, est_rappele_dec, obs_de_rappel_dec, niveau_initial, scenario, taux_actualisation)
        payoffs_dec = res_dec[0] if isinstance(res_dec, tuple) else res_dec
        
        # Sur le Price Return
        est_rappele_pr, obs_de_rappel_pr = product.evaluate(traj_pr, scenario, self.nb_trajectoires)
        res_pr = product.calculate_payoff(traj_pr, est_rappele_pr, obs_de_rappel_pr, niveau_initial, scenario, taux_actualisation)
        payoffs_pr = res_pr[0] if isinstance(res_pr, tuple) else res_pr
        
        return est_rappele_dec, obs_de_rappel_dec, payoffs_dec, est_rappele_pr, obs_de_rappel_pr, payoffs_pr

    def run_pricing_simulation(self, list_indices: list, product: AutocallProduct, annees: int, 
                               r_sans_risque: float = 0.03, taux_actualisation: float = None, jours_par_an: int = 252):
        """Pricer dédié et direct pour une liste d'indices (Price Return, Décrément % ou Décrément Pts).
        Le Total Return sous-jacent dérive toujours au taux sans risque r_sans_risque.
        Chaque indice est simulé sur sa propre dynamique sans dualisme artificiel.
        """
        if taux_actualisation is None:
            taux_actualisation = r_sans_risque
            
        total_jours = int(annees * jours_par_an)
        dt = 1.0 / float(jours_par_an)
        
        # Tirages appariés stricts
        np.random.seed(self.seed)
        Z_chocs = np.random.normal(0, 1, size=(self.nb_trajectoires, total_jours))
        
        schedule = product.get_barrieres_schedule(total_jours, jours_par_an)
        
        results = {}
        for idx in list_indices:
            s0 = float(idx.niveau_initial)
            # 1. Simulation propre de l'indice
            trajectoires = idx.simulate_single(r_sans_risque, total_jours, dt, self.nb_trajectoires, Z_chocs, jours_par_an)
            
            # 2. Clonage du produit adapté au spot de cet indice
            prod_idx = product.clone_for_spot(s0)
            
            # 3. Évaluation du rappel
            est_rappele, obs_de_rappel = prod_idx.evaluate(
                trajectoires, nb_trajectoires=self.nb_trajectoires, total_jours=total_jours, jours_par_an=jours_par_an
            )
            
            # 4. Calcul des payoffs et métriques riches
            payoffs, metrics = prod_idx.calculate_payoff(
                trajectoires, est_rappele, obs_de_rappel, s0, 
                taux_actualisation=taux_actualisation, total_jours=total_jours, jours_par_an=jours_par_an
            )
            
            # 5. Calcul des KPIs financiers
            tri_array = metrics["tri_annualise"]
            valeurs_finales = trajectoires[:, -1]
            
            # PDI
            sous_pdi = (~est_rappele) & (valeurs_finales < prod_idx.niveau_pdi)
            pct_pdi = float(np.mean(sous_pdi) * 100.0)
            perte_moy_pdi = float(1.0 - (np.mean(valeurs_finales[sous_pdi]) / s0)) * 100.0 if np.any(sous_pdi) else 0.0
            
            # Autocall & Duration
            pct_rappel = float(np.mean(est_rappele) * 100.0)
            duration = float(np.mean(metrics["duree_effective"]))
            moy_payoff = float(np.mean(payoffs) * 100.0)
            
            # TRI
            tri_moyen = float(np.mean(tri_array) * 100.0)
            tri_median = float(np.median(tri_array) * 100.0)
            tri_p10 = float(np.percentile(tri_array, 10) * 100.0)
            tri_p90 = float(np.percentile(tri_array, 90) * 100.0)
            pct_tri_positif = float(np.mean(tri_array > 0.0) * 100.0)
            
            # Sorties par date (Waterfall)
            sorties_obs = []
            for item in schedule:
                obs_k = item["obs_num"]
                mask_obs = est_rappele & (obs_de_rappel == obs_k)
                pct_obs = float(np.mean(mask_obs) * 100.0)
                sorties_obs.append({
                    "obs_num": obs_k,
                    "annee": item["annee"],
                    "barriere_pct": item["barriere_pct"],
                    "pct_rappel": pct_obs
                })
            
            non_rappeles = ~est_rappele
            pct_remb_pair = float(np.mean(non_rappeles & ~sous_pdi) * 100.0)
            
            res_idx = {
                "index": idx,
                "product": prod_idx,
                "trajectoires": trajectoires,
                "est_rappele": est_rappele,
                "obs_de_rappel": obs_de_rappel,
                "payoffs": payoffs,
                "metrics": metrics,
                "tri_array": tri_array,
                "pct_rappel": pct_rappel,
                "duration": duration,
                "moy_payoff": moy_payoff,
                "pct_pdi": pct_pdi,
                "perte_moy_pdi": perte_moy_pdi,
                "tri_moyen": tri_moyen,
                "tri_median": tri_median,
                "tri_p10": tri_p10,
                "tri_p90": tri_p90,
                "pct_tri_positif": pct_tri_positif,
                "pct_remb_pair": pct_remb_pair,
                "sorties_obs": sorties_obs,
                "schedule": schedule,
                "taux_coupons_encaisses": metrics.get("taux_coupons_encaisses"),
                "efficacite_memoire": metrics.get("efficacite_memoire"),
                "coupons_total_moyen": metrics.get("coupons_total_moyen"),
                "nb_coupons_encaisses_moy": metrics.get("nb_coupons_encaisses_moy")
            }
            results[idx.nom] = res_idx
            
        return results

    def run(self, index: DecrementIndex, scenario: MarketScenario, product: AutocallProduct = None, taux_actualisation=0.0):
        traj_pr, traj_dec = self.simulate_trajectoires(index, scenario)
        if product is None:
            return traj_pr, traj_dec
            
        est_rappele_dec, obs_de_rappel_dec, payoffs_dec, est_rappele_pr, obs_de_rappel_pr, payoffs_pr = self.evaluer_produit(
            product, traj_pr, traj_dec, scenario, niveau_initial=index.niveau_initial, taux_actualisation=taux_actualisation
        )
        return traj_pr, traj_dec, est_rappele_dec, obs_de_rappel_dec, payoffs_dec, est_rappele_pr, obs_de_rappel_pr, payoffs_pr

    def simulate_multi_indices(self, list_indices: list, scenario: MarketScenario):
        """Simule simultanément plusieurs indices sur la MÊME matrice de chocs aléatoires Z (tirages appariés)."""
        np.random.seed(self.seed)
        Z_chocs = np.random.normal(0, 1, size=(self.nb_trajectoires, scenario.total_jours))
        results = {}
        for idx in list_indices:
            traj_pr, traj_dec = idx.simulate(scenario, self.nb_trajectoires, Z_chocs)
            s0 = idx.niveau_initial

            # 1. Maturité
            val_fin_dec = traj_dec[:, -1]
            val_fin_pr = traj_pr[:, -1]
            moy_dec = float(np.mean(val_fin_dec))
            moy_pr = float(np.mean(val_fin_pr))

            # 2. Horizon 1 An
            j_1an = min(scenario.total_jours, 1 * scenario.jours_par_an)
            val_1an_dec = traj_dec[:, j_1an]
            val_1an_pr = traj_pr[:, j_1an]
            moy_1an_dec = float(np.mean(val_1an_dec))
            moy_1an_pr = float(np.mean(val_1an_pr))

            # 3. Horizon 5 Ans
            has_5ans = (scenario.annees >= 5)
            j_5ans = min(scenario.total_jours, 5 * scenario.jours_par_an)
            val_5ans_dec = traj_dec[:, j_5ans]
            val_5ans_pr = traj_pr[:, j_5ans]
            moy_5ans_dec = float(np.mean(val_5ans_dec))
            moy_5ans_pr = float(np.mean(val_5ans_pr))
            
            results[idx.nom] = {
                "index": idx,
                "traj_pr": traj_pr,
                "traj_dec": traj_dec,
                "moy_dec": moy_dec,
                "moy_pr": moy_pr,
                "moy_dec_pct": (moy_dec / s0 - 1.0) * 100.0,
                "moy_pr_pct": (moy_pr / s0 - 1.0) * 100.0,
                "ecart_moy_pts": moy_dec - moy_pr,
                "ecart_moy_pct": ((moy_dec - moy_pr) / s0) * 100.0,
                "pct_crash_50_dec": np.mean(val_fin_dec < 0.50 * s0) * 100.0,
                "pct_crash_50_pr": np.mean(val_fin_pr < 0.50 * s0) * 100.0,
                "moy_1an_dec": moy_1an_dec,
                "moy_1an_pr": moy_1an_pr,
                "moy_1an_dec_pct": (moy_1an_dec / s0 - 1.0) * 100.0,
                "moy_1an_pr_pct": (moy_1an_pr / s0 - 1.0) * 100.0,
                "ecart_1an_pts": moy_1an_dec - moy_1an_pr,
                "ecart_1an_pct": ((moy_1an_dec - moy_1an_pr) / s0) * 100.0,
                "has_5ans": has_5ans,
                "moy_5ans_dec": moy_5ans_dec,
                "moy_5ans_pr": moy_5ans_pr,
                "moy_5ans_dec_pct": (moy_5ans_dec / s0 - 1.0) * 100.0,
                "moy_5ans_pr_pct": (moy_5ans_pr / s0 - 1.0) * 100.0,
                "ecart_5ans_pts": moy_5ans_dec - moy_5ans_pr,
                "ecart_5ans_pct": ((moy_5ans_dec - moy_5ans_pr) / s0) * 100.0,
            }
        return results

    def run_multi_indices(self, list_indices: list, scenario: MarketScenario, product: AutocallProduct, taux_actualisation=0.0):
        """Évalue un produit structuré sur plusieurs indices en tirages appariés stricts (mêmes chocs Z)."""
        np.random.seed(self.seed)
        Z_chocs = np.random.normal(0, 1, size=(self.nb_trajectoires, scenario.total_jours))
        results = {}
        for idx in list_indices:
            traj_pr, traj_dec = idx.simulate(scenario, self.nb_trajectoires, Z_chocs)
            prod_idx = product.clone_for_spot(idx.niveau_initial) if hasattr(product, 'clone_for_spot') else product
            est_rappele_dec, obs_de_rappel_dec, payoffs_dec, est_rappele_pr, obs_de_rappel_pr, payoffs_pr = self.evaluer_produit(
                prod_idx, traj_pr, traj_dec, scenario, niveau_initial=idx.niveau_initial, taux_actualisation=taux_actualisation
            )
            duration_dec = self.calculer_duration(est_rappele_dec, obs_de_rappel_dec, prod_idx, scenario)
            duration_pr = self.calculer_duration(est_rappele_pr, obs_de_rappel_pr, prod_idx, scenario)
            
            # PDI
            val_fin_dec = traj_dec[:, -1]
            sous_pdi_dec = (val_fin_dec < prod_idx.niveau_pdi) & (~est_rappele_dec)
            pct_pdi_dec = np.mean(sous_pdi_dec) * 100.0
            
            val_fin_pr = traj_pr[:, -1]
            sous_pdi_pr = (val_fin_pr < prod_idx.niveau_pdi) & (~est_rappele_pr)
            pct_pdi_pr = np.mean(sous_pdi_pr) * 100.0
            
            # Levier
            levier = None
            if np.any(sous_pdi_dec):
                perte_dec = 1.0 - (np.mean(val_fin_dec[sous_pdi_dec]) / idx.niveau_initial)
                perte_pr = 1.0 - (np.mean(val_fin_pr[sous_pdi_dec]) / idx.niveau_initial)
                levier = (perte_dec / perte_pr) if perte_pr > 0 else 0.0

            results[idx.nom] = {
                "index": idx,
                "product": prod_idx,
                "traj_pr": traj_pr,
                "traj_dec": traj_dec,
                "est_rappele_dec": est_rappele_dec,
                "obs_de_rappel_dec": obs_de_rappel_dec,
                "payoffs_dec": payoffs_dec,
                "est_rappele_pr": est_rappele_pr,
                "obs_de_rappel_pr": obs_de_rappel_pr,
                "payoffs_pr": payoffs_pr,
                "duration_dec": duration_dec,
                "duration_pr": duration_pr,
                "pct_rappel_dec": np.mean(est_rappele_dec) * 100.0,
                "pct_rappel_pr": np.mean(est_rappele_pr) * 100.0,
                "moy_payoff_dec": np.mean(payoffs_dec) * 100.0,
                "moy_payoff_pr": np.mean(payoffs_pr) * 100.0,
                "pct_pdi_dec": pct_pdi_dec,
                "pct_pdi_pr": pct_pdi_pr,
                "levier_equivalent": levier
            }
        return results

    def calculer_duration(self, est_rappele, obs_de_rappel, product: AutocallProduct, scenario: MarketScenario):
        jours_par_mois = scenario.jours_par_an // 12
        jours_entre_observations = jours_par_mois * product.frequence_obs_mois
        annees_par_obs = jours_entre_observations / scenario.jours_par_an
        
        annees_rappel = obs_de_rappel[est_rappele] * annees_par_obs
        annees_non_rappel = np.full(np.sum(~est_rappele), scenario.annees)
        
        return (np.sum(annees_rappel) + np.sum(annees_non_rappel)) / len(est_rappele)

    def afficher_statistiques(self, nom_scenario, traj_pr, traj_dec, est_rappele_dec, payoffs_dec, est_rappele_pr, payoffs_pr, product: AutocallProduct, scenario: MarketScenario):
        print(f"#### Statistiques pour le {nom_scenario}\n")
        
        pct_rappel_dec = np.mean(est_rappele_dec) * 100
        pct_rappel_pr = np.mean(est_rappele_pr) * 100
        print(f"- **Pourcentage de trajectoires rappelées** : Decrement = {pct_rappel_dec:.2f}% | Price Return = {pct_rappel_pr:.2f}%")
        
        moy_payoff_dec = np.mean(payoffs_dec) * 100
        moy_payoff_pr = np.mean(payoffs_pr) * 100
        print(f"- **Payoff moyen actualisé** : Decrement = {moy_payoff_dec:.2f}% | Price Return = {moy_payoff_pr:.2f}%\n")
        
        niveau_initial = traj_dec[0, 0]
        
        reps = []
        valeurs_finales_dec = traj_dec[:, -1]
        valeurs_finales_pr = traj_pr[:, -1]
        
        en_dessous_pdi = (valeurs_finales_dec < product.niveau_pdi) & (~est_rappele_dec)
        pct_en_dessous_dec = np.mean(en_dessous_pdi) * 100
        
        en_dessous_pdi_pr = (valeurs_finales_pr < product.niveau_pdi) & (~est_rappele_pr)
        pct_en_dessous_pr = np.mean(en_dessous_pdi_pr) * 100
        
        print(f"\n#### À MATURITÉ (Année {scenario.annees}) :")
        print(f"- **Pourcentage de fois où l'indice finit en dessous du PDI** : Decrement = {pct_en_dessous_dec:.2f}% | Price Return = {pct_en_dessous_pr:.2f}%")
        
        levier_equivalent = None
        bin_stats = []
        if np.any(en_dessous_pdi):
            moy_dec_en_dessous = np.mean(valeurs_finales_dec[en_dessous_pdi])
            moy_pr_en_dessous = np.mean(valeurs_finales_pr[en_dessous_pdi])
            
            perte_dec = 1.0 - (moy_dec_en_dessous / niveau_initial)
            perte_pr = 1.0 - (moy_pr_en_dessous / niveau_initial)
            levier_equivalent = perte_dec / perte_pr if perte_pr > 0 else 0
            
            print(f"- **Position moyenne de l'indice Decrement** (pour ces cas) : {(moy_dec_en_dessous / niveau_initial) * 100:.2f}% du Spot")
            print(f"- **Position moyenne de l'indice PR** (pour ces cas) : {(moy_pr_en_dessous / niveau_initial) * 100:.2f}% du Spot")
            print(f"- **Levier Équivalent (Sévérité du Krach)** : La perte du Decrement correspond à la perte du PR multipliée par un levier de **{levier_equivalent:.2f}x**.\n")
            
            dec_sous_pdi = valeurs_finales_dec[en_dessous_pdi]
            pr_sous_pdi = valeurs_finales_pr[en_dessous_pdi]
            
            bins = [0, 10, 25, 50, 75, 90, 100]
            for i in range(len(bins)-1):
                p_low = bins[i]
                p_high = bins[i+1]
                val_high = np.percentile(dec_sous_pdi, p_high)
                
                if p_low == 0:
                    mask = dec_sous_pdi <= val_high
                else:
                    val_low = np.percentile(dec_sous_pdi, p_low)
                    mask = (dec_sous_pdi > val_low) & (dec_sous_pdi <= val_high)
                
                if np.any(mask):
                    moy_dec = np.mean(dec_sous_pdi[mask])
                    moy_pr = np.mean(pr_sous_pdi[mask])
                    label = f"{p_low}%-{p_high}%"
                    bin_stats.append({"label": label, "moy_dec": (moy_dec/niveau_initial)*100, "moy_pr": (moy_pr/niveau_initial)*100})
            
            bin_stats.append({
                "label": "Moyenne Globale", 
                "moy_dec": (moy_dec_en_dessous / niveau_initial) * 100, 
                "moy_pr": (moy_pr_en_dessous / niveau_initial) * 100,
                "is_global": True
            })
            
            pct_levels = [10, 25, 50, 75, 90]
            pct_values = [np.percentile(dec_sous_pdi, p) for p in pct_levels]
            
            print("\n**Trajectoires représentatives (Analyse par centiles)**")
            
            for p, val in zip(pct_levels, pct_values):
                idx = np.argmin(np.abs(dec_sous_pdi - val))
                original_idx = np.where(en_dessous_pdi)[0][idx]
                
                print(f"- **Top {p}%** : Niveau cible Decrement = {(val/niveau_initial)*100:.2f}% | PR équivalent = {(pr_sous_pdi[idx]/niveau_initial)*100:.2f}%")
                reps.append(((traj_pr[original_idx]/niveau_initial)*100, (traj_dec[original_idx]/niveau_initial)*100, f"Top {p}%"))
        else:
            print("- Aucun scénario ne finit en dessous du PDI à maturité.")
            
        return reps, bin_stats, levier_equivalent

    def _add_background_regimes_plotly(self, fig, scenario):
        """Ajoute des teintes de fond très légères selon le signe du drift :
        - Vert très subtil si drift positif
        - Rouge très subtil si drift négatif
        """
        for regime in scenario.config_regimes:
            r_perf = regime.get('r_perf', 0.0)
            if r_perf > 0:
                color = '#22c55e'  # Vert discret
                opacity = 0.06
            elif r_perf < 0:
                color = '#ef4444'  # Rouge discret
                opacity = 0.06
            else:
                color = '#94a3b8'  # Gris neutre
                opacity = 0.04

            fig.add_vrect(
                x0=regime['annee_debut'],
                x1=regime['annee_fin'],
                fillcolor=color,
                opacity=opacity,
                line_width=0,
                layer="below"
            )

    def _add_product_levels_plotly(self, fig, product, scenario, niveau_initial):
        """Ajoute les barrières du produit Autocall pour Plotly"""
        if product is None:
            return
        pdi_pct = (product.niveau_pdi / niveau_initial) * 100
        rappel_pct = (product.barriere_rappel / niveau_initial) * 100
        
        fig.add_hline(y=pdi_pct, line_dash="dash", line_color="red", line_width=2,
                      annotation_text=f"PDI ({pdi_pct:.0f}%)", annotation_position="bottom right")
        
        if hasattr(product, 'barriere_coupon') and product.barriere_coupon is not None:
            coupon_pct = (product.barriere_coupon / niveau_initial) * 100
            fig.add_hline(y=coupon_pct, line_dash="dot", line_color="green", line_width=1.5,
                          annotation_text=f"Coupon ({coupon_pct:.0f}%)", annotation_position="top left")
        
        if product.degressivite == 0.0:
            fig.add_hline(y=rappel_pct, line_dash="dashdot", line_color="purple", line_width=2,
                          annotation_text=f"Rappel ({rappel_pct:.0f}%)", annotation_position="top right")
        else:
            import plotly.graph_objects as go
            jours_par_mois = scenario.jours_par_an // 12
            jours_entre_observations = jours_par_mois * product.frequence_obs_mois
            baisse_en_pct = rappel_pct * (product.degressivite / 100.0)
            
            x_barriere = [0]
            y_barriere = [rappel_pct]
            
            nb_observations_passees = 0
            
            for t in range(1, scenario.total_jours + 1):
                if (t % jours_entre_observations == 0) and (t >= jours_par_mois * product.non_call_period_mois):
                    annee = t / scenario.jours_par_an
                    
                    # Fin de la marche actuelle
                    barriere_actuelle = rappel_pct - (nb_observations_passees * baisse_en_pct)
                    x_barriere.append(annee)
                    y_barriere.append(barriere_actuelle)
                    
                    # Début de la marche suivante
                    nb_observations_passees += 1
                    barriere_prochaine = rappel_pct - (nb_observations_passees * baisse_en_pct)
                    x_barriere.append(annee)
                    y_barriere.append(barriere_prochaine)
                    
            # Dernière marche jusqu'à la fin
            x_barriere.append(scenario.annees)
            y_barriere.append(rappel_pct - (nb_observations_passees * baisse_en_pct))
            
            fig.add_trace(go.Scatter(x=x_barriere, y=y_barriere, mode='lines', 
                                     line=dict(color='purple', width=2, dash='dashdot'), 
                                     name=f'Rappel Dégressif (-{product.degressivite}%/obs)', showlegend=False))

    def plot_results(self, nom_scenario, traj_pr, traj_dec, reps_scen=None, product=None, scenario=None, index=None):
        """Génère et affiche les graphiques interactifs Plotly"""
        import numpy as np
        import plotly.graph_objects as go
        axe_temps = np.linspace(0, scenario.annees, scenario.total_jours + 1)
        titre_base = nom_scenario
        niveau_initial = index.niveau_initial if index is not None else traj_dec[0, 0]
        
        # ==========================================
        # GRAPHIQUE 1 : Analyse par Quartiles
        # ==========================================
        fig1 = go.Figure()
        
        colors = ['#d73027', '#fc8d59', '#fee08b', '#d9ef8b', '#1a9850']
        
        if reps_scen is not None:
            for idx_rep in range(len(reps_scen)-1, -1, -1):
                rep = reps_scen[idx_rep]
                if rep[0] is not None:
                    t_pr, t_dec, label = rep
                    c = colors[idx_rep % len(colors)]
                    fig1.add_trace(go.Scatter(x=axe_temps, y=t_dec, mode='lines', 
                                              line=dict(color=c, width=2), 
                                              name=f'Dec ({label})',
                                              legendgroup=label))
                    fig1.add_trace(go.Scatter(x=axe_temps, y=t_pr, mode='lines', 
                                              line=dict(color=c, width=1, dash='dash'), 
                                              opacity=0.7, name=f'PR équivalent ({label})',
                                              legendgroup=label))
                    
            self._add_background_regimes_plotly(fig1, scenario)
            self._add_product_levels_plotly(fig1, product, scenario, niveau_initial)
            
            fig1.update_layout(
                title="Trajectoires Temporelles Représentatives (Cas sous PDI)",
                xaxis_title="Années", yaxis_title="Niveau (% du Spot)",
                xaxis=dict(range=[0, scenario.annees]), yaxis=dict(rangemode='tozero'),
                legend=dict(orientation="h", yanchor="bottom", y=-0.2, xanchor="left", x=0),
                margin=dict(l=40, r=40, t=60, b=80), hovermode="x unified")

        # ==========================================
        # GRAPHIQUE 2 : Le nuage de points
        # ==========================================
        fig2 = go.Figure()
        
        valeurs_finales_toutes_dec = traj_dec[:, -1]
        pct_levels = [90, 75, 50, 25, 10]
        colors_pct_map = {90: '#1a9850', 75: '#d9ef8b', 50: '#fee08b', 25: '#fc8d59', 10: '#d73027'}
        
        max_y_display = 200
        for p in pct_levels:
            val_cible = np.percentile(valeurs_finales_toutes_dec, p)
            idx_closest = np.argmin(np.abs(valeurs_finales_toutes_dec - val_cible))
            t_dec = (traj_dec[idx_closest] / niveau_initial) * 100
            t_pr = (traj_pr[idx_closest] / niveau_initial) * 100
            c = colors_pct_map[p]
            
            if p == 50:
                max_y_display = max(200, np.max(t_dec)*1.2)
            
            label = f"Top {p}%"
            fig2.add_trace(go.Scatter(x=axe_temps, y=t_dec, mode='lines', 
                                      line=dict(color=c, width=2.5), 
                                      name=f'Dec ({label})',
                                      legendgroup=label))
            fig2.add_trace(go.Scatter(x=axe_temps, y=t_pr, mode='lines', 
                                      line=dict(color=c, width=1.5, dash='dot'), 
                                      name=f'PR équivalent ({label})',
                                      legendgroup=label))
        
        self._add_background_regimes_plotly(fig2, scenario)
        self._add_product_levels_plotly(fig2, product, scenario, niveau_initial)
        
        fig2.update_layout(
            title="Trajectoires Temporelles par Centiles Finaux (Top 10% à 90%)",
            xaxis_title="Années", yaxis_title="Niveau (% du Spot)",
            xaxis=dict(range=[0, scenario.annees]), yaxis=dict(range=[0, max_y_display]),
            legend=dict(orientation="h", yanchor="bottom", y=-0.2, xanchor="left", x=0),
            margin=dict(l=40, r=40, t=60, b=80), hovermode="x unified")
                           
        return fig1, fig2

    def plot_distributions(self, traj_pr, traj_dec, est_rappele_pr=None, est_rappele_dec=None, product=None, scenario=None):
        import plotly.graph_objects as go
        from plotly.subplots import make_subplots
        import numpy as np
        
        nb_trajectoires = traj_dec.shape[0]
        
        # 1. Distribution des niveaux finaux (sans tenir compte des rappels)
        valeurs_finales_dec = np.clip(traj_dec[:, -1], a_min=None, a_max=5000)
        valeurs_finales_pr = np.clip(traj_pr[:, -1], a_min=None, a_max=5000)
        
        tickvals_dist = list(range(0, 5001, 500))
        ticktext_dist = [str(v) if v < 5000 else "5000+" for v in tickvals_dist]
        
        # Graphique Decrement
        fig_dist_dec = go.Figure()
        fig_dist_dec.add_trace(go.Histogram(
            x=valeurs_finales_dec, histnorm='percent', autobinx=False, 
            xbins=dict(start=0, end=5050, size=50), name="Decrement", 
            marker_color='blue', opacity=0.75,
            hovertemplate="Intervalle : %{x} pts<br>Proportion : %{y:.2f}% du total<extra></extra>"
        ))
        if product is not None:
            fig_dist_dec.add_vline(x=product.niveau_pdi, line_dash="dash", line_color="red", annotation_text="PDI")

        fig_dist_dec.update_layout(
            title="Distribution des Niveaux Finaux (Decrement - Plafonné à 5000)",
            xaxis_title="Niveau Final (pts)", 
            yaxis_title="Pourcentage des trajectoires totales (%)",
            yaxis=dict(ticksuffix="%"),
            xaxis=dict(range=[0, 5200], tickvals=tickvals_dist, ticktext=ticktext_dist)
        )
        
        # Graphique Price Return
        fig_dist_pr = go.Figure()
        fig_dist_pr.add_trace(go.Histogram(
            x=valeurs_finales_pr, histnorm='percent', autobinx=False, 
            xbins=dict(start=0, end=5050, size=50), name="Price Return", 
            marker_color='orange', opacity=0.75,
            hovertemplate="Intervalle : %{x} pts<br>Proportion : %{y:.2f}% du total<extra></extra>"
        ))
        if product is not None:
            fig_dist_pr.add_vline(x=product.niveau_pdi, line_dash="dash", line_color="red", annotation_text="PDI (Indicatif)")
        fig_dist_pr.update_layout(
            title="Distribution des Niveaux Finaux (Price Return - Plafonné à 5000)",
            xaxis_title="Niveau Final (pts)", 
            yaxis_title="Pourcentage des trajectoires totales (%)",
            yaxis=dict(ticksuffix="%"),
            xaxis=dict(range=[0, 5200], tickvals=tickvals_dist, ticktext=ticktext_dist)
        )

        if product is None or est_rappele_pr is None or est_rappele_dec is None:
            return fig_dist_dec, fig_dist_pr, None, None, None

        # 1. Bis. Distribution des trajectoires non rappelées
        valeurs_non_rappelees_dec = np.clip(traj_dec[~est_rappele_dec, -1], a_min=None, a_max=5000)
        valeurs_non_rappelees_pr = np.clip(traj_pr[~est_rappele_pr, -1], a_min=None, a_max=5000)
        
        # Poids proportionnels au NOMBRE TOTAL DE TRAJECTOIRES
        poids_non_rappelees_dec = np.full(len(valeurs_non_rappelees_dec), 100.0 / nb_trajectoires)
        poids_non_rappelees_pr = np.full(len(valeurs_non_rappelees_pr), 100.0 / nb_trajectoires)
        
        # Graphique Decrement (Trajectoires Non Rappelées uniquement, rapportées au total)
        fig_dist_dec_reelle = go.Figure()
        if len(valeurs_non_rappelees_dec) > 0:
            fig_dist_dec_reelle.add_trace(go.Histogram(
                x=valeurs_non_rappelees_dec, y=poids_non_rappelees_dec, histfunc='sum', autobinx=False, 
                xbins=dict(start=0, end=5050, size=50), name="Decrement (Non Rappelé)", 
                marker_color='darkblue', opacity=0.75,
                hovertemplate="Niveau : %{x} pts<br>Proportion : %{y:.2f}% du total<extra></extra>"
            ))
        fig_dist_dec_reelle.add_vline(x=product.niveau_pdi, line_dash="dash", line_color="red", annotation_text="PDI")
        fig_dist_dec_reelle.update_layout(
            title="Distribution des Trajectoires Non Rappelées (Decrement)",
            xaxis_title="Niveau Final à Maturité (pts)", 
            yaxis_title="Pourcentage des trajectoires totales (%)",
            yaxis=dict(ticksuffix="%"),
            xaxis=dict(range=[0, 5200], tickvals=tickvals_dist, ticktext=ticktext_dist)
        )
        
        # Graphique Price Return (Trajectoires Non Rappelées uniquement, rapportées au total)
        fig_dist_pr_reelle = go.Figure()
        if len(valeurs_non_rappelees_pr) > 0:
            fig_dist_pr_reelle.add_trace(go.Histogram(
                x=valeurs_non_rappelees_pr, y=poids_non_rappelees_pr, histfunc='sum', autobinx=False, 
                xbins=dict(start=0, end=5050, size=50), name="Price Return (Non Rappelé)", 
                marker_color='darkorange', opacity=0.75,
                hovertemplate="Niveau : %{x} pts<br>Proportion : %{y:.2f}% du total<extra></extra>"
            ))
        fig_dist_pr_reelle.add_vline(x=product.niveau_pdi, line_dash="dash", line_color="red", annotation_text="PDI (Indicatif)")
        fig_dist_pr_reelle.update_layout(
            title="Distribution des Trajectoires Non Rappelées (Price Return)",
            xaxis_title="Niveau Final à Maturité (pts)", 
            yaxis_title="Pourcentage des trajectoires totales (%)",
            yaxis=dict(ticksuffix="%"),
            xaxis=dict(range=[0, 5200], tickvals=tickvals_dist, ticktext=ticktext_dist)
        )
        
        # 2. Distribution des dates de rappel (Decrement et Price Return)
        _, obs_de_rappel_dec = product.evaluate(traj_dec, scenario, nb_trajectoires)
        _, obs_de_rappel_pr = product.evaluate(traj_pr, scenario, nb_trajectoires)
        
        valid_obs_dec = obs_de_rappel_dec[est_rappele_dec]
        unique_obs_dec, counts_dec = np.unique(valid_obs_dec, return_counts=True)
        dict_dec = dict(zip(unique_obs_dec, counts_dec))
        
        valid_obs_pr = obs_de_rappel_pr[est_rappele_pr]
        unique_obs_pr, counts_pr = np.unique(valid_obs_pr, return_counts=True)
        dict_pr = dict(zip(unique_obs_pr, counts_pr))
        
        all_obs = np.array(sorted(list(set(unique_obs_dec) | set(unique_obs_pr))))
        if len(all_obs) == 0:
            all_obs = np.array([1])
            
        counts_pct_dec = [(dict_dec.get(o, 0) / nb_trajectoires) * 100.0 for o in all_obs]
        counts_pct_pr = [(dict_pr.get(o, 0) / nb_trajectoires) * 100.0 for o in all_obs]
        
        fig_dist_rappel = go.Figure()
        
        # Decrement
        fig_dist_rappel.add_trace(go.Bar(
            x=all_obs, y=counts_pct_dec, name="Decrement", 
            marker_color='blue', opacity=0.75,
            hovertemplate="Observation %{x} (Decrement) : %{y:.2f}% des trajectoires<extra></extra>"
        ))
        
        # Price Return (Vert transparent)
        fig_dist_rappel.add_trace(go.Bar(
            x=all_obs, y=counts_pct_pr, name="Price Return", 
            marker_color='rgba(46, 204, 113, 0.65)',
            hovertemplate="Observation %{x} (Price Return) : %{y:.2f}% des trajectoires<extra></extra>"
        ))
        
        fig_dist_rappel.update_layout(
            title="Distribution des Périodes de Rappel (Autocall Decrement vs Price Return)",
            xaxis_title=f"Numéro d'observation (Fréquence : {product.frequence_obs_mois} mois)", 
            yaxis_title="Pourcentage des trajectoires (%)",
            yaxis=dict(ticksuffix="%"),
            xaxis=dict(dtick=1),
            barmode='overlay',
            hovermode="x unified"
        )
        
        return fig_dist_dec, fig_dist_pr, fig_dist_rappel, fig_dist_dec_reelle, fig_dist_pr_reelle

    def plot_binned_averages(self, bin_stats):
        import plotly.graph_objects as go
        
        labels = [b['label'] for b in bin_stats]
        dec_vals = [b['moy_dec'] for b in bin_stats]
        pr_vals = [b['moy_pr'] for b in bin_stats]        
        
        colors_dec = ['darkblue' if b.get('is_global') else 'blue' for b in bin_stats]
        colors_pr = ['darkorange' if b.get('is_global') else 'orange' for b in bin_stats]

        fig = go.Figure()
        fig.add_trace(go.Bar(
            x=labels, y=dec_vals,
            name='Decrement', marker_color=colors_dec
        ))
        fig.add_trace(go.Bar(
            x=labels, y=pr_vals,
            name='Price Return', marker_color=colors_pr
        ))
        
        fig.update_layout(
            title="Niveaux Moyens par Tranches de Centiles (Sous PDI)",
            xaxis_title="Tranches de Centiles",
            yaxis_title="Niveau Final Moyen (pts)",
            barmode='group',
            plot_bgcolor='white',
            hovermode="x unified"
        )
        
        return fig

    def plot_dispersion_ecarts_violons(self, traj_pr, traj_dec, scenario, niveau_initial=None, return_stats=False,
                                       product=None, est_rappele_dec=None, obs_de_rappel_dec=None):
        import plotly.graph_objects as go
        import numpy as np
        
        if niveau_initial is None:
            niveau_initial = traj_dec[0, 0]
            
        fig = go.Figure()
        
        nb_annees = scenario.annees
        means = []
        medians = []
        mins = []
        maxs = []
        stats_data = []
        x_mean_labels = []
        
        is_pricing_mode = (est_rappele_dec is not None and obs_de_rappel_dec is not None and product is not None)
        if is_pricing_mode:
            jours_par_mois = scenario.jours_par_an // 12
            freq_obs = getattr(product, 'frequence_obs_mois', 3)
            jours_entre_obs = jours_par_mois * freq_obs
            t_rappel = obs_de_rappel_dec * jours_entre_obs
            nb_total = traj_dec.shape[0]

        for idx, k in enumerate(range(1, nb_annees + 1)):
            t_idx = k * scenario.jours_par_an
            label_annee = f"Année {k}"
            
            if is_pricing_mode:
                # Trajectoires actives à la date anniversaire k (non rappelées strictement avant t_idx)
                mask_active = ~(est_rappele_dec & (t_rappel < t_idx))
                n_active = int(np.sum(mask_active))
                pct_active = (n_active / nb_total) * 100.0
                
                if n_active == 0:
                    stats_data.append({
                        "Année": label_annee,
                        "Actives": "0 (0.0%)",
                        "Médiane": None,
                        "Moyenne": None,
                        "Q25": None,
                        "Q75": None,
                        "IQR": None,
                        "Min": None,
                        "Max": None
                    })
                    continue
                    
                ecart_k = ((traj_dec[mask_active, t_idx] - traj_pr[mask_active, t_idx]) / niveau_initial) * 100.0
            else:
                n_active = traj_dec.shape[0]
                pct_active = 100.0
                ecart_k = ((traj_dec[:, t_idx] - traj_pr[:, t_idx]) / niveau_initial) * 100.0
            
            med = float(np.median(ecart_k))
            mn = float(np.mean(ecart_k))
            q25 = float(np.percentile(ecart_k, 25))
            q75 = float(np.percentile(ecart_k, 75))
            iqr = q75 - q25
            p1 = float(np.percentile(ecart_k, 1.0))
            p99 = float(np.percentile(ecart_k, 99.0))
            val_min = float(np.min(ecart_k))
            val_max = float(np.max(ecart_k))
            
            medians.append(med)
            means.append(mn)
            mins.append(val_min)
            maxs.append(val_max)
            x_mean_labels.append(label_annee)
            
            stat_row = {
                "Année": label_annee,
                "Médiane": med,
                "Moyenne": mn,
                "Q25": q25,
                "Q75": q75,
                "IQR": iqr,
                "P1": p1,
                "P99": p99,
                "Min": val_min,
                "Max": val_max
            }
            if is_pricing_mode:
                stat_row["Actives"] = f"{n_active:,} ({pct_active:.1f}%)"
            stats_data.append(stat_row)
            
            # Hover personnalisé indiquant les trajectoires actives en pricing et les bornes P1-P99
            if is_pricing_mode:
                hover_info = (
                    f"<b>{label_annee}</b><br>"
                    f"Écart : <b>%{{y:+.2f}}%</b><br>"
                    f"Moustaches [P1, P99] : <b>[{p1:+.2f}%, {p99:+.2f}%]</b><br>"
                    f"Trajectoires encore actives : <b>{n_active:,} ({pct_active:.1f}%)</b>"
                    "<extra></extra>"
                )
            else:
                hover_info = (
                    f"<b>{label_annee}</b><br>"
                    f"Écart : <b>%{{y:+.2f}}%</b><br>"
                    f"Moustaches [P1, P99] : <b>[{p1:+.2f}%, {p99:+.2f}%]</b>"
                    "<extra></extra>"
                )
            
            # Pour le tracé du violon, on restreint aux 98% de trajectoires au cœur du marché (P1 à P99)
            # afin d'éviter qu'une poignée d'extrêmes browniens à 5 sigmas n'écrase l'axe Y
            ecart_plot = ecart_k[(ecart_k >= p1) & (ecart_k <= p99)]
            if len(ecart_plot) == 0:
                ecart_plot = ecart_k
            
            # Violon avec boîte à moustache intégrée (Raincloud / Box-in-Violin)
            fig.add_trace(go.Violin(
                y=ecart_plot,
                x=[label_annee] * len(ecart_plot),
                name=label_annee,
                box_visible=True,
                box_width=0.38,
                box_fillcolor='rgba(255, 255, 255, 0.95)', # Boîte blanche très lisible et nette
                box_line_color='#0f172a', # Bordure sombre pour un contraste maximal
                box_line_width=1.8,
                meanline_visible=False,
                points=False,
                scalemode='width', # Largeur égale et harmonieuse sur chaque année
                spanmode='hard', # Arrêt net aux valeurs réelles extrêmes
                line_color='#2563eb', # Contour bleu électrique
                line_width=1.5,
                fillcolor='rgba(37, 99, 235, 0.12)', # Voile bleu glacier translucide
                showlegend=False,
                hovertemplate=hover_info
            ))
            
            # Moustache verticale jusqu'au Centile 99% (P99)
            fig.add_shape(
                type='line', xref='x', yref='y',
                x0=idx, x1=idx, y0=q75, y1=p99,
                line=dict(color='#0f172a', width=1.6),
                layer='above'
            )
            # Barre horizontale (chapeau de moustache) au niveau de P99
            fig.add_shape(
                type='line', xref='x', yref='y',
                x0=idx - 0.12, x1=idx + 0.12, y0=p99, y1=p99,
                line=dict(color='#0f172a', width=2.0),
                layer='above'
            )
            
            # Moustache verticale jusqu'au Centile 1% (P1)
            fig.add_shape(
                type='line', xref='x', yref='y',
                x0=idx, x1=idx, y0=q25, y1=p1,
                line=dict(color='#0f172a', width=1.6),
                layer='above'
            )
            # Barre horizontale (chapeau de moustache) au niveau de P1
            fig.add_shape(
                type='line', xref='x', yref='y',
                x0=idx - 0.12, x1=idx + 0.12, y0=p1, y1=p1,
                line=dict(color='#0f172a', width=2.0),
                layer='above'
            )
            
            # Barre rouge horizontale pour la médiane au coeur de chaque boîte (trait fin 1px)
            fig.add_shape(
                type='line',
                xref='x', yref='y',
                x0=idx - 0.19, x1=idx + 0.19,
                y0=med, y1=med,
                line=dict(color='#dc2626', width=1.0),
                layer='above'
            )

        # Entrée de légende pour la médiane (barre rouge dans chaque boîte)
        fig.add_trace(go.Scatter(
            x=[None], y=[None], mode='lines',
            line=dict(color='#dc2626', width=1.0),
            name='Médiane (Ligne rouge)',
            showlegend=True
        ))
        
        # Moyenne : Croix noire ultra-fine (symbole natif Plotly 'x-thin' en trait simple)
        fig.add_trace(go.Scatter(
            x=x_mean_labels, y=means, mode='markers',
            marker=dict(symbol='x-thin', size=11, color='#0f172a', line=dict(width=1.0, color='#0f172a')),
            name='Moyenne (Croix)',
            hovertemplate="<b>%{x}</b><br>Moyenne : <b>%{y:+.2f}%</b> du Spot<extra></extra>"
        ))
        
        if is_pricing_mode:
            chart_title = "<b>Dispersion des Écarts (Décrément - Price Return) sur Trajectoires Actives</b>"
        else:
            chart_title = "<b>Dispersion des Écarts (Décrément - Price Return) par Année</b>"
            
        fig.update_layout(
            title=dict(
                text=chart_title,
                font=dict(size=17, color='#0f172a')
            ),
            xaxis=dict(
                title=dict(text="<b>Horizon Temporel (Année)</b>", font=dict(size=14, color='#0f172a')),
                showgrid=False,
                tickfont=dict(size=13, color='#0f172a')
            ),
            yaxis=dict(
                title=dict(text="<b>Écart : (Dec - PR) / Spot Initial (%)</b>", font=dict(size=14, color='#0f172a')),
                ticksuffix="%",
                zeroline=False, # Pas de ligne à 0% demandée
                gridcolor='#f1f5f9',
                gridwidth=1,
                tickfont=dict(size=12, color='#0f172a')
            ),
            height=750,
            plot_bgcolor='#ffffff',
            paper_bgcolor='#ffffff',
            hovermode="closest",
            legend=dict(
                orientation="h",
                yanchor="bottom",
                y=1.02,
                xanchor="right",
                x=1,
                bgcolor="rgba(255, 255, 255, 0.9)",
                bordercolor="#cbd5e1",
                borderwidth=1,
                font=dict(size=12, color='#0f172a')
            ),
            margin=dict(l=60, r=40, t=95, b=60)
        )
        
        if return_stats:
            return fig, stats_data
        return fig

    def plot_multi_trajectoires(self, results: dict, scenario: MarketScenario):
        """Affiche les trajectoires médianes et fuseaux [P10-P90] de plusieurs indices normalisés à 100%."""
        fig = go.Figure()
        self._add_background_regimes_plotly(fig, scenario)
        
        axe_temps = np.linspace(0, scenario.annees, scenario.total_jours + 1)
        palette = ['#2563eb', '#dc2626', '#16a34a', '#9333ea', '#ea580c', '#0891b2']
        nb_indices = len(results)
        
        # Pour chaque indice : son fuseau P10-P90, sa médiane Décrément et son propre Price Return médian
        for idx_i, (nom_idx, data) in enumerate(results.items()):
            color = palette[idx_i % len(palette)]
            idx_obj = data["index"]
            s0 = idx_obj.niveau_initial
            
            dec_pct = (data["traj_dec"] / s0) * 100.0
            pr_pct = (data["traj_pr"] / s0) * 100.0
            
            med_dec = np.median(dec_pct, axis=0)
            p10 = np.percentile(dec_pct, 10, axis=0)
            p90 = np.percentile(dec_pct, 90, axis=0)
            med_pr = np.median(pr_pct, axis=0)
            
            # Fuseau P10 - P90 (Décrément)
            fig.add_trace(go.Scatter(
                x=axe_temps, y=p90, mode='lines',
                line=dict(width=0),
                showlegend=False,
                legendgroup=nom_idx,
                hoverinfo='skip'
            ))
            fig.add_trace(go.Scatter(
                x=axe_temps, y=p10, mode='lines',
                line=dict(width=0),
                fill='tonexty',
                fillcolor=f"rgba({int(color[1:3], 16)}, {int(color[3:5], 16)}, {int(color[5:7], 16)}, 0.12)",
                name=f"{nom_idx} [P10-P90]",
                legendgroup=nom_idx,
                showlegend=False
            ))
            # Médiane Décrément (trait plein épais)
            dec_name = f"{nom_idx} (Décrément)" if nb_indices > 1 else f"{nom_idx} (Décrément)"
            fig.add_trace(go.Scatter(
                x=axe_temps, y=med_dec, mode='lines',
                line=dict(color=color, width=2.8),
                name=dec_name,
                legendgroup=nom_idx,
                showlegend=True,
                hovertemplate=f"<b>{nom_idx} (Décrément)</b><br>Horizon: %{{x:.2f}} ans<br>Niveau: <b>%{{y:.1f}}%</b><extra></extra>"
            ))
            # Médiane Price Return propre à cet indice (strictement la médiane en pointillé, même couleur, sans distribution)
            pr_name = f"{nom_idx} (Price Return)"
            fig.add_trace(go.Scatter(
                x=axe_temps, y=med_pr, mode='lines',
                line=dict(color=color, width=2.0, dash='dash'),
                name=pr_name,
                legendgroup=nom_idx,
                showlegend=True,
                hovertemplate=f"<b>{nom_idx} (Price Return)</b><br>Horizon: %{{x:.2f}} ans<br>Niveau PR Médian: <b>%{{y:.1f}}%</b><extra></extra>"
            ))
            
        fig.update_layout(
            title="<b>Comparaison Temporelle des Indices (% du Spot Initial S0)</b>",
            xaxis_title="<b>Horizon Temporel (Années)</b>",
            yaxis_title="<b>Niveau de l'Indice (% de S0)</b>",
            template="plotly_white",
            legend=dict(
                orientation="h",
                yanchor="top",
                y=-0.22,
                xanchor="center",
                x=0.5,
                bgcolor="rgba(255,255,255,0.9)",
                bordercolor="#e2e8f0",
                borderwidth=1
            ),
            margin=dict(l=60, r=40, t=60, b=90)
        )
        return fig

    def plot_multi_courbes_ecarts(self, results: dict, scenario: MarketScenario, filter_active: bool = False, product: AutocallProduct = None):
        """Affiche l'évolution temporelle continue de l'écart (Dec - PR)/S0 pour chaque indice :
        Médiane en trait plein, couloir interquartile [Q25 - Q75] en voile translucide.
        Supporte le conditionnement aux trajectoires actives (non rappelées) en mode pricing.
        """
        fig = go.Figure()
        self._add_background_regimes_plotly(fig, scenario)
        
        axe_temps = np.linspace(0, scenario.annees, scenario.total_jours + 1)
        palette = ['#2563eb', '#dc2626', '#16a34a', '#9333ea', '#ea580c', '#0891b2']
        
        jours_par_mois = scenario.jours_par_an // 12
        jours_entre_obs = (jours_par_mois * product.frequence_obs_mois) if (product is not None) else None
        
        for idx_i, (nom_idx, data) in enumerate(results.items()):
            color = palette[idx_i % len(palette)]
            idx_obj = data["index"]
            s0 = idx_obj.niveau_initial
            
            traj_dec = data["traj_dec"]
            traj_pr = data["traj_pr"]
            
            # Matrice des écarts journaliers en % de S0
            mat_ecarts = ((traj_dec - traj_pr) / s0) * 100.0
            
            med_courbe = np.zeros(scenario.total_jours + 1)
            q25_courbe = np.zeros(scenario.total_jours + 1)
            q75_courbe = np.zeros(scenario.total_jours + 1)
            
            if filter_active and ("est_rappele_dec" in data) and (jours_entre_obs is not None):
                est_rappele = data["est_rappele_dec"]
                obs_rappel = data["obs_de_rappel_dec"]
                nb_obs = int(scenario.total_jours // jours_entre_obs)
                
                for k in range(nb_obs + 1):
                    if k == 0:
                        j_start = 0
                        j_end = min(scenario.total_jours + 1, jours_entre_obs)
                        actif = np.ones(len(est_rappele), dtype=bool)
                    else:
                        j_start = k * jours_entre_obs
                        j_end = min(scenario.total_jours + 1, (k + 1) * jours_entre_obs) if k < nb_obs else scenario.total_jours + 1
                        actif = (~est_rappele) | (obs_rappel > k)
                        
                    if np.any(actif) and j_start < scenario.total_jours + 1:
                        tranche = mat_ecarts[actif, j_start:j_end]
                        med_courbe[j_start:j_end] = np.median(tranche, axis=0)
                        q25_courbe[j_start:j_end] = np.percentile(tranche, 25, axis=0)
                        q75_courbe[j_start:j_end] = np.percentile(tranche, 75, axis=0)
                    elif j_start < scenario.total_jours + 1:
                        med_courbe[j_start:j_end] = np.nan
                        q25_courbe[j_start:j_end] = np.nan
                        q75_courbe[j_start:j_end] = np.nan
            else:
                med_courbe = np.median(mat_ecarts, axis=0)
                q25_courbe = np.percentile(mat_ecarts, 25, axis=0)
                q75_courbe = np.percentile(mat_ecarts, 75, axis=0)
                
            rgb_col = f"{int(color[1:3], 16)}, {int(color[3:5], 16)}, {int(color[5:7], 16)}"
            
            # Borne haute Q75
            fig.add_trace(go.Scatter(
                x=axe_temps, y=q75_courbe, mode='lines',
                line=dict(width=0),
                showlegend=False,
                legendgroup=nom_idx,
                hoverinfo='skip'
            ))
            # Borne basse Q25 + Voile translucide
            fig.add_trace(go.Scatter(
                x=axe_temps, y=q25_courbe, mode='lines',
                line=dict(width=0),
                fill='tonexty',
                fillcolor=f"rgba({rgb_col}, 0.15)",
                name=f"{nom_idx} [Q25 - Q75]",
                legendgroup=nom_idx,
                showlegend=False
            ))
            # Médiane (trait plein épais)
            fig.add_trace(go.Scatter(
                x=axe_temps, y=med_courbe, mode='lines',
                line=dict(color=color, width=2.8),
                name=nom_idx,
                legendgroup=nom_idx,
                showlegend=True,
                hovertemplate=f"<b>{nom_idx}</b><br>Horizon: %{{x:.2f}} ans<br>Écart Médian: %{{y:+.2f}}%<extra></extra>"
            ))
            
        # Ligne de parité Décrément = PR (0%)
        fig.add_hline(
            y=0, line_dash="dash", line_color="#475569", line_width=1.5,
            annotation_text="Parité Décrément = PR (0%)", annotation_position="bottom right",
            annotation_font=dict(size=11, color="#475569")
        )
        
        titre_actif = " sur Trajectoires Non Rappelées" if filter_active else ""
        fig.update_layout(
            title=f"<b>Évolution Temporelle des Écarts (Décrément - Price Return){titre_actif}</b>",
            xaxis_title="<b>Horizon Temporel (Années)</b>",
            yaxis_title="<b>Écart : (Dec - PR) / S0 (%)</b>",
            template="plotly_white",
            legend=dict(
                orientation="h",
                yanchor="top",
                y=-0.22,
                xanchor="center",
                x=0.5,
                bgcolor="rgba(255,255,255,0.9)",
                bordercolor="#e2e8f0",
                borderwidth=1
            ),
            margin=dict(l=60, r=40, t=60, b=90)
        )
        return fig

    def plot_multi_dispersion_ecarts(self, results: dict, scenario: MarketScenario):
        """Affiche des boîtes à moustaches comparant la dispersion de l'écart (Dec - PR)/S0 à maturité pour chaque indice."""
        import re
        fig = go.Figure()
        palette = ['#2563eb', '#dc2626', '#16a34a', '#9333ea', '#ea580c', '#0891b2']
        
        for idx_i, (nom_idx, data) in enumerate(results.items()):
            color = palette[idx_i % len(palette)]
            s0 = float(data["index"].niveau_initial) if (data["index"].niveau_initial and float(data["index"].niveau_initial) > 0) else 1000.0
            diff = data["traj_dec"][:, -1] - data["traj_pr"][:, -1]
            ecart_maturite_pct = (diff / s0) * 100.0
            ecart_maturite_pct = ecart_maturite_pct[np.isfinite(ecart_maturite_pct)]
            
            if len(ecart_maturite_pct) == 0:
                continue
                
            p1 = np.percentile(ecart_maturite_pct, 1)
            p99 = np.percentile(ecart_maturite_pct, 99)
            sub = ecart_maturite_pct[(ecart_maturite_pct >= p1) & (ecart_maturite_pct <= p99)]
            
            # Nom court pour l'axe horizontal pour éviter les chevauchements
            m = re.search(r'\(([^)]+)\)$', nom_idx.strip())
            ticker_short = m.group(1) if m else ((nom_idx[:25] + '...') if len(nom_idx) > 25 else nom_idx)
            x_label = f"Indice {idx_i + 1} : {ticker_short}"
            
            fig.add_trace(go.Box(
                y=sub,
                name=x_label,
                marker_color=color,
                boxpoints=False,
                whiskerwidth=0.4,
                line_width=1.8
            ))
            
        fig.add_hline(y=0, line_dash="dash", line_color="#94a3b8", line_width=1.5)
        fig.update_layout(
            title="<b>Dispersion Comparée de l'Écart (Décrément - Price Return) à Maturité</b>",
            yaxis_title="<b>Écart (Dec - PR) / S0 (%)</b>",
            template="plotly_white",
            showlegend=False,
            xaxis=dict(tickangle=0),
            margin=dict(l=60, r=40, t=50, b=50)
        )
        return fig

    def plot_pricing_kpis_bars(self, results: dict):
        """Graphique comparatif des indicateurs de pricing en 2 volets distincts :
        1. Volet Risque/Issues : Probabilités d'Autocall, Remboursement 100% et PDI (échelle 0-100%).
        2. Volet Rendement : TRA Moyen et TRA Médian (échelle TRA %).
        """
        import re
        from plotly.subplots import make_subplots
        
        indices_noms = list(results.keys())
        short_noms = []
        for idx_i, nom_idx in enumerate(indices_noms):
            m = re.search(r'\(([^)]+)\)$', nom_idx.strip())
            ticker_short = m.group(1) if m else ((nom_idx[:25] + '...') if len(nom_idx) > 25 else nom_idx)
            short_noms.append(f"Indice {idx_i + 1} : {ticker_short}")

        taux_autocall = [results[k]["pct_rappel"] for k in indices_noms]
        remb_pair = [results[k].get("pct_remb_pair", 0.0) for k in indices_noms]
        taux_pdi = [results[k]["pct_pdi"] for k in indices_noms]
        
        tri_moyens = [results[k]["tri_moyen"] for k in indices_noms]
        tri_medians = [results[k]["tri_median"] for k in indices_noms]

        fig = make_subplots(
            rows=1, cols=2,
            subplot_titles=[
                "<b>1. Probabilités d'Issues du Produit (%)</b>",
                "<b>2. Rendement Espéré - TRA (%)</b>"
            ],
            horizontal_spacing=0.14
        )

        # --- SOUS-GRAPHIQUE 1 : ISSUES ET RISQUES (0 - 100%) ---
        fig.add_trace(go.Bar(
            x=short_noms, y=taux_autocall,
            name="Autocall Anticipé (%)",
            marker_color="#16a34a",
            text=[f"{v:.1f}%" for v in taux_autocall],
            textposition="auto",
            hovertemplate="<b>%{x}</b><br>Autocall: <b>%{y:.1f}%</b><extra></extra>"
        ), row=1, col=1)

        fig.add_trace(go.Bar(
            x=short_noms, y=remb_pair,
            name="Remboursement au Pair (100%)",
            marker_color="#64748b",
            text=[f"{v:.1f}%" for v in remb_pair],
            textposition="auto",
            hovertemplate="<b>%{x}</b><br>Remb. Pair: <b>%{y:.1f}%</b><extra></extra>"
        ), row=1, col=1)

        fig.add_trace(go.Bar(
            x=short_noms, y=taux_pdi,
            name="Risque de Perte PDI (%)",
            marker_color="#dc2626",
            text=[f"{v:.1f}%" for v in taux_pdi],
            textposition="auto",
            hovertemplate="<b>%{x}</b><br>Perte PDI: <b>%{y:.1f}%</b><extra></extra>"
        ), row=1, col=1)

        # --- SOUS-GRAPHIQUE 2 : RENDEMENT TRA (%) ---
        fig.add_trace(go.Bar(
            x=short_noms, y=tri_moyens,
            name="TRA Moyen (%)",
            marker_color="#0284c7",
            text=[f"{v:.2f}%" for v in tri_moyens],
            textposition="auto",
            hovertemplate="<b>%{x}</b><br>TRA Moyen: <b>%{y:.2f}%</b><extra></extra>"
        ), row=1, col=2)

        fig.add_trace(go.Bar(
            x=short_noms, y=tri_medians,
            name="TRA Médian (%)",
            marker_color="#4f46e5",
            text=[f"{v:.2f}%" for v in tri_medians],
            textposition="auto",
            hovertemplate="<b>%{x}</b><br>TRA Médian: <b>%{y:.2f}%</b><extra></extra>"
        ), row=1, col=2)

        fig.update_yaxes(title_text="<b>Probabilité (%)</b>", range=[0, 105], row=1, col=1)
        fig.update_yaxes(title_text="<b>TRA (%)</b>", row=1, col=2)

        fig.update_layout(
            barmode='group',
            template="plotly_white",
            legend=dict(
                orientation="h",
                yanchor="top",
                y=-0.18,
                xanchor="center",
                x=0.5,
                bgcolor="rgba(255,255,255,0.9)",
                bordercolor="#e2e8f0",
                borderwidth=1
            ),
            margin=dict(l=50, r=40, t=60, b=80)
        )
        return fig

    def plot_pricing_waterfall(self, results: dict, product: AutocallProduct):
        """Graphique à barres comparant la distribution des sorties agrégées par Année."""
        palette = ['#2563eb', '#dc2626', '#16a34a', '#9333ea', '#ea580c']
        fig = go.Figure()
        
        for idx_i, (nom_idx, data) in enumerate(results.items()):
            color = palette[idx_i % len(palette)]
            schedule = data["schedule"]
            est_rappele = data["est_rappele"]
            obs_rappel = data["obs_de_rappel"]
            total_traj = len(est_rappele)
            
            # Détermination de l'horizon total en années
            annees_total = int(max(item["annee"] for item in schedule)) if len(schedule) > 0 else 1
            recalls_par_annee = {y: 0.0 for y in range(1, annees_total + 1)}
            
            # Constatations de rappel agrégées par année entière
            for item in schedule:
                if not item["eligible"]:
                    continue
                obs_k = item["obs_num"]
                annee_val = item["annee"]
                annee_idx = max(1, int(np.ceil(annee_val - 1e-5)))
                pct = np.sum(est_rappele & (obs_rappel == obs_k)) / total_traj * 100.0
                if annee_idx in recalls_par_annee:
                    recalls_par_annee[annee_idx] += pct
                else:
                    recalls_par_annee[annee_idx] = pct
                    
            x_labels = [f"Rappel An {y}" for y in range(1, annees_total + 1)]
            y_pcts = [recalls_par_annee[y] for y in range(1, annees_total + 1)]
            
            # Sorties à maturité
            x_labels.append("Maturité : Au Pair (100%)")
            y_pcts.append(data.get("pct_remb_pair", 0.0))
            
            x_labels.append("Maturité : Perte PDI")
            y_pcts.append(data.get("pct_pdi", 0.0))
            
            fig.add_trace(go.Bar(
                x=x_labels, y=y_pcts,
                name=nom_idx,
                marker_color=color,
                text=[f"{v:.1f}%" if v >= 1.0 else "" for v in y_pcts],
                textposition="auto",
                hovertemplate="<b>%{x}</b><br>" + nom_idx + ": <b>%{y:.1f}%</b><extra></extra>"
            ))
            
        fig.update_layout(
            barmode='group',
            title="<b>Distribution des Scénarios de Sortie par Année</b>",
            xaxis_title="<b>Horizon et Mode de Sortie</b>",
            yaxis_title="<b>Fréquence (%)</b>",
            template="plotly_white",
            legend=dict(
                orientation="h",
                yanchor="top",
                y=-0.22,
                xanchor="center",
                x=0.5,
                bgcolor="rgba(255,255,255,0.9)",
                bordercolor="#e2e8f0",
                borderwidth=1
            ),
            margin=dict(l=50, r=40, t=60, b=90)
        )
        return fig

    def plot_pricing_distribution_tri(self, results: dict):
        """Histogramme de distribution des Rendements (TRA) pour chaque indice."""
        import re
        palette = ['#2563eb', '#dc2626', '#16a34a', '#9333ea', '#ea580c']
        fig = go.Figure()
        
        for idx_i, (nom_idx, data) in enumerate(results.items()):
            color = palette[idx_i % len(palette)]
            tri_vals = data["tri_array"] * 100.0
            # Bornage de sécurité pour affichage propre
            tri_sub = np.clip(tri_vals, -50.0, 30.0)
            
            m = re.search(r'\(([^)]+)\)$', nom_idx.strip())
            ticker_short = m.group(1) if m else ((nom_idx[:20] + '...') if len(nom_idx) > 20 else nom_idx)
            m_tri = data["tri_moyen"]
            
            fig.add_trace(go.Histogram(
                x=tri_sub,
                name=f"{ticker_short} (TRA Moy: {m_tri:.2f}%)",
                marker_color=color,
                opacity=0.55,
                nbinsx=60,
                histnorm='percent'
            ))
            fig.add_vline(
                x=m_tri, line_dash="dot", line_color=color, line_width=2,
                annotation_text=f"Moy {ticker_short}: {m_tri:.2f}%",
                annotation_position="top right"
            )
            
        fig.add_vline(x=0.0, line_dash="dash", line_color="#475569", line_width=1.5, annotation_text="TRA 0% (Remb. 100%)")
        fig.update_layout(
            barmode='overlay',
            title="<b>Distribution Comparée du TRA</b>",
            xaxis_title="<b>TRA (%)</b>",
            yaxis_title="<b>Proportion des Trajectoires (%)</b>",
            template="plotly_white",
            legend=dict(
                orientation="h",
                yanchor="top",
                y=-0.20,
                xanchor="center",
                x=0.5,
                bgcolor="rgba(255,255,255,0.9)",
                bordercolor="#e2e8f0",
                borderwidth=1
            ),
            margin=dict(l=50, r=40, t=60, b=80)
        )
        return fig

    def plot_pricing_distribution_fair_value(self, results: dict):
        """Histogramme de distribution de la Fair Value (Payoff actualisé % du nominal) pour chaque indice."""
        import re
        palette = ['#2563eb', '#dc2626', '#16a34a', '#9333ea', '#ea580c']
        fig = go.Figure()
        
        for idx_i, (nom_idx, data) in enumerate(results.items()):
            color = palette[idx_i % len(palette)]
            fv_vals = data["payoffs"] * 100.0
            fv_sub = np.clip(fv_vals, 0.0, 200.0)
            
            m = re.search(r'\(([^)]+)\)$', nom_idx.strip())
            ticker_short = m.group(1) if m else ((nom_idx[:20] + '...') if len(nom_idx) > 20 else nom_idx)
            m_fv = data["moy_payoff"]
            
            fig.add_trace(go.Histogram(
                x=fv_sub,
                name=f"{ticker_short} (FV Moy: {m_fv:.1f}%)",
                marker_color=color,
                opacity=0.55,
                nbinsx=60,
                histnorm='percent'
            ))
            fig.add_vline(
                x=m_fv, line_dash="dot", line_color=color, line_width=2,
                annotation_text=f"FV {ticker_short}: {m_fv:.1f}%",
                annotation_position="top right"
            )
            
        fig.add_vline(x=100.0, line_dash="dash", line_color="#475569", line_width=1.5, annotation_text="Nominal (100%)")
        fig.update_layout(
            barmode='overlay',
            title="<b>Distribution Comparée de la Fair Value (Payoffs Actualisés)</b>",
            xaxis_title="<b>Fair Value (% du nominal)</b>",
            yaxis_title="<b>Proportion des Trajectoires (%)</b>",
            template="plotly_white",
            legend=dict(
                orientation="h",
                yanchor="top",
                y=-0.20,
                xanchor="center",
                x=0.5,
                bgcolor="rgba(255,255,255,0.9)",
                bordercolor="#e2e8f0",
                borderwidth=1
            ),
            margin=dict(l=50, r=40, t=60, b=80)
        )
        return fig

    def plot_pricing_distribution_durations(self, results: dict, product: AutocallProduct = None):
        """Diagramme en barres de la distribution discrète des Durées de vie effectives (Horizons de sortie)."""
        import re
        palette = ['#2563eb', '#dc2626', '#16a34a', '#9333ea', '#ea580c']
        fig = go.Figure()
        
        all_exit_times = set()
        for nom_idx, data in results.items():
            durees = data["metrics"]["duree_effective"]
            unique_t = np.unique(np.round(durees, 2))
            all_exit_times.update(unique_t.tolist())
            
        all_t_sorted = sorted(list(all_exit_times))
        if not all_t_sorted:
            all_t_sorted = [1.0]
            
        t_max = all_t_sorted[-1]
        
        # Si plus de 24 dates distinctes (ex: mensuelle), agrégation par semestre pour lisibilité
        if len(all_t_sorted) > 24:
            semestres = sorted(list(set([max(0.5, round(np.ceil(t * 2.0) / 2.0, 2)) for t in all_t_sorted])))
            x_labels = [f"{s:.1f} an" if s <= 1.0 else (f"{s:.1f} ans (Maturité)" if s >= t_max - 0.1 else f"{s:.1f} ans") for s in semestres]
            for idx_i, (nom_idx, data) in enumerate(results.items()):
                color = palette[idx_i % len(palette)]
                durees = data["metrics"]["duree_effective"]
                total_n = len(durees)
                m = re.search(r'\(([^)]+)\)$', nom_idx.strip())
                ticker_short = m.group(1) if m else ((nom_idx[:20] + '...') if len(nom_idx) > 20 else nom_idx)
                freqs = []
                for s in semestres:
                    mask = (durees <= s + 1e-4) & (durees > s - 0.5 + 1e-4) if s > 0.5 else (durees <= s + 1e-4)
                    freqs.append(np.sum(mask) / total_n * 100.0)
                dur_moy = data["duration"]
                fig.add_trace(go.Bar(
                    x=x_labels, y=freqs,
                    name=f"{ticker_short} (Duration : {dur_moy:.2f} ans)",
                    marker_color=color,
                    text=[f"{v:.1f}%" if v >= 1.0 else "" for v in freqs],
                    textposition="auto",
                    hovertemplate=f"<b>%{{x}}</b><br>{ticker_short}: <b>%{{y:.1f}}%</b><extra></extra>"
                ))
        else:
            x_labels = [f"{t:.2f} ans" if t < t_max - 1e-4 else f"{t:.2f} ans (Maturité)" for t in all_t_sorted]
            for idx_i, (nom_idx, data) in enumerate(results.items()):
                color = palette[idx_i % len(palette)]
                durees = data["metrics"]["duree_effective"]
                total_n = len(durees)
                m = re.search(r'\(([^)]+)\)$', nom_idx.strip())
                ticker_short = m.group(1) if m else ((nom_idx[:20] + '...') if len(nom_idx) > 20 else nom_idx)
                freqs = [np.sum(np.isclose(durees, t, atol=0.03)) / total_n * 100.0 for t in all_t_sorted]
                dur_moy = data["duration"]
                fig.add_trace(go.Bar(
                    x=x_labels, y=freqs,
                    name=f"{ticker_short} (Duration : {dur_moy:.2f} ans)",
                    marker_color=color,
                    text=[f"{v:.1f}%" if v >= 1.0 else "" for v in freqs],
                    textposition="auto",
                    hovertemplate=f"<b>%{{x}}</b><br>{ticker_short}: <b>%{{y:.1f}}%</b><extra></extra>"
                ))
                
        fig.update_layout(
            barmode='group',
            title="<b>Distribution des Durées de Vie Effectives (Horizons de Sortie)</b>",
            xaxis_title="<b>Date / Horizon de Sortie (années)</b>",
            yaxis_title="<b>Proportion des Trajectoires (%)</b>",
            template="plotly_white",
            legend=dict(
                orientation="h",
                yanchor="top",
                y=-0.22,
                xanchor="center",
                x=0.5,
                bgcolor="rgba(255,255,255,0.9)",
                bordercolor="#e2e8f0",
                borderwidth=1
            ),
            margin=dict(l=50, r=40, t=60, b=90)
        )
        return fig

    def plot_pricing_trajectoires_avec_barrieres(self, results: dict, product: AutocallProduct, annees: int):
        """Affiche les trajectoires médianes et fuseaux P10-P90 des indices face aux barrières du produit."""
        palette = ['#2563eb', '#dc2626', '#16a34a', '#9333ea', '#ea580c']
        fig = go.Figure()
        
        jours_par_an = 252
        total_jours = int(annees * jours_par_an)
        axe_temps = np.linspace(0, annees, total_jours + 1)
        
        # 1. Trajectoires et fuseaux de chaque indice
        for idx_i, (nom_idx, data) in enumerate(results.items()):
            color = palette[idx_i % len(palette)]
            s0 = float(data["index"].niveau_initial)
            traj = data["trajectoires"]
            
            traj_pct = (traj / s0) * 100.0
            med_courbe = np.median(traj_pct, axis=0)
            p10_courbe = np.percentile(traj_pct, 10, axis=0)
            p90_courbe = np.percentile(traj_pct, 90, axis=0)
            
            rgb_col = f"{int(color[1:3], 16)}, {int(color[3:5], 16)}, {int(color[5:7], 16)}"
            
            # Fuseau P10 - P90
            fig.add_trace(go.Scatter(
                x=axe_temps, y=p90_courbe, mode='lines', line=dict(width=0),
                showlegend=False, legendgroup=nom_idx, hoverinfo='skip'
            ))
            fig.add_trace(go.Scatter(
                x=axe_temps, y=p10_courbe, mode='lines', line=dict(width=0),
                fill='tonexty', fillcolor=f"rgba({rgb_col}, 0.12)",
                name=f"{nom_idx} [P10-P90]", legendgroup=nom_idx, showlegend=False
            ))
            # Médiane
            fig.add_trace(go.Scatter(
                x=axe_temps, y=med_courbe, mode='lines', line=dict(color=color, width=2.8),
                name=nom_idx, legendgroup=nom_idx, showlegend=True,
                hovertemplate=f"<b>{nom_idx}</b><br>Horizon: %{{x:.2f}} ans<br>Niveau Médian: <b>%{{y:.1f}}%</b><extra></extra>"
            ))
            
        # 2. Barrières du produit (normalisées en % du spot)
        ref_s0 = product.ref_s0 if product.ref_s0 > 0 else 1000.0
        pdi_pct = (product.niveau_pdi / ref_s0) * 100.0
        rappel_pct = (product.barriere_rappel / ref_s0) * 100.0
        
        # Barrière PDI
        fig.add_hline(y=pdi_pct, line_dash="dash", line_color="#dc2626", line_width=2.0,
                      annotation_text=f"PDI ({pdi_pct:.0f}%)", annotation_position="bottom right")
        
        # Barrière Coupon (si Phoenix)
        if hasattr(product, 'barriere_coupon') and product.barriere_coupon is not None:
            coupon_pct = (product.barriere_coupon / ref_s0) * 100.0
            fig.add_hline(y=coupon_pct, line_dash="dot", line_color="#16a34a", line_width=1.8,
                          annotation_text=f"Barrière Coupon ({coupon_pct:.0f}%)", annotation_position="top left")
        
        # Barrière de Rappel (avec dégressivité en escalier et plancher)
        schedule = product.get_barrieres_schedule(total_jours, jours_par_an)
        x_barr = [0.0]
        y_barr = [rappel_pct]
        
        for item in schedule:
            t_an = item["annee"]
            b_pct = item["barriere_pct"] if np.isfinite(item["barriere_pct"]) else rappel_pct
            x_barr.append(t_an)
            y_barr.append(y_barr[-1])
            x_barr.append(t_an)
            y_barr.append(b_pct)
            
        x_barr.append(annees)
        y_barr.append(y_barr[-1])
        
        fig.add_trace(go.Scatter(
            x=x_barr, y=y_barr, mode='lines',
            line=dict(color="#7c3aed", width=2.2, dash='dashdot'),
            name=f"Barrière Rappel ({rappel_pct:.0f}%)",
            showlegend=True
        ))
        
        fig.update_layout(
            title="<b>Trajectoires Médianes des Indices face aux Barrières du Produit</b>",
            xaxis_title="<b>Horizon Temporel (Années)</b>",
            yaxis_title="<b>Niveau (% du Spot Initial)</b>",
            template="plotly_white",
            legend=dict(
                orientation="h",
                yanchor="top",
                y=-0.20,
                xanchor="center",
                x=0.5,
                bgcolor="rgba(255,255,255,0.9)",
                bordercolor="#e2e8f0",
                borderwidth=1
            ),
            margin=dict(l=60, r=40, t=60, b=80)
        )
        return fig

    def plot_multi_pricing_kpis(self, results: dict):
        """Graphique à barres comparatif des KPIs majeurs de pricing."""
        import re
        indices_noms = list(results.keys())
        taux_autocall = [results[k]["pct_rappel_dec"] for k in indices_noms]
        taux_pdi = [results[k]["pct_pdi_dec"] for k in indices_noms]
        payoffs = [results[k]["moy_payoff_dec"] for k in indices_noms]
        
        short_noms = []
        for idx_i, nom_idx in enumerate(indices_noms):
            m = re.search(r'\(([^)]+)\)$', nom_idx.strip())
            ticker_short = m.group(1) if m else ((nom_idx[:25] + '...') if len(nom_idx) > 25 else nom_idx)
            short_noms.append(f"Indice {idx_i + 1} : {ticker_short}")
        
        fig = go.Figure()
        fig.add_trace(go.Bar(
            x=short_noms, y=taux_autocall,
            name="Taux d'Autocall (%)",
            marker_color="#16a34a",
            text=[f"{v:.1f}%" for v in taux_autocall],
            textposition="auto"
        ))
        fig.add_trace(go.Bar(
            x=short_noms, y=taux_pdi,
            name="Probabilité sous PDI (%)",
            marker_color="#dc2626",
            text=[f"{v:.2f}%" for v in taux_pdi],
            textposition="auto"
        ))
        fig.add_trace(go.Bar(
            x=short_noms, y=payoffs,
            name="Payoff Moyen Actualisé (% nom.)",
            marker_color="#2563eb",
            text=[f"{v:.1f}%" for v in payoffs],
            textposition="auto"
        ))
        fig.update_layout(
            barmode='group',
            title="<b>Comparaison des Indicateurs Clés de Risque et de Rendement</b>",
            yaxis_title="<b>Pourcentage (%)</b>",
            template="plotly_white",
            xaxis=dict(tickangle=0),
            legend=dict(
                orientation="h",
                yanchor="top",
                y=-0.22,
                xanchor="center",
                x=0.5,
                bgcolor="rgba(255,255,255,0.9)",
                bordercolor="#e2e8f0",
                borderwidth=1
            ),
            margin=dict(l=50, r=40, t=60, b=90)
        )
        return fig

    def plot_multi_pricing_rappels(self, results: dict, scenario: MarketScenario, product: AutocallProduct):
        """Graphique à barres groupé comparant les dates de rappel anticipé pour chaque indice."""
        jours_par_mois = scenario.jours_par_an // 12
        jours_entre_obs = jours_par_mois * product.frequence_obs_mois
        annees_par_obs = jours_entre_obs / scenario.jours_par_an
        
        nb_obs_total = int(scenario.total_jours // jours_entre_obs)
        x_annees = [(k + 1) * annees_par_obs for k in range(nb_obs_total)]
        x_labels = [f"An {a:.2f}" for a in x_annees]
        
        fig = go.Figure()
        palette = ['#2563eb', '#dc2626', '#16a34a', '#9333ea', '#ea580c']
        
        for idx_i, (nom_idx, data) in enumerate(results.items()):
            color = palette[idx_i % len(palette)]
            obs_rappel = data["obs_de_rappel_dec"]
            est_rappele = data["est_rappele_dec"]
            total_traj = len(est_rappele)
            
            pcts_obs = []
            for k in range(1, nb_obs_total + 1):
                pct = np.sum(est_rappele & (obs_rappel == k)) / total_traj * 100.0
                pcts_obs.append(pct)
                
            fig.add_trace(go.Bar(
                x=x_labels, y=pcts_obs,
                name=nom_idx,
                marker_color=color
            ))
            
        fig.update_layout(
            barmode='group',
            title="<b>Distribution Comparée des Constatations de Rappel Anticipé</b>",
            xaxis_title="<b>Date de Constatation</b>",
            yaxis_title="<b>Fréquence de Rappel (%)</b>",
            template="plotly_white",
            legend=dict(
                orientation="h",
                yanchor="top",
                y=-0.22,
                xanchor="center",
                x=0.5,
                bgcolor="rgba(255,255,255,0.9)",
                bordercolor="#e2e8f0",
                borderwidth=1
            ),
            margin=dict(l=50, r=40, t=60, b=90)
        )
        return fig

if __name__ == "__main__":
    mes_regimes = [
        {"duree_annees": 10, "r_perf": 0.0}
    ]
    
    scenario_krach = MarketScenario(config_regimes=mes_regimes, annees=10, jours_par_an=252)
    mon_indice_dec = DecrementIndex(niveau_initial=1000.0, decrement_annuel=50.0, vol=0.18, dividend_yield=0.03)
    pdi_pts = mon_indice_dec.niveau_initial * 0.50
    mon_autocall = AutocallProduct(barriere_rappel=1000.0, niveau_pdi=pdi_pts, non_call_period_mois=11, frequence_obs_mois=3, degressivite=1.0)
    
    moteur = SimulationEngine(nb_trajectoires=10000,seed=42)
    traj_pr, traj_dec, est_rappele_dec, obs_de_rappel_dec, payoffs_dec, est_rappele_pr, obs_de_rappel_pr, payoffs_pr = moteur.run(mon_indice_dec, scenario_krach, mon_autocall, taux_actualisation=0.03)
    
    nom_scenario = f"Scénario N-Périodes Test"
    reps_scen, bin_stats, levier = moteur.afficher_statistiques(nom_scenario, traj_pr, traj_dec, est_rappele_dec, payoffs_dec, est_rappele_pr, payoffs_pr, mon_autocall, scenario_krach)
    
    fig1, fig2 = moteur.plot_results(nom_scenario, traj_pr, traj_dec, reps_scen, mon_autocall, scenario_krach, mon_indice_dec)
    fig1.show()
    fig2.show()
    if bin_stats:
        fig_binned = moteur.plot_binned_averages(bin_stats)
        fig_binned.show()

