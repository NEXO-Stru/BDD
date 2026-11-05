"""
financial_core.py
=================
Cœur financier et moteur quantitatif du projet Database.
Contient toutes les classes métiers :
- UniverseRepository : Accès base de données, référentiel des sous-jacents et séries de prix.
- ScreenerEngine : Calculs vectorisés haute performance sur l'ensemble de l'univers.
- AssetAnalytics : Analyse financière individuelle d'un sous-jacent (performances, volatilité, bêta, drawdown).
- DecrementAnalytics : Sous-classe dédiée aux indices décrément (scoring NEXO™ calibré, extraction du décrément).
- BasketAnalytics : Analyse comparative multi-actifs, panier équipondéré et corrélations croisées.
- NexoPptxGenerator : Génération du slide institutionnel client One-Pager NEXO sur template natif.
- ExcelReportGenerator & PptxReportGenerator : Génération des rapports bureautiques multi-onglets.

Aucun code Streamlit n'est présent dans ce module.
"""

import os
import io
import re
import math
import itertools
import datetime
import numpy as np
import pandas as pd
from sqlalchemy import create_engine, text
from pptx import Presentation
from pptx.util import Inches
from pptx.dml.color import RGBColor
from dotenv import load_dotenv


# ==============================================================================
# 1. COUCHE DONNÉES : UniverseRepository
# ==============================================================================

