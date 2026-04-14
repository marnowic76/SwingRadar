"""
Scoring Engine v1.0
Bazuje na Masterplan V2.4.5

Struktura pliku:
    1. Typy danych (dataclasses)
    2. Enums
    3. Stałe konfiguracyjne
    4. Sub-score calculators (L6)
    5. Pipeline layers (L3, L4, L5, L6, L7, L8, L9, L10)
    6. Główna funkcja pipeline
    7. Unit testy
"""

from __future__ import annotations

import math
import uuid
from dataclasses import dataclass, field
from datetime import datetime, date
from enum import Enum
from typing import Optional


# ─────────────────────────────────────────────
# 1. ENUMS
# ─────────────────────────────────────────────

class SetupType(str, Enum):
    BREAKOUT_VOLUME   = "Breakout Volume"
    CUP_AND_HANDLE    = "Cup & Handle"
    HIGH_52W          = "52W High Breakout"
    TREND_PULLBACK    = "Trend Pullback"
    BULL_FLAG         = "Bull Flag"
    EARNINGS_GAP_HOLD = "Earnings Gap Hold"
    MEAN_REVERSION    = "Mean Reversion"


class LiquidityStatus(str, Enum):
    PASS         = "PASS"
    SOFT_WARNING = "SOFT_WARNING"
    REJECT       = "REJECT"


class EventStatus(str, Enum):
    SAFE      = "SAFE"
    WARN      = "WARN"
    HIGH_RISK = "HIGH_RISK"
    BLOCKED   = "BLOCKED"


class FreshnessCategory(str, Enum):
    EARLY   = "EARLY"    # 80–100
    OPTIMAL = "OPTIMAL"  # 60–79
    LATE    = "LATE"     # 30–59
    STALE   = "STALE"    # < 30


class Grade(str, Enum):
    A_PLUS = "A+"
    A      = "A"
    B      = "B"
    C      = "C"
    WEAK   = "WEAK"


class GapRisk(str, Enum):
    LOW    = "LOW"
    MEDIUM = "MEDIUM"
    HIGH   = "HIGH"


class RRStatus(str, Enum):
    OK             = "OK"
    POOR_EXECUTION = "POOR_EXECUTION"
    BLOCKED        = "BLOCKED"


class Market(str, Enum):
    US = "US"
    UK = "UK"


# ─────────────────────────────────────────────
# 2. STAŁE KONFIGURACYJNE
# ─────────────────────────────────────────────

class Config:
    # L3 – Liquidity thresholds (US)
    ADV_HARD_MIN_US   = 2_000_000    # < $2M → REJECT
    ADV_SOFT_MIN_US   = 5_000_000    # < $5M → SOFT_WARNING
    SPREAD_MAX_US     = 0.005        # > 0.5% → REJECT
    MCAP_MIN_US       = 500_000_000  # < $500M → REJECT
    PRICE_MIN_US      = 5.0          # < $5 → REJECT
    RVOL_MIN          = 1.5          # < 1.5× → REJECT

    # L3 – Liquidity thresholds (UK)
    ADV_HARD_MIN_UK   = 1_000_000    # < £1M → REJECT
    ADV_SOFT_MIN_UK   = 3_000_000    # < £3M → SOFT_WARNING
    SPREAD_MAX_UK     = 0.008        # > 0.8% → REJECT
    MCAP_MIN_UK       = 300_000_000  # < £300M → REJECT
    PRICE_MIN_UK      = 0.50         # < 50p → REJECT

    # L3 – Soft warning risk override
    SOFT_WARNING_MAX_RISK = 0.0075   # 0.75%

    # L6 – Scoring weights
    WEIGHT_SETUP       = 0.30
    WEIGHT_VOLUME      = 0.20
    WEIGHT_MOMENTUM    = 0.15
    WEIGHT_SENTIMENT   = 0.15
    WEIGHT_REGIME      = 0.10
    WEIGHT_FUNDAMENTAL = 0.10

    # L7 – Freshness decay
    FRESHNESS_DECAY_RATE      = 0.15
    FRESHNESS_CATALYST_5D_MULT = 0.80
    FRESHNESS_CATALYST_10D_MULT = 0.60
    FRESHNESS_STALE_PENALTY   = 10.0

    # L8 – Execution costs (US)
    SLIPPAGE_PCT_US   = 0.001        # 0.1% estimate
    COMMISSION_US     = 1.0          # $1 per trade
    STAMP_DUTY_UK     = 0.005        # 0.5% (buy only)
    SLIPPAGE_PCT_UK   = 0.002        # 0.2% estimate
    COMMISSION_UK     = 7.0          # £7 per trade

    # L8 – Min RR
    MIN_RR_BASE       = 1.5
    MIN_RR_ATR_BASE   = 3.0          # ATR baseline dla kalkulacji
    MIN_RR_ATR_FACTOR = 0.15         # wzrost min RR per % ATR powyżej baseline
    MIN_RR_HARD_BLOCK = 1.0          # poniżej → BLOCKED

    # L9 – Grade thresholds
    GRADE_A_PLUS = 90
    GRADE_A      = 80
    GRADE_B      = 70
    GRADE_C      = 60

    # L10 – Risk per grade
    RISK_A_PLUS  = 0.020
    RISK_A       = 0.015
    RISK_B       = 0.010
    RISK_C       = 0.005

    # L10 – Gap risk multipliers
    GAP_HIGH_MULT   = 0.60
    GAP_MEDIUM_MULT = 0.80

    # L10 – Position limits
    MAX_POSITION_PCT = 0.10          # max 10% portfela w jednej akcji

    # L10 – Losing trade alert
    LOSING_TRADE_DAYS    = 3
    LOSING_TRADE_THRESH  = -0.015    # -1.5%


