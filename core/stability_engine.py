"""
Stability Engine V2.28 - SwingRadar DSS
Silnik wyliczający Momentum i Stabilność trendu w czasie.
Chroni przed sztucznymi wyskokami cen i wczesnym wejściem.

ZMIANY V2.28:
- [FIX] Wymóg pędu (MIN_MOVEMENT) rozszerzony o logikę "wysokiej konsolidacji":
  spółki stabilnie trzymające średnią >= MIN_HIGH_CONSOLIDATION nie są karane
  za brak delty — to sygnał silnej bazy przed wybiciem, nie słabości.
  Poprzednia logika odrzucała idealne konsolidacje np. [75, 76, 75, 76].
"""

import logging
import numpy as np

logger = logging.getLogger(__name__)


class StabilityEngine:
    def __init__(self):
        # Parametry Sędziego
        self.MIN_SNAPSHOTS = 3          # Minimum skanów do oceny
        self.MIN_MEAN_SCORE = 60.0      # Minimalna średnia ocena z historii
        self.MIN_MOVEMENT = 5.0         # Wymóg pędu (delta ostatni - pierwszy skan)
        # FIX: Próg konsolidacji wysokiej jakości.
        # Jeśli średnia >= tego progu, spółka może przejść bez wymagania delty —
        # jest już w silnej strefie i buduje bazę.
        self.MIN_HIGH_CONSOLIDATION = 72.0

    def calculate_stability(self, history_scores: list) -> float:
        """
        Oblicza znormalizowany Stability Score.
        Wejście: Lista ostatnich ocen (np. [60, 62, 68, 75]).
        """
        n = len(history_scores)

        # 1. Twarda bramka ilościowa
        if n < self.MIN_SNAPSHOTS:
            return 0.0

        scores = np.array(history_scores, dtype=float)
        mean_val = float(np.mean(scores))

        # 2. Twarda bramka jakościowa (średnia za niska)
        if mean_val < self.MIN_MEAN_SCORE:
            return 0.0

        total_delta = float(scores[-1] - scores[0])

        # 3. Wymóg pędu — z wyjątkiem wysokiej konsolidacji
        # FIX: Jeśli spółka utrzymuje wysoki poziom (>=72), przepuszczamy mimo
        # braku wyraźnego wzrostu. Taka konsolidacja to sygnał siły, nie stagnacji.
        if n > 1 and total_delta < self.MIN_MOVEMENT:
            if mean_val >= self.MIN_HIGH_CONSOLIDATION:
                logger.debug(
                    f"Stability: Brak pędu (Delta={total_delta:.1f}), "
                    f"ale wysoka konsolidacja (Avg={mean_val:.1f}) — przepuszczam."
                )
                # Nie zwracamy 0 — kontynuujemy kalkulację
            else:
                logger.debug(
                    f"Stability Veto: Brak pędu (Delta={total_delta:.1f}), "
                    f"średnia za niska na konsolidację ({mean_val:.1f} < {self.MIN_HIGH_CONSOLIDATION})."
                )
                return 0.0

        std_dev = float(np.std(scores))

        # 4. Znormalizowana matematyka (uwzględnia nachylenie trendu)
        trend_slope = total_delta / (n - 1) if n > 1 else 0.0

        # Wzór: (Średnia/100) - 0.65*(StdDev/50) + 0.35*(TrendSlope/20)
        stability_raw = (
            (mean_val / 100.0)
            - (0.65 * (std_dev / 50.0))
            + (0.35 * (trend_slope / 20.0))
        )

        stability = stability_raw * 100.0
        return max(0.0, min(100.0, round(stability, 2)))

    def evaluate_signal_state(self, current_score: float, history_scores: list) -> str:
        """
        Określa cykl życia sygnału (State Machine).
        Zwraca: 'NEW' lub 'CANDIDATE'.
        Status 'CONFIRMED' nadaje dopiero Daemon w oknie decyzyjnym.
        """
        n = len(history_scores)

        if n < self.MIN_SNAPSHOTS:
            return "NEW"

        stability = self.calculate_stability(history_scores)

        if stability >= 60.0:
            return "CANDIDATE"

        # Spółka straciła pęd lub średnia spadła — wraca do kwarantanny
        return "NEW"