class UniverseRepository:
    """Gère la connexion à la base de données Supabase, le chargement, le nettoyage
    et la distribution du référentiel et de l'historique des cours.
    """

    BENCHMARK_MAPPING = {
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

    def __init__(self, db_url: str = None, engine=None):
        if engine is not None:
            self.engine = engine
            self.db_url = str(engine.url) if hasattr(engine, 'url') else None
        else:
            if not db_url:
                load_dotenv()
                db_url = os.getenv("SUPABASE_DB_URL")
            if db_url and db_url.startswith("postgres://"):
                db_url = db_url.replace("postgres://", "postgresql://", 1)
            self.db_url = db_url
            self.engine = create_engine(self.db_url) if self.db_url else None

        self.assets_df = pd.DataFrame()
        self.prices_pivot = pd.DataFrame()

    def fetch_assets_from_db(self) -> pd.DataFrame:
        """Charge la table asset depuis Supabase et nettoie les secteurs."""
        if self.engine is None:
            raise ValueError("Moteur de base de données non initialisé (SUPABASE_DB_URL manquante).")
        with self.engine.connect() as conn:
            df = pd.read_sql("SELECT * FROM asset", conn)
            df['sector'] = df['sector'].astype(str).str.strip()
            df.loc[df['sector'].str.contains('multi', case=False, na=False), 'sector'] = 'Multi-secteurs'
            df.loc[df['sector'].str.contains('diversifi', case=False, na=False), 'sector'] = 'Multi-secteurs'
            self.assets_df = df
            return df

    def fetch_prices_from_db(self) -> pd.DataFrame:
        """Charge historical_price depuis Supabase, pivote et ffill."""
        if self.engine is None:
            raise ValueError("Moteur de base de données non initialisé.")
        with self.engine.connect() as conn:
            df = pd.read_sql("SELECT asset_id, date, close FROM historical_price", conn)
            df['date'] = pd.to_datetime(df['date'])
            pivot = df.pivot(index='date', columns='asset_id', values='close')
            pivot = pivot.sort_index().ffill()
            self.prices_pivot = pivot
            return pivot

    def load_all(self, assets_df: pd.DataFrame = None, prices_pivot: pd.DataFrame = None):
        """Initialise ou injecte les DataFrames assets et prices."""
        if assets_df is not None:
            self.assets_df = assets_df.copy()
        else:
            self.assets_df = self.fetch_assets_from_db()

        if prices_pivot is not None:
            self.prices_pivot = prices_pivot.copy()
        else:
            self.prices_pivot = self.fetch_prices_from_db()

        if 'display_name' not in self.assets_df.columns:
            self.assets_df['display_name'] = (
                self.assets_df['name'].fillna('Inconnu') + " (" + self.assets_df['ticker_bloomberg'].fillna('') + ")"
            )

    def get_asset_info(self, asset_id, assets_df: pd.DataFrame = None) -> dict:
        target_df = assets_df if assets_df is not None else self.assets_df
        if target_df is None or target_df.empty or 'asset_id' not in target_df.columns:
            return {}
        matched = target_df[target_df['asset_id'] == asset_id]
        if matched.empty:
            return {}
        return matched.iloc[0].to_dict()

    def get_price_series(self, asset_id, prices_pivot: pd.DataFrame = None) -> pd.Series:
        target_prices = prices_pivot if prices_pivot is not None else self.prices_pivot
        if target_prices is None or target_prices.empty or asset_id not in target_prices.columns:
            return pd.Series(dtype=float)
        s = target_prices[asset_id].dropna()
        return s[s > 0]

    def get_benchmark_for_asset(self, asset_info: dict, assets_df: pd.DataFrame = None, prices_pivot: pd.DataFrame = None) -> tuple:
        """Retourne (benchmark_asset_id, benchmark_ticker, benchmark_prices)."""
        country = str(asset_info.get('country', '')).strip().upper()
        ticker_bench = self.BENCHMARK_MAPPING.get(country)
        if not ticker_bench:
            return None, None, None

        target_df = assets_df if assets_df is not None else self.assets_df
        if target_df is None or target_df.empty or 'ticker_bloomberg' not in target_df.columns:
            return None, ticker_bench, None

        matched = target_df[target_df['ticker_bloomberg'] == ticker_bench]
        if matched.empty:
            return None, ticker_bench, None
        bench_id = matched.iloc[0]['asset_id']

        target_prices = prices_pivot if prices_pivot is not None else self.prices_pivot
        if target_prices is not None and not target_prices.empty and bench_id in target_prices.columns:
            bench_prices = target_prices[bench_id].dropna()
            bench_prices = bench_prices[bench_prices > 0]
        else:
            bench_prices = self.get_price_series(bench_id, prices_pivot=target_prices)

        return bench_id, ticker_bench, bench_prices

    def filter_universe(self, search_query: str = "", sel_types=None, sel_subtypes=None,
                        sel_sectors=None, sel_countries=None, sel_currencies=None,
                        filter_only_priced: bool = True, base_df: pd.DataFrame = None) -> pd.DataFrame:
        target = base_df if base_df is not None else self.assets_df
        if target is None or target.empty:
            return pd.DataFrame()
        df = target.copy()

        if search_query:
            q = search_query.strip().lower()
            mask_search = (
                df['name'].astype(str).str.lower().str.contains(q, na=False) |
                df['ticker_bloomberg'].astype(str).str.lower().str.contains(q, na=False) |
                df['isin'].astype(str).str.lower().str.contains(q, na=False)
            )
            df = df[mask_search]

        if sel_types:
            df = df[df['asset_type'].isin(sel_types)]
        if sel_subtypes:
            df = df[df['asset_subtype'].isin(sel_subtypes)]
        if sel_sectors:
            df = df[df['sector'].isin(sel_sectors)]
        if sel_countries:
            df = df[df['country'].isin(sel_countries)]
        if sel_currencies:
            df = df[df['currency'].isin(sel_currencies)]

        if filter_only_priced and 'last_price' in df.columns:
            df = df[df['last_price'].notna() & (df['last_price'] > 0)]

        return df


# ==============================================================================
# 2. COUCHE QUANTITATIVE : ScreenerEngine
# ==============================================================================

class ScreenerEngine:
    """Exécute les calculs vectorisés sur la matrice 2D des prix pour enrichir l'univers."""

    COLUMNS_MAPPING = {
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

    @staticmethod
    def compute_metrics(assets_df: pd.DataFrame, prices_pivot: pd.DataFrame) -> pd.DataFrame:
        if prices_pivot.empty:
            return assets_df

        date_now = prices_pivot.index[-1]
        last_prices = prices_pivot.iloc[-1]

        # Performances
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

        # Volatilités annualisées
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

        # Écartement Moyennes Mobiles (SMA 50 et 200)
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


# ==============================================================================
# 3. COUCHE QUANTITATIVE : AssetAnalytics & DecrementAnalytics
# ==============================================================================

class AssetAnalytics:
    """Modélise le comportement financier d'un actif individuel."""

    def __init__(self, asset_id, info: dict, prices: pd.Series, benchmark_id=None,
                 benchmark_ticker: str = None, benchmark_prices: pd.Series = None):
        self.asset_id = asset_id
        self.info = info or {}
        self.prices = prices.dropna()[prices > 0] if prices is not None else pd.Series(dtype=float)
        self.daily_returns = self.prices.pct_change(fill_method=None).dropna() if len(self.prices) > 1 else pd.Series(dtype=float)
        self.current_date = self.prices.index.max() if len(self.prices) > 0 else None
        self.current_price = float(self.prices.iloc[-1]) if len(self.prices) > 0 else np.nan

        self.benchmark_id = benchmark_id
        self.benchmark_ticker = benchmark_ticker
        self.benchmark_prices = benchmark_prices.dropna()[benchmark_prices > 0] if benchmark_prices is not None else None

    def get_price_at(self, date_target) -> float:
        if len(self.prices) == 0:
            return np.nan
        avail = self.prices[self.prices.index <= date_target]
        if len(avail) == 0:
            return np.nan
        return float(avail.iloc[-1])

    def perf(self, days: int = None, ytd: bool = False) -> float:
        if len(self.prices) < 2 or pd.isna(self.current_price):
            return np.nan
        if ytd:
            end_prev_year = pd.Timestamp(year=self.current_date.year - 1, month=12, day=31)
            old_p = self.get_price_at(end_prev_year)
        else:
            old_p = self.get_price_at(self.current_date - pd.Timedelta(days=days))
        if pd.isna(old_p) or old_p <= 0:
            return np.nan
        return ((self.current_price / old_p) - 1.0) * 100.0

    def perf_ann(self, days: int) -> float:
        if len(self.prices) == 0 or pd.isna(self.current_price):
            return np.nan
        start_date = self.current_date - pd.Timedelta(days=days)
        sub = self.prices[self.prices.index >= start_date]
        if len(sub) == 0:
            return np.nan
        old_price = sub.iloc[0]
        years = days / 365.25
        if old_price <= 0:
            return np.nan
        return ((self.current_price / old_price) ** (1 / years) - 1.0) * 100.0

    def vol(self, days: int = None, ytd: bool = False) -> float:
        if len(self.daily_returns) < 2:
            return np.nan
        if ytd:
            end_prev_year = pd.Timestamp(year=self.current_date.year - 1, month=12, day=31)
            sub_rets = self.daily_returns[self.daily_returns.index > end_prev_year]
        else:
            sub_rets = self.daily_returns[self.daily_returns.index >= (self.current_date - pd.Timedelta(days=days))]
        if len(sub_rets) < 2:
            return np.nan
        return float(sub_rets.std() * np.sqrt(252) * 100.0)

    def rolling_vol(self, window_days: int = 252) -> pd.Series:
        if len(self.daily_returns) < window_days:
            return pd.Series(dtype=float)
        return self.daily_returns.rolling(window=window_days, min_periods=window_days).std() * np.sqrt(252) * 100.0

    def beta(self, days: int = 365) -> float:
        if self.benchmark_prices is None or len(self.benchmark_prices) < 20 or len(self.daily_returns) < 20:
            return np.nan
        bench_rets = self.benchmark_prices.pct_change(fill_method=None).dropna()
        cutoff = self.current_date - pd.Timedelta(days=days)
        sub_a = self.daily_returns[self.daily_returns.index >= cutoff]
        sub_b = bench_rets[bench_rets.index >= cutoff]
        common = sub_a.index.intersection(sub_b.index)
        if len(common) < 20:
            return np.nan
        cov = sub_a.loc[common].cov(sub_b.loc[common])
        var_b = sub_b.loc[common].var()
        if var_b == 0 or pd.isna(var_b):
            return np.nan
        return float(cov / var_b)

    def correlation_with_benchmark(self, days: int = 365) -> float:
        if self.benchmark_prices is None or len(self.benchmark_prices) < 2:
            return np.nan
        common = self.prices.index.intersection(self.benchmark_prices.index)
        cutoff = common.max() - pd.Timedelta(days=days)
        common = common[common >= cutoff]
        if len(common) < 2:
            return np.nan
        ret_a = self.prices.loc[common].pct_change().dropna()
        ret_b = self.benchmark_prices.loc[common].pct_change().dropna()
        if len(ret_a) < 2:
            return np.nan
        return float(ret_a.corr(ret_b) * 100.0)

    def max_drawdown(self, days: int) -> float:
        start_date = self.current_date - pd.Timedelta(days=days)
        sub = self.prices[self.prices.index >= start_date]
        if len(sub) == 0:
            return np.nan
        roll_max = sub.cummax()
        dd = (sub / roll_max) - 1.0
        return float(dd.min() * 100.0)

    def sharpe_ratio(self, days: int) -> float:
        perf = self.perf_ann(days) if days > 365 else self.perf(days=days)
        vol = self.vol(days)
        if pd.isna(perf) or pd.isna(vol) or vol == 0:
            return np.nan
        return float(perf / vol)

    def sma(self, window: int = 50) -> pd.Series:
        return self.prices.rolling(window=window, min_periods=1).mean()


class DecrementAnalytics(AssetAnalytics):
    """Sous-classe pour les indices à décrément fixe avec moteur de notation NEXO™ calibré."""

    def __init__(self, asset_id, info: dict, prices: pd.Series, benchmark_id=None,
                 benchmark_ticker: str = None, benchmark_prices: pd.Series = None):
        super().__init__(asset_id, info, prices, benchmark_id, benchmark_ticker, benchmark_prices)

        self.asset_name = str(self.info.get('name', ''))
        self.dec_val, self.dec_type = self.extract_decrement(self.asset_name)
        self.dividend_yield = self.info.get('dividend_yield')

        # Calcul du rendement effectif du décrément sur le spot
        self.dec_yield = None
        self.dec_yield_pct = "N/A"
        if self.dec_val is not None and pd.notna(self.current_price) and self.current_price > 0:
            if self.dec_type == 'PERCENT':
                self.dec_yield = float(self.dec_val) / 100.0
                self.dec_yield_pct = float(self.dec_val)
            else:
                self.dec_yield = float(self.dec_val) / float(self.current_price)
                self.dec_yield_pct = self.dec_yield * 100.0

    @staticmethod
    def extract_decrement(name: str):
        """Parse le nom d'un actif pour identifier un décrément en points ou %."""
        if not name or not isinstance(name, str):
            return None, None
        m_pct = re.search(r'(\d+(?:[.,]\d+)?)\s*%', name)
        if m_pct:
            return float(m_pct.group(1).replace(',', '.')), 'PERCENT'
        m_dnp = re.search(r'(?i)d\s*(\d+(?:[.,]\d+)?)\s*p', name)
        if m_dnp:
            return float(m_dnp.group(1).replace(',', '.')), 'POINTS'
        m_dec = re.search(r'(?i)(?:decrement|decr?\.?)\s*(\d+(?:[.,]\d+)?)', name)
        if m_dec:
            return float(m_dec.group(1).replace(',', '.')), 'POINTS'
        m_num = re.search(r'(?i)(\d+(?:[.,]\d+)?)\s*(?:points?|pts?|pt|point\(s\))?\s*decr?', name)
        if m_num:
            return float(m_num.group(1).replace(',', '.')), 'POINTS'
        return None, None

    @staticmethod
    def score_volatilite(vol_pct) -> float:
        """Calcule la note de risque Volatilité 1 An (0 à 5) - Calibration du 05/11."""
        if vol_pct == "N/A" or pd.isna(vol_pct) or vol_pct is None:
            return "N/A"
        try:
            x_vol = float(vol_pct)
            if x_vol <= 15.0:
                return 0.0
            elif x_vol >= 40.0:
                return 5.0
            else:
                val = 8.68 - 14.53 * math.exp(-0.0343 * x_vol)
                return max(0.0, min(5.0, val))
        except Exception:
            return "N/A"

    @staticmethod
    def score_yield(yield_pct) -> float:
        """Calcule la note de risque Yield du décrément (0 à 5) - Calibration du 05/11."""
        if yield_pct == "N/A" or pd.isna(yield_pct) or yield_pct is None:
            return "N/A"
        try:
            x_yield = float(yield_pct)
            if x_yield <= 4.0:
                return 0.0
            elif x_yield >= 6.90:
                return 5.0
            else:
                val = -0.69 + 0.0370 * math.exp(0.73 * x_yield)
                return max(0.0, min(5.0, val))
        except Exception:
            return "N/A"

    @staticmethod
    def score_ecart(ecart_pct) -> float:
        """Calcule la note de risque Écart Dividende - Décrément (0 à 5) - Calibration du 05/11."""
        if ecart_pct == "N/A" or pd.isna(ecart_pct) or ecart_pct is None:
            return "N/A"
        try:
            x_ecart = float(ecart_pct)
            if x_ecart >= 1.0:
                return 0.0
            elif x_ecart <= -4.5:
                return 5.0
            else:
                val = -1.57 + 2.04 * math.exp(-0.26 * x_ecart)
                return max(0.0, min(5.0, val))
        except Exception:
            return "N/A"

    @staticmethod
    def color_score(score) -> str:
        if score == "N/A" or pd.isna(score):
            return "gray"
        if score <= 1:
            return "#28a745"   # Risque très faible (Vert)
        if score <= 2:
            return "#85c13f"   # Risque faible (Vert clair)
        if score <= 3:
            return "#ffc107"   # Risque modéré (Jaune)
        if score <= 4:
            return "#fd7e14"   # Risque élevé (Orange)
        return "#dc3545"       # Risque très élevé (Rouge)

    def compute_nexo_scores(self) -> dict:
        """Calcule les 3 notes de risque NEXO™ (formules calibrées du 05/11)."""
        # 1. Note Volatilité (1 An)
        vol_1y = self.vol(days=365)
        note_vol = self.score_volatilite(vol_1y)

        # 2. Note Yield & Note Écart (si décrément)
        note_yield = "N/A"
        note_ecart = "N/A"
        if self.dec_val is not None and self.dec_yield_pct != "N/A":
            note_yield = self.score_yield(self.dec_yield_pct)

            if pd.notna(self.dividend_yield) and self.dividend_yield is not None:
                x_ecart = (float(self.dividend_yield) - self.dec_yield) * 100.0
                note_ecart = self.score_ecart(x_ecart)

        return {
            'vol': note_vol,
            'yield': note_yield,
            'ecart': note_ecart,
            'color_vol': self.color_score(note_vol),
            'color_yield': self.color_score(note_yield),
            'color_ecart': self.color_score(note_ecart)
        }

    def to_stress_test_payload(self) -> dict:
        """Prépare la charge utile pour alimentation directe de monte_carlo_2.py."""
        vol_val = self.vol(days=365)
        return {
            'niveau_initial': self.current_price,
            'decrement_annuel': self.dec_val if self.dec_val else 0.0,
            'vol': (vol_val / 100.0) if pd.notna(vol_val) else 0.20,
            'dividend_yield': float(self.dividend_yield) if pd.notna(self.dividend_yield) else 0.03,
            'nom': self.asset_name
        }


# ==============================================================================
# 4. COUCHE QUANTITATIVE : BasketAnalytics
# ==============================================================================

class BasketAnalytics:
    """Modélise l'analyse comparative multi-actifs, le panier équipondéré et les corrélations."""

    def __init__(self, selected_ids: list, asset_options: dict, prices_pivot: pd.DataFrame,
                 cutoff_start: pd.Timestamp, cutoff_end: pd.Timestamp):
        self.selected_ids = [aid for aid in selected_ids if aid in prices_pivot.columns]
        self.asset_options = asset_options
        self.id_to_name = {v: k for k, v in asset_options.items()}

        raw_sub = prices_pivot[self.selected_ids].dropna(how='all')
        self.compare_prices = raw_sub[(raw_sub.index >= cutoff_start) & (raw_sub.index <= cutoff_end)]

        start_dates = self.compare_prices.apply(lambda x: x.first_valid_index()) if not self.compare_prices.empty else pd.Series()
        self.common_start_date = start_dates.max() if not start_dates.empty else pd.NaT

        if pd.notna(self.common_start_date):
            self.compare_prices_common = self.compare_prices[self.compare_prices.index >= self.common_start_date]
            first_prices = self.compare_prices_common.iloc[0]
            self.base_100_prices = (self.compare_prices_common / first_prices) * 100.0
            self.basket_prices = self.base_100_prices.mean(axis=1) if len(self.selected_ids) > 1 else self.base_100_prices.iloc[:, 0]
        else:
            self.compare_prices_common = pd.DataFrame()
            self.base_100_prices = pd.DataFrame()
            self.basket_prices = pd.Series(dtype=float)

    def compute_performance_table(self) -> pd.DataFrame:
        if self.base_100_prices.empty:
            return pd.DataFrame(columns=['Actif', 'Performance'])
        perf_series = (self.base_100_prices.iloc[-1] - 100.0)
        perf_df = perf_series.reset_index()
        perf_df.columns = ['asset_id', 'Performance']
        perf_df['Actif'] = perf_df['asset_id'].map(self.id_to_name)
        return perf_df[['Actif', 'Performance']].sort_values(by='Performance', ascending=False)

    def compute_basket_comparison(self, bench_id, bench_name, prices_pivot: pd.DataFrame) -> tuple:
        """Calcule la comparaison détaillée entre le Panier et le Benchmark sélectionné."""
        if bench_id is None or bench_id not in prices_pivot.columns or self.basket_prices.empty:
            return None, None, None, None

        bench_raw = prices_pivot[bench_id].dropna()
        bench_sub = bench_raw[(bench_raw.index >= self.common_start_date) & (bench_raw.index <= self.compare_prices_common.index.max())]
        if len(bench_sub) < 2:
            return None, None, None, None

        bench_base_100 = (bench_sub / bench_sub.iloc[0]) * 100.0
        basket_perf = float(self.basket_prices.iloc[-1] - 100.0)
        bench_perf = float((bench_sub.iloc[-1] / bench_sub.iloc[0] - 1.0) * 100.0)
        spread_perf = basket_perf - bench_perf

        basket_ret = self.basket_prices.pct_change(fill_method=None).dropna()
        bench_ret = bench_sub.pct_change(fill_method=None).dropna()
        comb_ret = pd.DataFrame({'Panier': basket_ret, 'Benchmark': bench_ret}).dropna()

        # Bêta
        if len(comb_ret) >= 5 and comb_ret['Benchmark'].var() > 0:
            basket_beta = float(comb_ret['Panier'].cov(comb_ret['Benchmark']) / comb_ret['Benchmark'].var())
            beta_disp = f"{basket_beta:.2f}"
        else:
            beta_disp = "N/A"

        # Volatilités
        basket_vol = float(basket_ret.std(ddof=1) * np.sqrt(252) * 100.0) if len(basket_ret) > 1 else np.nan
        bench_vol = float(bench_ret.std(ddof=1) * np.sqrt(252) * 100.0) if len(bench_ret) > 1 else np.nan
        spread_vol = basket_vol - bench_vol if pd.notna(basket_vol) and pd.notna(bench_vol) else np.nan

        # Max Drawdown
        cummax_basket = self.basket_prices.cummax()
        basket_mdd = float(((self.basket_prices - cummax_basket) / cummax_basket).min() * 100.0)
        cummax_bench = bench_sub.cummax()
        bench_mdd = float(((bench_sub - cummax_bench) / cummax_bench).min() * 100.0)
        spread_mdd = basket_mdd - bench_mdd

        bench_col_title = f"Benchmark ({bench_name})"
        comp_df = pd.DataFrame({
            "Métrique": ["Performance Globale", "Volatilité Historique (ann.)", "Max Drawdown"],
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
        })

        return comp_df, bench_base_100, beta_disp, comb_ret


# ==============================================================================
# 5. COUCHE REPORTING : NexoPptxGenerator & ExcelReportGenerator
# ==============================================================================

class NexoPptxGenerator:
    """Générateur de la présentation client PowerPoint native NEXO."""

    @staticmethod
    def hex_to_rgb(hex_str: str) -> RGBColor:
        hex_str = hex_str.lstrip('#')
        if hex_str == "gray":
            return RGBColor(128, 128, 128)
        return RGBColor(*tuple(int(hex_str[i:i+2], 16) for i in (0, 2, 4)))

    @staticmethod
    def set_text(obj, text: str):
        tf = getattr(obj, 'text_frame', None)
        if tf is None or not tf.paragraphs:
            return
        p = tf.paragraphs[0]
        if p.runs:
            p.runs[0].text = str(text)
            for r in p.runs[1:]:
                r.text = ''
        else:
            p.text = str(text)

    @classmethod
    def create_presentation(cls, asset_name: str, desc: str, left_data: list,
                            nexo_data: list, right_df: pd.DataFrame, fig,
                            template_name: str = "template_nexo.pptx") -> io.BytesIO:
        template_path = os.path.join(os.path.dirname(__file__), template_name)
        if not os.path.exists(template_path):
            prs = Presentation()
            prs.slides.add_slide(prs.slide_layouts[6])
            buf = io.BytesIO()
            prs.save(buf)
            buf.seek(0)
            return buf

        prs = Presentation(template_path)
        slide = prs.slides[0]

        try:
            cls.set_text(slide.shapes[1].shapes[0], asset_name)
        except Exception:
            pass

        try:
            cls.set_text(slide.shapes[2], desc)
        except Exception:
            pass

        table_left, table_nexo, table_right, chart_shape = None, None, None, None
        for shape in slide.shapes:
            if shape.has_table:
                cols = len(shape.table.columns)
                if cols == 2:
                    table_left = shape.table
                elif cols == 3:
                    table_nexo = shape.table
                elif cols >= 4:
                    table_right = shape.table
            elif shape.shape_type == 3:
                chart_shape = shape

        # Table gauche (Spot, décrément, dividende)
        try:
            if table_left:
                for r in range(len(table_left.rows)):
                    if r < len(left_data):
                        row_data = left_data[r]
                        for c, val in enumerate(row_data):
                            if c < len(table_left.columns):
                                cls.set_text(table_left.cell(r, c), val)
                    else:
                        for c in range(len(table_left.columns)):
                            cls.set_text(table_left.cell(r, c), "")
        except Exception:
            pass

        # Table centrale (Score NEXO™)
        if nexo_data and table_nexo:
            try:
                if len(table_nexo.rows) > 1 and len(table_nexo.columns) >= 2:
                    cls.set_text(table_nexo.cell(1, 1), "Poids du Décrément")
                for c, item in enumerate(nexo_data):
                    val, color_hex = item
                    if c < len(table_nexo.columns):
                        cell = table_nexo.cell(2, c)
                        cls.set_text(cell, val)
                        if cell.text_frame.paragraphs and cell.text_frame.paragraphs[0].runs:
                            cell.text_frame.paragraphs[0].runs[0].font.color.rgb = cls.hex_to_rgb(color_hex)
            except Exception:
                pass

        # Table droite (Performance / Volatilité / Sharpe / Drawdown)
        try:
            if table_right:
                rows, cols = right_df.shape
                for r in range(rows):
                    for c in range(cols):
                        if r + 1 < len(table_right.rows) and c < len(table_right.columns):
                            val = right_df.iloc[r, c]
                            if val != "MERGE":
                                cls.set_text(table_right.cell(r + 1, c), val)
        except Exception:
            pass

        # Graphique Base 100
        try:
            if chart_shape and fig is not None:
                left, top, width, height = chart_shape.left, chart_shape.top, chart_shape.width, chart_shape.height
                img_bytes = fig.to_image(format="png", width=600, height=350)
                img_buffer = io.BytesIO(img_bytes)

                sp = chart_shape._element
                sp.getparent().remove(sp)
                slide.shapes.add_picture(img_buffer, left, top, width, height)
        except Exception:
            pass

        buf = io.BytesIO()
        prs.save(buf)
        buf.seek(0)
        return buf


class ExcelReportGenerator:
    """Générateur de classeurs Excel multi-onglets structurés."""

    @staticmethod
    def create_report(dfs_dict: dict, figs_dict: dict = None) -> io.BytesIO:
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

            if figs_dict:
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


class PptxReportGenerator:
    """Générateur de rapports PowerPoint multi-slides standards."""

    @staticmethod
    def create_report(dfs_dict: dict, figs_dict: dict, title: str = "Rapport") -> io.BytesIO:
        prs = Presentation()
        title_slide = prs.slides.add_slide(prs.slide_layouts[0])
        title_slide.shapes.title.text = title

        for df_title, df in dfs_dict.items():
            slide = prs.slides.add_slide(prs.slide_layouts[5])
            slide.shapes.title.text = df_title
            rows, cols = df.shape
            table_shape = slide.shapes.add_table(rows + 1, cols, Inches(1), Inches(2), Inches(8), Inches(0.4 * (rows + 1))).table
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

        buf = io.BytesIO()
        prs.save(buf)
        buf.seek(0)
        return buf


# ==============================================================================
# ALIASES DE RÉTRO-COMPATIBILITÉ DIRECTE
# ==============================================================================

create_excel_report = ExcelReportGenerator.create_report
create_pptx_report = PptxReportGenerator.create_report
create_nexo_presentation_pptx = NexoPptxGenerator.create_presentation
extract_decrement = DecrementAnalytics.extract_decrement
color_score = DecrementAnalytics.color_score