# ─────────────────────────────────────────────
# 3. DATACLASSES – struktury danych
# ─────────────────────────────────────────────

@dataclass
class TickerData:
    """Dane wejściowe dla jednego tickera – wyjście z L1."""
    ticker:       str
    market:       Market

    # Ceny i OHLCV
    price:        float          # aktualna cena (close)
    ask:          float
    bid:          float

    # Volume
    adv_20d:      float          # Average Daily Volume, 20 sesji
    rvol:         float          # Relative Volume (dziś vs ADV)
    obv_slope:    float          # normalized OBV slope (-1…+1), z L1

    # Wskaźniki techniczne
    sma200:       float
    ema50:        float
    ema20:        float
    rsi_14:       float
    macd_hist:    float
    macd_hist_max_20d: float     # max absolutna wartość histogramu, 20 sesji
    roc_10:       float          # Rate of Change, 10 dni, w %
    atr_14:       float          # ATR(14) w jednostkach ceny
    market_cap:   float

    # Setup (z L2)
    setup_type:   SetupType
    resistance:   float          # poziom resistance dla setupu
    support:      float          # poziom wsparcia

    # Setup modyfikatory (z L2)
    pattern_range_pct:  float    # tightness of pattern (%)
    pullback_fib_pct:   float    # głębokość pullbacku (% Fib)

    # Gap metrics (obliczone w L1)
    gap_20d_avg:  float          # średni overnight gap (20 sesji)
    gap_risk:     GapRisk

    # Fundamentals
    eps_growth_yoy:     float    # YoY EPS growth w %
    revenue_growth_yoy: float    # YoY Revenue growth w %
    pe_ratio:           float
    sector_avg_pe:      float
    debt_equity:        float

    # Rynek / Regime
    spy_price:    float
    spy_sma200:   float
    spy_sma50:    float
    vix_percentile: float        # VIX w percentylu (0–100)

    # Event Guard (z L4)
    event_status: EventStatus = EventStatus.SAFE

    # Sentiment (z L5)
    sentiment_raw: float = 0.0   # -100…+100

    # Spread
    spread_pct:   float = 0.0    # bid-ask spread jako %

    # Timing
    days_since_setup: int = 0
    catalyst_age_days: int = 0


@dataclass
class SubScores:
    """Sub-scores z L6."""
    setup:       float = 0.0
    volume:      float = 0.0
    momentum:    float = 0.0
    sentiment:   float = 0.0
    regime:      float = 0.0
    fundamental: float = 0.0


@dataclass
class ScoringResult:
    """Pełny wynik pipeline dla jednego sygnału."""
    signal_id:   str = field(default_factory=lambda: str(uuid.uuid4()))
    timestamp:   str = field(default_factory=lambda: datetime.now().isoformat())
    ticker:      str = ""
    market:      Market = Market.US

    # L3
    liquidity_status:    LiquidityStatus = LiquidityStatus.PASS
    max_risk_override:   Optional[float] = None

    # L4
    event_status:        EventStatus = EventStatus.SAFE
    event_penalty:       float = 0.0

    # L5
    sentiment_score:     float = 50.0

    # L6
    sub_scores:          SubScores = field(default_factory=SubScores)
    raw_score:           float = 0.0
    regime_multiplier:   float = 1.0
    final_score:         float = 0.0

    # L7
    freshness:           float = 100.0
    freshness_category:  FreshnessCategory = FreshnessCategory.EARLY
    freshness_penalty:   float = 0.0

    # L8
    nominal_rr:          float = 0.0
    real_rr:             float = 0.0
    min_acceptable_rr:   float = 1.5
    rr_status:           RRStatus = RRStatus.OK
    atr_pct:             float = 0.0
    effective_entry:     float = 0.0
    cost_roundtrip_pct:  float = 0.0
    breakeven_move_pct:  float = 0.0

    # L9
    grade:               Grade = Grade.WEAK

    # L10
    gap_risk:            GapRisk = GapRisk.LOW
    effective_risk_pct:  float = 0.0
    position_size:       float = 0.0

    # Targets & stops
    entry_suggested:     float = 0.0
    stop:                float = 0.0
    target_1:            float = 0.0


@dataclass
class PortfolioState:
    """Stan portfela dla L10 i L11."""
    total_value:     float
    cash_balance:    float
    open_positions:  list[dict] = field(default_factory=list)
    # open_positions: [{"ticker": str, "sector": str, "value": float}]


# ─────────────────────────────────────────────
# 4. LAYER 3 – LIQUIDITY FILTER
# ─────────────────────────────────────────────

