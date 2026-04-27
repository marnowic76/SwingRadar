"""
Scoring Engine V2.41 - SwingRadar DSS
Odpowiada za wielowymiarową ocenę spółek (Model 50/30/20).
Wdraża Veto Fundamentalne oraz kary za nadmierne luki wzrostowe.

ZMIANY V2.41:
- [NEW] calculate_event_score() uwzględnia recent 8-K:
  8-K złożony w ostatnich 3 dniach → +20 pkt (świeży katalizator)
  8-K złożony w ostatnich 7 dniach → +10 pkt (aktywna spółka)
ZMIANY V2.40:
- [NEW] calculate_fundamental_score() uwzględnia insider trading statistics:
  insider_net_buying  (ratio > 1.0) → +15 pkt (zarząd kupuje własne akcje)
  insider_net_selling (ratio < 0.2) → -15 pkt (zarząd masowo sprzedaje)
ZMIANY V2.39:
- [NEW] calculate_technical_score() uwzględnia float_category:
  low float (<50M) + wysoki RVOL = silny sygnał momentum → +15 pkt
  micro float (<10M) = ostrzeżenie (powinno być odfiltrowane przez Guard)
ZMIANY V2.37:
- [NEW] calculate_technical_score() rozszerzony o momentum wielookresowe:
  change_1m > 5%  → +15 pkt (trend miesięczny)
  change_3m > 10% → +15 pkt (trend kwartalny)
  change_5d > 2%  → +10 pkt (momentum tygodniowe)
  change_1m < -10% lub change_3m < -20% → -20 pkt (spółka w trendzie spadkowym)
ZMIANY V2.35:
- [NEW] calculate_fundamental_score() uwzględnia Piotroski Score i Altman Z-Score:
  Piotroski >= 7 → +15 pkt (silna spółka), <= 2 → veto (słaba spółka)
  Altman < 1.81  → veto (ryzyko bankructwa), > 2.99 → +10 pkt (strefa bezpieczna)
  Oba są opcjonalne — brak danych (None) = neutralne zachowanie
ZMIANY V2.33:
- [NEW] calculate_event_score() uwzględnia grades analityków:
  recent_upgrade +20 pkt, strong_buy_count bonus, recent_downgrade -25 pkt veto
ZMIANY V2.28:
- [FIX] Ujednolicona skala changesPercentage: silnik oczekuje wartości
  już znormalizowanej przez execution_layer (np. 0.025 = 2.5%), NIE surowych
  procentów (2.5). Próg dla event_score zmieniony z >2.0 na >0.02.
"""

import logging

logger = logging.getLogger(__name__)