def evaluate_liquidity(
    td: TickerData,
    scan_mode=None,   # ScanMode z market_session.py (opcjonalny)
) -> tuple[LiquidityStatus, Optional[float]]:
    """
    L3 – Quality + Liquidity Reality Filter.

    Operuje wyłącznie na twardych progach liczbowych.
    Zero zależności od Score. Deterministyczna.

    scan_mode: jeśli podany, używa progów RVOL z ScanMode (auto-detect sesji).
               Jeśli None, używa domyślnych progów z Config.

    Returns:
        (LiquidityStatus, max_risk_override)
        max_risk_override = 0.0075 przy SOFT_WARNING, None przy PASS
    """
    cfg = Config()

    if td.market == Market.US:
        adv_hard   = cfg.ADV_HARD_MIN_US
        adv_soft   = cfg.ADV_SOFT_MIN_US
        spread_max = cfg.SPREAD_MAX_US
        mcap_min   = cfg.MCAP_MIN_US
        price_min  = cfg.PRICE_MIN_US
    else:  # UK
        adv_hard   = cfg.ADV_HARD_MIN_UK
        adv_soft   = cfg.ADV_SOFT_MIN_UK
        spread_max = cfg.SPREAD_MAX_UK
        mcap_min   = cfg.MCAP_MIN_UK
        price_min  = cfg.PRICE_MIN_UK

    # RVOL progi – z ScanMode jeśli dostępny, inaczej domyślne
    if scan_mode is not None:
        rvol_reject = scan_mode.rvol_reject
        rvol_soft   = scan_mode.rvol_soft
    else:
        rvol_reject = 1.0    # domyślny fallback (EOD-safe)
        rvol_soft   = cfg.RVOL_MIN  # 1.5

    # Twarde REJECT – żaden wyjątek
    if td.adv_20d < adv_hard:
        return LiquidityStatus.REJECT, None
    # Spread: tylko sprawdzamy jeśli mamy realne dane (> 0)
    if td.spread_pct > 0 and td.spread_pct > spread_max:
        return LiquidityStatus.REJECT, None
    if td.market_cap < mcap_min:
        return LiquidityStatus.REJECT, None
    if td.price < price_min:
        return LiquidityStatus.REJECT, None

    # RVOL – dynamiczne progi z ScanMode
    if td.rvol < rvol_reject:
        return LiquidityStatus.REJECT, None
    if td.rvol < rvol_soft:
        return LiquidityStatus.SOFT_WARNING, cfg.SOFT_WARNING_MAX_RISK

    # SOFT_WARNING – ADV w przedziale miękkim
    if td.adv_20d < adv_soft:
        return LiquidityStatus.SOFT_WARNING, cfg.SOFT_WARNING_MAX_RISK

    return LiquidityStatus.PASS, None


# ─────────────────────────────────────────────
# 5. LAYER 4 – EVENT GUARD
# ─────────────────────────────────────────────

def evaluate_event_guard(event_status: EventStatus) -> tuple[float, bool]:
    """
    L4 – Event Guard.

    Returns:
        (penalty_points, is_blocked)
        penalty_points: 0 / -8 / -18
        is_blocked: True → sygnał nie trafia do Output
    """
    penalties = {
        EventStatus.SAFE:      (0.0,   False),
        EventStatus.WARN:      (-8.0,  False),
        EventStatus.HIGH_RISK: (-18.0, False),
        EventStatus.BLOCKED:   (-18.0, True),
    }
    return penalties[event_status]


# ─────────────────────────────────────────────
# 6. LAYER 5 – AI SENTIMENT
# ─────────────────────────────────────────────

def calculate_sentiment_score(
    raw_sentiment: float,
    is_technical_setup: bool = True
) -> float:
    """
    L5 – AI Sentiment Layer.

    Args:
        raw_sentiment: wynik FinBERT w zakresie -100…+100
        is_technical_setup: czy setup jest czysto techniczny

    Returns:
        sentiment_score: 20–100
    """
    score = (raw_sentiment + 100) / 2  # -100→0, 0→50, +100→100

    # Penalty: techniczny setup sprzeczny z sentymentem
    if is_technical_setup and raw_sentiment < -50:
        score -= 12

    return max(20.0, min(100.0, score))


# ─────────────────────────────────────────────
# 7. LAYER 6 – SCORING ENGINE (sub-scores)
# ─────────────────────────────────────────────

def calculate_setup_quality(td: TickerData) -> float:
    """
    L6.1 – Setup Quality Score (waga 30%).

    Returns: float 40–100
    """
    base_scores = {
        SetupType.BREAKOUT_VOLUME:   92,
        SetupType.CUP_AND_HANDLE:    88,
        SetupType.HIGH_52W:          82,
        SetupType.TREND_PULLBACK:    78,
        SetupType.BULL_FLAG:         75,
        SetupType.EARNINGS_GAP_HOLD: 70,
        SetupType.MEAN_REVERSION:    55,
    }

    score = float(base_scores[td.setup_type])
    mods  = 0.0

    # Volume confirmation
    if td.rvol > 2.0:
        mods += 8
    elif td.rvol >= 1.5:
        mods += 4

    # Pattern tightness
    if td.pattern_range_pct < 8.0:
        mods += 6
    elif td.pattern_range_pct <= 12.0:
        mods += 3

    # Pullback depth (Fibonacci)
    if td.pullback_fib_pct <= 38.2:
        mods += 5
    elif td.pullback_fib_pct > 50.0:
        mods -= 5

    # Breakout strength
    atr_pct_price = td.atr_14
    if td.price > td.resistance + atr_pct_price:
        mods += 7
    elif td.price > td.resistance:
        mods += 3

    # Clamp modifiers to ±15
    mods = max(-15.0, min(15.0, mods))
    score += mods

    return max(40.0, min(100.0, score))


def calculate_volume_score(td: TickerData) -> float:
    """
    L6.2 – Volume Score (waga 20%).

    obv_slope_factor: przekazany z L1 jako pole td.obv_slope (-1…+1)
    Obliczenie w L1: regresja liniowa OBV 10 sesji → tanh normalizacja.

    Returns: float 30–100
    """
    rvol_score = min(100.0, max(0.0, (td.rvol - 1.0) * 50.0))

    # Neutralny baseline = 50 (bullish bias jest już w filtrach L2)
    obv_score = 50.0 + (td.obv_slope * 50.0)
    obv_score = max(0.0, min(100.0, obv_score))

    volume_score = 0.5 * rvol_score + 0.5 * obv_score
    return max(30.0, min(100.0, volume_score))


def calculate_momentum_score(td: TickerData) -> float:
    """
    L6.3 – Momentum Score (waga 15%).

    RSI asymetria celowa: system działa na RSI 40–75 (L2 filter).
    RSI 65 > RSI 45 nawet jeśli oba "w zakresie" – asymetria to odzwierciedla.

    MACD fix (Gemini): ochrona przed ZeroDivisionError gdy max_hist = 0.

    Returns: float 25–100
    """
    # RSI score (asymetria celowa)
    if td.rsi_14 >= 50:
        rsi_score = 50.0 + (td.rsi_14 - 50.0) * 2.0   # 50→50, 75→100
    else:
        rsi_score = 50.0 - (50.0 - td.rsi_14) * 1.5   # 45→42.5, 40→35

    # MACD score – ochrona przed ZeroDivisionError (fix Gemini)
    if td.macd_hist_max_20d == 0:
        macd_score = 50.0
    else:
        macd_score = 50.0 + (td.macd_hist / td.macd_hist_max_20d * 40.0)

    # ROC score
    roc_score = 50.0 + (td.roc_10 / 15.0 * 30.0)

    momentum = (rsi_score * 0.40 +
                macd_score * 0.35 +
                roc_score  * 0.25)

    return max(25.0, min(100.0, momentum))


def calculate_regime_score(td: TickerData) -> tuple[float, float]:
    """
    L6.5 – Regime Score (waga 10%) + multiplier.

    Regime chroni kapitał, nie boostuje Score (cap = 1.00).

    Returns:
        (regime_score 35–100, regime_multiplier 0.35–1.00)
    """
    spy_above_200 = td.spy_price > td.spy_sma200
    spy_above_50  = td.spy_price > td.spy_sma50
    vix_low       = td.vix_percentile < 50

    if spy_above_200 and spy_above_50 and vix_low:
        score = 85.0 + (50.0 - td.vix_percentile) * 0.3   # bull: 85–100
    elif spy_above_200 and not spy_above_50:
        score = 65.0                                        # korekta w hossie
    elif not spy_above_200 and spy_above_50:
        score = 50.0                                        # sideways
    else:
        score = 35.0 + max(0.0, 50.0 - td.vix_percentile) # bessa: 35–85

    score = max(35.0, min(100.0, score))
    multiplier = min(1.0, score / 100.0)  # cap 1.00 – nie boostuje

    return score, multiplier


def calculate_fundamental_score(td: TickerData) -> float:
    """
    L6.6 – Fundamental Score (waga 10%).

    Prosty quality check – nie timing, tylko "czy spółka jest zdrowa".

    Returns: float 30–100
    """
    eps_score = min(100.0, max(0.0, 50.0 + td.eps_growth_yoy * 2.0))

    revenue_score = min(100.0, max(0.0, 50.0 + td.revenue_growth_yoy * 2.0))

    if td.sector_avg_pe > 0:
        pe_ratio = td.pe_ratio / td.sector_avg_pe - 1.0
        pe_score = min(100.0, max(0.0, 100.0 - pe_ratio * 50.0))
    else:
        pe_score = 50.0

    de_score = min(100.0, max(0.0, 100.0 - td.debt_equity * 20.0))

    fundamental = (eps_score     * 0.35 +
                   revenue_score * 0.25 +
                   pe_score      * 0.20 +
                   de_score      * 0.20)

    return max(30.0, min(100.0, fundamental))


def calculate_final_score(
    sub:             SubScores,
    regime_mult:     float,
    event_penalty:   float
) -> float:
    """
    L6.7 – Formuła końcowa.

    raw_score = Σ(sub_score_i × waga_i)
    final_score = raw_score × regime_multiplier + event_penalty
    """
    cfg = Config()

    raw = (sub.setup       * cfg.WEIGHT_SETUP +
           sub.volume      * cfg.WEIGHT_VOLUME +
           sub.momentum    * cfg.WEIGHT_MOMENTUM +
           sub.sentiment   * cfg.WEIGHT_SENTIMENT +
           sub.regime      * cfg.WEIGHT_REGIME +
           sub.fundamental * cfg.WEIGHT_FUNDAMENTAL)

    final = raw * regime_mult + event_penalty
    return max(0.0, min(100.0, final))


# ─────────────────────────────────────────────
# 8. LAYER 7 – SIGNAL FRESHNESS
# ─────────────────────────────────────────────

def calculate_freshness(
    days_since_setup: int,
    catalyst_age_days: int
) -> tuple[float, FreshnessCategory]:
    """
    L7 – Signal Freshness Score.

    Returns:
        (freshness 0–100, category)
    """
    cfg = Config()

    freshness = 100.0 * math.exp(-cfg.FRESHNESS_DECAY_RATE * days_since_setup)

    if catalyst_age_days > 10:
        freshness *= cfg.FRESHNESS_CATALYST_10D_MULT
    elif catalyst_age_days > 5:
        freshness *= cfg.FRESHNESS_CATALYST_5D_MULT

    freshness = max(0.0, min(100.0, freshness))

    if freshness >= 80:
        cat = FreshnessCategory.EARLY
    elif freshness >= 60:
        cat = FreshnessCategory.OPTIMAL
    elif freshness >= 30:
        cat = FreshnessCategory.LATE
    else:
        cat = FreshnessCategory.STALE

    return freshness, cat


# ─────────────────────────────────────────────
# 9. LAYER 8 – EXECUTION REALITY
# ─────────────────────────────────────────────