class ScoringEngine:
    def __init__(self):
        # Wagi modelu 50/30/20
        self.WEIGHT_TECH = 0.50
        self.WEIGHT_FUND = 0.30
        self.WEIGHT_EVENT = 0.20

    def calculate_technical_score(self, tech_data: dict, hist_df: dict) -> float:
        """
        Ocena techniczna (50%): Momentum, Wolumen, RSI, Trend wielookresowy.

        Momentum wielookresowe (change_1m, change_3m, change_5d):
          Wartości w dziesiętnych: 0.05 = +5%, -0.10 = -10%.
          Brak danych (0.0) = neutralny — bez bonusu i kary.
        """
        score = 0

        # 1. RSI (Idealne okno: 40 - 70)
        rsi = tech_data.get('rsi', 50)
        if 40 <= rsi <= 70:
            score += 30
        elif 70 < rsi < 80:
            score += 10  # Lekkie wykupienie

        # 2. RVOL (Relative Volume)
        rvol = tech_data.get('rvol', 1.0)
        if rvol >= 1.5:
            score += 40
        elif rvol >= 1.2:
            score += 25

        # 3. EMA alignment (Cena powyżej EMA20)
        price = tech_data.get('price', 0)
        ema20 = tech_data.get('ema20', 0)
        if price > ema20 and ema20 > 0:
            score += 30

        # 4. Korekta za "Positive Gap"
        if tech_data.get('positive_gap_penalty', False):
            score -= 20

        # 5. Momentum wielookresowy (dane z /stock-price-change)
        change_1m = tech_data.get('change_1m', 0.0)
        change_3m = tech_data.get('change_3m', 0.0)
        change_5d = tech_data.get('change_5d', 0.0)

        # Trend miesięczny — spółka rośnie od miesiąca
        if change_1m > 0.05:     # > +5%
            score += 15
            logger.debug(f"Tech score: +15 za 1M momentum ({change_1m:.1%})")
        elif change_1m > 0.02:   # > +2%
            score += 7

        # Trend kwartalny — silny trend od kwartału
        if change_3m > 0.10:     # > +10%
            score += 15
            logger.debug(f"Tech score: +15 za 3M momentum ({change_3m:.1%})")
        elif change_3m > 0.05:   # > +5%
            score += 7

        # Momentum tygodniowe
        if change_5d > 0.02:     # > +2% w tygodniu
            score += 10
            logger.debug(f"Tech score: +10 za 5D momentum ({change_5d:.1%})")

        # Kara za trend spadkowy — nie walczymy z rynkiem
        if change_1m < -0.10:    # < -10% w miesiącu
            score -= 20
            logger.info(f"Tech score: -20 za trend spadkowy 1M ({change_1m:.1%})")
        elif change_3m < -0.20:  # < -20% w kwartale
            score -= 20
            logger.info(f"Tech score: -20 za trend spadkowy 3M ({change_3m:.1%})")

        # 6. Float Premium — low float + wysoki RVOL = silniejszy sygnał
        # Logika: im mniej akcji w obrocie, tym łatwiej o duży ruch przy dużym wolumenie.
        # Nagradzamy tylko gdy oba warunki spełnione (float + rvol) — samo low float to nie sygnał.
        float_category = tech_data.get('float_category')
        if float_category in ('low', 'micro') and rvol >= 1.5:
            score += 15
            logger.debug(f"Tech score: +15 za low-float premium ({float_category}, RVOL={rvol:.2f})")
        elif float_category == 'low' and rvol >= 1.2:
            score += 7
            logger.debug(f"Tech score: +7 za low-float ({float_category}, RVOL={rvol:.2f})")

        return max(0, min(100, score))

    def calculate_fundamental_score(self, metrics: dict) -> float:
        """
        Ocena fundamentalna (30%): Jakość, Wzrost, Zdrowie finansowe.

        Veto twarde:
          ROE < 0                → 0 pkt (spółka traci na kapitale)
          Debt/Equity > 2.0      → 0 pkt (nadmierne zadłużenie)
          Piotroski <= 2         → 0 pkt (słaba spółka, 9 kryteriów F-Score)
          Altman Z < 1.81        → 0 pkt (strefa zagrożenia bankructwem)

        Bonusy:
          ROE > 15%              → +20 pkt
          EPS growth > 10%       → +20 pkt
          Debt/Equity < 0.5      → +10 pkt
          Piotroski >= 7         → +15 pkt (spółka w dobrej kondycji)
          Altman Z > 2.99        → +10 pkt (strefa bezpieczna)

        Brak danych (None / same zera) → neutralne 50 pkt.
        """
        roe         = metrics.get('roe', 0.0)
        debt_equity = metrics.get('debt_equity', 0.0)
        eps_growth  = metrics.get('eps_growth', 0.0)
        piotroski   = metrics.get('piotroski_score')   # int 0-9 lub None
        altman      = metrics.get('altman_z_score')    # float lub None

        # Ochrona przed brakiem danych (API zwróciło same zera i None)
        no_basic_data = (roe == 0.0 and debt_equity == 0.0 and eps_growth == 0.0)
        no_scores     = (piotroski is None and altman is None)
        if no_basic_data and no_scores:
            logger.debug("Brak danych fundamentalnych — neutralne 50 pkt.")
            return 50.0

        # ── VETO TWARDE ─────────────────────────────────────────────
        if roe < 0:
            logger.info(f"Fundamental Veto: ROE ujemny ({roe:.3f})")
            return 0.0

        if debt_equity > 2.0:
            logger.info(f"Fundamental Veto: D/E zbyt wysokie ({debt_equity:.2f})")
            return 0.0

        if piotroski is not None and piotroski <= 2:
            logger.info(f"Fundamental Veto: Piotroski={piotroski} (<=2 = słaba spółka)")
            return 0.0

        if altman is not None and altman < 1.81:
            logger.info(f"Fundamental Veto: Altman Z={altman:.2f} (strefa bankructwa)")
            return 0.0

        # ── SCORING ─────────────────────────────────────────────────
        score = 50  # Bazowe punkty za przejście wszystkich veto

        # Podstawowe wskaźniki
        if roe > 0.15:        score += 20
        if eps_growth > 0.10: score += 20
        if debt_equity < 0.5: score += 10

        # Piotroski Score (0-9)
        if piotroski is not None:
            if piotroski >= 7:
                score += 15
                logger.debug(f"Fund score: +15 za Piotroski={piotroski}")
            elif piotroski >= 5:
                score += 5
                logger.debug(f"Fund score: +5 za Piotroski={piotroski}")
            # 3-4 = neutralny, już przeszedł veto powyżej

        # Altman Z-Score
        if altman is not None:
            if altman > 2.99:
                score += 10
                logger.debug(f"Fund score: +10 za Altman Z={altman:.2f} (strefa bezpieczna)")
            elif altman > 1.81:
                score += 3
                logger.debug(f"Fund score: +3 za Altman Z={altman:.2f} (szara strefa)")

        # Insider Trading (sygnał zaufania zarządu do własnej spółki)
        if metrics.get('insider_net_buying', False):
            score += 15
            logger.debug("Fund score: +15 za insider net buying")
        elif metrics.get('insider_net_selling', False):
            score -= 15
            logger.info("Fund score: -15 za insider net selling")

        return float(min(100, max(0, score)))

    def calculate_event_score(self, tech_data: dict, metrics: dict) -> float:
        """
        Ocena zdarzeń (20%): Targety analityków, katalizatory i grades.

        Skala change_pct: znormalizowana (0.025 = 2.5%) przez execution_layer.

        Grades (ostatnie 30 dni):
          recent_upgrade   → +20 pkt (analityk podniósł ocenę na Buy/Outperform)
          strong_buy_count → +5 pkt za każdy Strong Buy (max +15)
          recent_downgrade → -25 pkt (analityk obniżył ocenę na Sell/Underperform)
          analyst_consensus == "Strong Buy" → dodatkowe +10 pkt
        """
        score = 50  # Neutralny start

        # 1. Analyst Upside (price target)
        price  = tech_data.get('price', 1)
        target = metrics.get('analyst_target', 0)
        if target > price and price > 0:
            upside = (target - price) / price
            if upside > 0.20:
                score += 50
            elif upside > 0.10:
                score += 25

        # 2. Price Action Reaction (rynek potwierdza siłę)
        change_pct = tech_data.get('changesPercentage', 0)
        if change_pct > 0.02:
            score += 20

        # 3. Analyst Grades (ostatnie 30 dni)
        if metrics.get('recent_upgrade', False):
            score += 20
            logger.debug("Event score: +20 za recent upgrade")

        strong_buy_bonus = min(metrics.get('strong_buy_count', 0) * 5, 15)
        if strong_buy_bonus:
            score += strong_buy_bonus
            logger.debug(f"Event score: +{strong_buy_bonus} za Strong Buy count")

        if (metrics.get('analyst_consensus', '') or '').lower() == 'strong buy':
            score += 10
            logger.debug("Event score: +10 za consensus Strong Buy")

        # 4. Downgrade Veto — obniżka oceny to poważny sygnał ostrzegawczy
        if metrics.get('recent_downgrade', False):
            score -= 25
            logger.info("Event score: -25 za recent downgrade")

        # 5. Recent 8-K — material event złożony do SEC
        # Im świeższy, tym większy bonus (rynek jeszcze nie w pełni zdyskontował)
        days_since_8k = metrics.get('days_since_8k')
        if metrics.get('has_recent_8k', False) and days_since_8k is not None:
            if days_since_8k <= 3:
                score += 20
                logger.debug(f"Event score: +20 za 8-K sprzed {days_since_8k} dni")
            elif days_since_8k <= 7:
                score += 10
                logger.debug(f"Event score: +10 za 8-K sprzed {days_since_8k} dni")

        return float(max(0, min(100, score)))

    def get_composite_score(self, ticker: str, tech_data: dict, fund_data: dict) -> dict:
        """
        Główna metoda łącząca wszystkie filary w jeden wynik końcowy.
        """
        s_tech = self.calculate_technical_score(tech_data, {})
        s_fund = self.calculate_fundamental_score(fund_data)
        s_event = self.calculate_event_score(tech_data, fund_data)

        final_score = (
            (s_tech  * self.WEIGHT_TECH) +
            (s_fund  * self.WEIGHT_FUND) +
            (s_event * self.WEIGHT_EVENT)
        )

        return {
            "ticker":      ticker,
            "final_score": round(final_score, 2),
            "tech_score":  s_tech,
            "fund_score":  s_fund,
            "event_score": s_event
        }