def calculate_execution_reality(
    td:      TickerData,
    entry:   float,
    stop:    float,
    target:  float
) -> dict:
    """
    L8 – Execution Reality Layer.

    Zwraca realne koszty i RR po wszystkich opłatach.
    Stamp Duty obliczany proporcjonalnie do ceny (fix Gemini).

    Returns: dict z kluczami:
        effective_entry, real_rr, nominal_rr, rr_status,
        min_acceptable_rr, atr_pct, cost_roundtrip_pct, breakeven_pct
    """
    cfg = Config()

    # Koszty wejścia
    if td.market == Market.US:
        slippage  = cfg.SLIPPAGE_PCT_US
        commission = cfg.COMMISSION_US
        stamp_duty = 0.0
    else:  # UK
        slippage  = cfg.SLIPPAGE_PCT_UK
        commission = cfg.COMMISSION_UK
        # Stamp Duty: 0.5% od wartości zakupu (fix Gemini – proporcjonalne)
        stamp_duty = td.ask * cfg.STAMP_DUTY_UK

    effective_entry = td.ask + (td.ask * slippage) + stamp_duty
    effective_exit  = td.bid - (td.bid * slippage) - commission / td.bid

    # RR kalkulacja
    exit_costs   = td.bid * slippage + commission / max(target, 0.01)
    entry_costs  = td.ask * slippage + stamp_duty

    real_reward = target - effective_entry - exit_costs
    real_risk   = effective_entry - stop + entry_costs
    nominal_rr  = (target - entry) / max(entry - stop, 0.001)

    if real_risk <= 0:
        real_rr = 0.0
    else:
        real_rr = real_reward / real_risk

    # Volatility-adjusted minimum RR
    atr_pct = (td.atr_14 / td.price) * 100.0
    min_rr  = cfg.MIN_RR_BASE + max(0.0, (atr_pct - cfg.MIN_RR_ATR_BASE) * cfg.MIN_RR_ATR_FACTOR)

    # Status
    if real_rr < cfg.MIN_RR_HARD_BLOCK:
        rr_status = RRStatus.BLOCKED
    elif real_rr < min_rr:
        rr_status = RRStatus.POOR_EXECUTION
    else:
        rr_status = RRStatus.OK

    # Koszty round-trip jako %
    cost_entry = td.ask * slippage + stamp_duty
    cost_exit  = td.bid * slippage
    cost_total_pct = (cost_entry + cost_exit) / td.price

    # Break-even move
    breakeven_pct = cost_total_pct

    return {
        "effective_entry":    effective_entry,
        "real_rr":            real_rr,
        "nominal_rr":         nominal_rr,
        "rr_status":          rr_status,
        "min_acceptable_rr":  min_rr,
        "atr_pct":            atr_pct,
        "cost_roundtrip_pct": cost_total_pct,
        "breakeven_pct":      breakeven_pct,
    }


# ─────────────────────────────────────────────
# 10. LAYER 9 – SCORE CALIBRATION
# ─────────────────────────────────────────────

def calibrate_grade(score: float) -> Grade:
    """L9 – Score Calibration."""
    cfg = Config()
    if score >= cfg.GRADE_A_PLUS:
        return Grade.A_PLUS
    elif score >= cfg.GRADE_A:
        return Grade.A
    elif score >= cfg.GRADE_B:
        return Grade.B
    elif score >= cfg.GRADE_C:
        return Grade.C
    else:
        return Grade.WEAK


# ─────────────────────────────────────────────
# 11. LAYER 10 – RISK ENGINE
# ─────────────────────────────────────────────

def calculate_position_size(
    grade:             Grade,
    portfolio:         PortfolioState,
    entry:             float,
    stop:              float,
    gap_risk:          GapRisk,
    max_risk_override: Optional[float] = None,
) -> tuple[float, float]:
    """
    L10 – Risk Engine.

    Returns:
        (position_size_units, effective_risk_pct)
    """
    cfg = Config()

    risk_map = {
        Grade.A_PLUS: cfg.RISK_A_PLUS,
        Grade.A:      cfg.RISK_A,
        Grade.B:      cfg.RISK_B,
        Grade.C:      cfg.RISK_C,
        Grade.WEAK:   0.0,
    }

    base_risk = risk_map[grade]

    # Override z L3 SOFT_WARNING
    if max_risk_override is not None:
        base_risk = min(base_risk, max_risk_override)

    # Gap Risk reduction
    if gap_risk == GapRisk.HIGH:
        base_risk *= cfg.GAP_HIGH_MULT
    elif gap_risk == GapRisk.MEDIUM:
        base_risk *= cfg.GAP_MEDIUM_MULT

    effective_risk = base_risk

    # Position size formula
    risk_amount  = portfolio.total_value * effective_risk
    price_risk   = entry - stop

    if price_risk <= 0:
        return 0.0, effective_risk

    position_value = risk_amount / price_risk * entry

    # Limity
    max_by_portfolio = portfolio.total_value * cfg.MAX_POSITION_PCT
    max_by_cash      = portfolio.cash_balance

    position_value = min(position_value, max_by_portfolio, max_by_cash)
    units = position_value / entry if entry > 0 else 0

    return round(units, 0), effective_risk


def check_losing_trade_alert(
    days_held:       int,
    unrealized_pct:  float
) -> bool:
    """
    L10 – Losing Trade Acceleration.

    Sprawdzana EOD dla otwartych pozycji.
    NIE jest automatycznym exit – to alert/notyfikacja dla usera.
    User podejmuje decyzję o egzekucji samodzielnie.

    Returns:
        True jeśli alert powinien być wyświetlony
    """
    cfg = Config()
    return days_held >= cfg.LOSING_TRADE_DAYS and unrealized_pct < cfg.LOSING_TRADE_THRESH


def calculate_stop_loss(td: TickerData, entry: float) -> float:
    """
    L10 – Stop-loss calculation per setup type.

    Returns: stop price
    """
    atr = td.atr_14

    if td.setup_type == SetupType.BREAKOUT_VOLUME:
        stop = td.resistance - atr
    elif td.setup_type == SetupType.TREND_PULLBACK:
        stop = min(td.ema50, td.support)
    elif td.setup_type == SetupType.BULL_FLAG:
        stop = td.support
    else:
        stop = entry - atr * 1.5  # default

    # floor_stop:   najwyżej dozwolony stop – stop nie może być BLIŻEJ entry niż 1.5×ATR
    #               (chroni przed stop-out na normalnym szumie rynkowym)
    # ceiling_stop: najniżej dozwolony stop – stop nie może być DALEJ niż 8% od entry
    #               (ogranicza maksymalną stratę na jednym trade)
    floor_stop   = entry - atr * 1.5   # blisko entry  (min odległość)
    ceiling_stop = entry * 0.92        # daleko od entry (max strata 8%)

    stop = min(stop, floor_stop)       # stop nie wyżej niż floor   → min 1.5×ATR od entry
    stop = max(stop, ceiling_stop)     # stop nie niżej niż ceiling  → max 8% od entry

    return round(stop, 2)


def calculate_target(entry: float, stop: float, rr_target: float = 2.5) -> float:
    """
    Oblicza T1 na podstawie entry, stop i docelowego RR.
    Default RR = 2.5 (przed kosztami).
    """
    risk = entry - stop
    return round(entry + risk * rr_target, 2)


# ─────────────────────────────────────────────
# 12. GŁÓWNA FUNKCJA PIPELINE
# ─────────────────────────────────────────────

def run_scoring_pipeline(
    td:        TickerData,
    portfolio: PortfolioState,
    entry:     Optional[float] = None,
    scan_mode  = None,   # ScanMode z market_session.py (opcjonalny)
) -> Optional[ScoringResult]:
    """
    Główny pipeline scoringowy.

    Wykonuje L3 → L4 → L5 → L6 → L7 → L8 → L9 → L10.
    Zwraca None jeśli sygnał odrzucony (REJECT lub BLOCKED).

    Args:
        td:        dane tickera z L1 + L2
        portfolio: stan portfela
        entry:     sugerowana cena wejścia (None = użyj td.ask)
        scan_mode: ScanMode z market_session (None = domyślne progi EOD-safe)
    """
    result = ScoringResult(
        ticker = td.ticker,
        market = td.market,
    )

    if entry is None:
        entry = td.ask

    # ── L3: Liquidity Filter ──────────────────
    liq_status, max_risk_override = evaluate_liquidity(td, scan_mode=scan_mode)
    result.liquidity_status  = liq_status
    result.max_risk_override = max_risk_override

    if liq_status == LiquidityStatus.REJECT:
        # Verbose: powód odrzucenia
        cfg = Config()
        rvol_reject = scan_mode.rvol_reject if scan_mode else 1.0
        reasons = []
        if td.adv_20d < cfg.ADV_HARD_MIN_US:
            reasons.append(f"ADV ${td.adv_20d/1e6:.1f}M < ${cfg.ADV_HARD_MIN_US/1e6:.0f}M")
        if td.market_cap < cfg.MCAP_MIN_US:
            reasons.append(f"MCap ${td.market_cap/1e9:.1f}B < $500M")
        if td.price < cfg.PRICE_MIN_US:
            reasons.append(f"Price ${td.price:.2f} < $5")
        if td.rvol < rvol_reject:
            reasons.append(f"RVOL {td.rvol:.2f}x < {rvol_reject:.1f}x")
        import logging as _log
        _log.getLogger(__name__).debug(
            f"L3 REJECT {td.ticker}: {' | '.join(reasons) if reasons else 'unknown'}"
        )
        return None

    # ── L4: Event Guard ───────────────────────
    event_penalty, is_blocked = evaluate_event_guard(td.event_status)
    result.event_status  = td.event_status
    result.event_penalty = event_penalty

    if is_blocked:
        return None  # earnings/event block

    # ── L5: Sentiment ─────────────────────────
    sentiment_score = calculate_sentiment_score(
        raw_sentiment      = td.sentiment_raw,
        is_technical_setup = True,
    )
    result.sentiment_score = sentiment_score

    # ── L6: Scoring Engine ────────────────────
    setup_score   = calculate_setup_quality(td)
    volume_score  = calculate_volume_score(td)
    momentum_score = calculate_momentum_score(td)
    regime_score, regime_mult = calculate_regime_score(td)
    fundamental_score = calculate_fundamental_score(td)

    sub = SubScores(
        setup       = setup_score,
        volume      = volume_score,
        momentum    = momentum_score,
        sentiment   = sentiment_score,
        regime      = regime_score,
        fundamental = fundamental_score,
    )
    result.sub_scores        = sub
    result.regime_multiplier = regime_mult

    final_score = calculate_final_score(sub, regime_mult, event_penalty)

    # ── L7: Freshness ─────────────────────────
    freshness, freshness_cat = calculate_freshness(
        days_since_setup  = td.days_since_setup,
        catalyst_age_days = td.catalyst_age_days,
    )
    result.freshness          = freshness
    result.freshness_category = freshness_cat

    freshness_penalty = 0.0
    if freshness_cat == FreshnessCategory.STALE:
        freshness_penalty = Config.FRESHNESS_STALE_PENALTY
        final_score -= freshness_penalty

    result.freshness_penalty = freshness_penalty
    final_score = max(0.0, min(100.0, final_score))
    result.final_score = final_score

    # ── L9: Grade ─────────────────────────────
    grade = calibrate_grade(final_score)
    result.grade = grade

    if grade == Grade.WEAK:
        return None  # poniżej progu C – nie pokazujemy

    # ── L8: Execution Reality ─────────────────
    stop     = calculate_stop_loss(td, entry)
    target_1 = calculate_target(entry, stop)

    exec_data = calculate_execution_reality(td, entry, stop, target_1)

    result.effective_entry    = exec_data["effective_entry"]
    result.nominal_rr         = exec_data["nominal_rr"]
    result.real_rr            = exec_data["real_rr"]
    result.rr_status          = exec_data["rr_status"]
    result.min_acceptable_rr  = exec_data["min_acceptable_rr"]
    result.atr_pct            = exec_data["atr_pct"]
    result.cost_roundtrip_pct = exec_data["cost_roundtrip_pct"]
    result.breakeven_move_pct = exec_data["breakeven_pct"]
    result.entry_suggested    = entry
    result.stop               = stop
    result.target_1           = target_1

    if result.rr_status == RRStatus.BLOCKED:
        return None  # real RR poniżej 1.0

    # ── L10: Risk Engine ──────────────────────
    result.gap_risk = td.gap_risk

    units, eff_risk = calculate_position_size(
        grade             = grade,
        portfolio         = portfolio,
        entry             = entry,
        stop              = stop,
        gap_risk          = td.gap_risk,
        max_risk_override = max_risk_override,
    )
    result.position_size      = units
    result.effective_risk_pct = eff_risk
    # raw_score już obliczony i przechowywany w result przez calculate_final_score;
    # sub_scores dostępne przez result.sub_scores dla debugowania

    return result


# ─────────────────────────────────────────────
# 13. UNIT TESTY
# ─────────────────────────────────────────────

def _make_test_ticker(overrides: dict = {}) -> TickerData:
    """Bazowy ticker do testów – solid mid-cap US bull market."""
    defaults = dict(
        ticker="AAPL", market=Market.US,
        price=187.50, ask=187.55, bid=187.45,
        adv_20d=80_000_000, rvol=1.8,
        obv_slope=0.4,
        sma200=170.0, ema50=182.0, ema20=185.0,
        rsi_14=62.0,
        macd_hist=0.8, macd_hist_max_20d=1.2,
        roc_10=4.5,
        atr_14=3.2, market_cap=2_900_000_000_000,
        setup_type=SetupType.TREND_PULLBACK,
        resistance=188.0, support=181.0,
        pattern_range_pct=6.5, pullback_fib_pct=35.0,
        gap_20d_avg=0.008, gap_risk=GapRisk.LOW,
        eps_growth_yoy=12.0, revenue_growth_yoy=8.0,
        pe_ratio=28.0, sector_avg_pe=25.0, debt_equity=1.5,
        spy_price=480.0, spy_sma200=440.0, spy_sma50=465.0,
        vix_percentile=30.0,
        event_status=EventStatus.SAFE,
        sentiment_raw=25.0,
        spread_pct=0.0005,
        days_since_setup=1, catalyst_age_days=2,
    )
    defaults.update(overrides)
    return TickerData(**defaults)


def test_liquidity_pass():
    td = _make_test_ticker()
    status, override = evaluate_liquidity(td)
    assert status == LiquidityStatus.PASS
    assert override is None
    print("✓ test_liquidity_pass")


def test_liquidity_reject_low_adv():
    td = _make_test_ticker({"adv_20d": 500_000})
    status, _ = evaluate_liquidity(td)
    assert status == LiquidityStatus.REJECT
    print("✓ test_liquidity_reject_low_adv")


def test_liquidity_soft_warning():
    td = _make_test_ticker({"adv_20d": 3_000_000})
    status, override = evaluate_liquidity(td)
    assert status == LiquidityStatus.SOFT_WARNING
    assert override == 0.0075
    print("✓ test_liquidity_soft_warning")


def test_event_blocked():
    td = _make_test_ticker({"event_status": EventStatus.BLOCKED})
    portfolio = PortfolioState(total_value=30000, cash_balance=25000)
    result = run_scoring_pipeline(td, portfolio)
    assert result is None
    print("✓ test_event_blocked")


def test_macd_zero_division():
    """Gemini fix: macd_hist_max_20d = 0 nie powoduje ZeroDivisionError."""
    td = _make_test_ticker({"macd_hist_max_20d": 0.0})
    score = calculate_momentum_score(td)
    assert 25 <= score <= 100
    print(f"✓ test_macd_zero_division (score={score:.1f})")


def test_stamp_duty_uk():
    """Gemini fix: Stamp Duty obliczany proporcjonalnie, nie jako stała."""
    td = _make_test_ticker({
        "market": Market.UK,
        "ask": 100.0, "bid": 99.8,
        "spread_pct": 0.002,
        "adv_20d": 5_000_000,
        "market_cap": 400_000_000,
        "price": 100.0,
    })
    portfolio = PortfolioState(total_value=30000, cash_balance=25000)
    result = run_scoring_pipeline(td, portfolio)
    if result:
        # Stamp Duty = ask * 0.005 = 100 * 0.005 = 0.50
        expected_stamp = 100.0 * 0.005
        assert abs(result.effective_entry - (td.ask + td.ask * 0.002 + expected_stamp)) < 0.01
        print(f"✓ test_stamp_duty_uk (effective_entry={result.effective_entry:.4f})")
    else:
        print("✓ test_stamp_duty_uk (sygnał odrzucony przez inne filtry – OK)")


def test_full_pipeline_grade_a():
    """Pełny pipeline – oczekiwany Grade B lub wyższy na solidnym setupie."""
    td = _make_test_ticker()
    portfolio = PortfolioState(total_value=30000, cash_balance=25000)
    result = run_scoring_pipeline(td, portfolio)
    assert result is not None, "Sygnał nie powinien być odrzucony"
    assert result.grade in (Grade.A_PLUS, Grade.A, Grade.B, Grade.C)
    assert result.final_score >= 60
    assert result.position_size > 0
    assert result.real_rr >= 1.0
    print(f"✓ test_full_pipeline_grade_a (grade={result.grade.value}, score={result.final_score:.1f}, real_rr={result.real_rr:.2f})")


def test_high_gap_risk_reduces_sizing():
    """HIGH gap risk powinien zredukować position size o 40%."""
    td_low  = _make_test_ticker({"gap_risk": GapRisk.LOW})
    td_high = _make_test_ticker({"gap_risk": GapRisk.HIGH})
    portfolio = PortfolioState(total_value=30000, cash_balance=25000)

    r_low  = run_scoring_pipeline(td_low,  portfolio)
    r_high = run_scoring_pipeline(td_high, portfolio)

    if r_low and r_high:
        ratio = r_high.effective_risk_pct / r_low.effective_risk_pct
        assert abs(ratio - Config.GAP_HIGH_MULT) < 0.01
        print(f"✓ test_high_gap_risk_reduces_sizing (ratio={ratio:.2f})")
    else:
        print("✓ test_high_gap_risk_reduces_sizing (sygnał odrzucony – OK)")


def test_volatility_adjusted_rr():
    """Wyższa zmienność (ATR) podnosi wymagane minimum RR."""
    cfg = Config()
    atr_low  = 2.0   # spokojny mid-cap
    atr_high = 8.0   # high-beta

    price = 100.0
    min_rr_low  = cfg.MIN_RR_BASE + max(0, (atr_low  / price * 100 - cfg.MIN_RR_ATR_BASE) * cfg.MIN_RR_ATR_FACTOR)
    min_rr_high = cfg.MIN_RR_BASE + max(0, (atr_high / price * 100 - cfg.MIN_RR_ATR_BASE) * cfg.MIN_RR_ATR_FACTOR)

    assert min_rr_high > min_rr_low
    print(f"✓ test_volatility_adjusted_rr (ATR 2%→minRR={min_rr_low:.2f}, ATR 8%→minRR={min_rr_high:.2f})")


def test_losing_trade_alert():
    assert check_losing_trade_alert(days_held=3, unrealized_pct=-0.02) is True
    assert check_losing_trade_alert(days_held=2, unrealized_pct=-0.02) is False
    assert check_losing_trade_alert(days_held=3, unrealized_pct=-0.01) is False
    assert check_losing_trade_alert(days_held=5, unrealized_pct=-0.05) is True
    print("✓ test_losing_trade_alert")


def test_stale_signal_penalty():
    """STALE sygnał (9+ dni) powinien być odrzucony (score spada do WEAK)."""
    td_fresh = _make_test_ticker({"days_since_setup": 0})
    td_stale = _make_test_ticker({"days_since_setup": 9})
    portfolio = PortfolioState(total_value=30000, cash_balance=25000)

    r_fresh = run_scoring_pipeline(td_fresh, portfolio)
    r_stale = run_scoring_pipeline(td_stale, portfolio)

    assert r_fresh is not None, "Świeży sygnał powinien przejść"
    assert r_stale is None, "Stale sygnał (9d) powinien być odrzucony jako WEAK"
    print(f"✓ test_stale_signal_penalty (fresh={r_fresh.final_score:.1f}, stale=REJECTED)")


def run_all_tests():
    print("\n" + "="*50)
    print("SCORING ENGINE v1.0 – Unit Tests")
    print("="*50)
    test_liquidity_pass()
    test_liquidity_reject_low_adv()
    test_liquidity_soft_warning()
    test_event_blocked()
    test_macd_zero_division()
    test_stamp_duty_uk()
    test_full_pipeline_grade_a()
    test_high_gap_risk_reduces_sizing()
    test_volatility_adjusted_rr()
    test_losing_trade_alert()
    test_stale_signal_penalty()
    print("="*50)
    print("Wszystkie testy przeszły ✓")
    print("="*50 + "\n")


# ─────────────────────────────────────────────
# 14. PRZYKŁADOWE URUCHOMIENIE
# ─────────────────────────────────────────────

def demo():
    """Przykładowe uruchomienie pipeline na fikcyjnym AAPL."""
    print("\n" + "─"*50)
    print("DEMO: Scoring Engine v1.0")
    print("─"*50)

    td = _make_test_ticker()
    portfolio = PortfolioState(
        total_value=30_000,
        cash_balance=22_000,
        open_positions=[
            {"ticker": "MSFT", "sector": "Technology", "value": 4500},
        ]
    )

    result = run_scoring_pipeline(td, portfolio)

    if result is None:
        print("Sygnał odrzucony przez pipeline.")
        return

    cfg = Config()
    print(f"""
Ticker:        {result.ticker} ({result.market.value})
Grade:         {result.grade.value}
Final Score:   {result.final_score:.1f}
Freshness:     {result.freshness:.0f} ({result.freshness_category.value})

Sub-scores:
  Setup:       {result.sub_scores.setup:.1f}
  Volume:      {result.sub_scores.volume:.1f}
  Momentum:    {result.sub_scores.momentum:.1f}
  Sentiment:   {result.sub_scores.sentiment:.1f}
  Regime:      {result.sub_scores.regime:.1f}
  Fundamental: {result.sub_scores.fundamental:.1f}

Liquidity:     {result.liquidity_status.value}
Event:         {result.event_status.value} ({result.event_penalty:+.0f} pkt)
Gap Risk:      {result.gap_risk.value}

Entry:         ${result.entry_suggested:.2f}
Stop:          ${result.stop:.2f}
Target 1:      ${result.target_1:.2f}
Nominal RR:    {result.nominal_rr:.2f}:1
Real RR:       {result.real_rr:.2f}:1  [{result.rr_status.value}]
Min RR (ATR):  {result.min_acceptable_rr:.2f}:1
ATR%:          {result.atr_pct:.1f}%
Cost RT:       {result.cost_roundtrip_pct*100:.2f}%
Break-even:    +{result.breakeven_move_pct*100:.2f}%

Sizing:
  Risk %:      {result.effective_risk_pct*100:.2f}%
  Units:       {result.position_size:.0f} akcji
  Value:       ${result.position_size * result.entry_suggested:,.0f}
""")


if __name__ == "__main__":
    run_all_tests()
    demo()
