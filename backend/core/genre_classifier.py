from __future__ import annotations

from dataclasses import dataclass
import logging
import threading

import numpy as np

logger = logging.getLogger(__name__)


@dataclass
class SchlagerClassificationResult:
    """Ergebnis der Schlager-Klassifikation mit Beitrag jeder Erkennungsschicht."""

    # Required fields — must be provided by all callers (including UV3 §Dach GlobalPlan-Prior)
    is_schlager: bool
    confidence: float
    genre_label: str
    subgenre: str
    bpm: float
    # Optional tier-score fields — default to 0.0 when reconstructed from GlobalPlan context
    clap_score: float = 0.0
    accordion_score: float = 0.0
    harmonic_simplicity: float = 0.0
    rhythm_score: float = 0.0
    vocal_german_prior: float = 0.0
    melodic_repetition: float = 0.0
    key: str = ""
    reasoning: str = ""


#: Backward-compatible alias — UV3 and other callsites import as ``GenreResult``
GenreResult = SchlagerClassificationResult


class GermanSchlagerClassifier:
    """Erkennt Deutschen Schlager zuverlässig ohne vortrainiertes Genre-Modell.

    Erkennungskaskade (6 Schichten):
        Tier-1: LAION-CLAP Zero-Shot (optional, weicher Prior)
        Tier-2: Akkordeon-Reed-Beating-Fingerprint (DSP, physikalisch)
        Tier-3: Harmonischer Simplizitäts-Index (HSI, CQT-Chroma)
        Tier-4: Rhythmus-Muster-Klassifikation (madmom / librosa)
        Tier-5: Deutsch-Vokal-Formant-Prior (LPC-Burg, SAMPA)
        Tier-6: Melodische Wiederholungsrate (MFCC-SSM)
    """

    # ---- CLAP Zero-Shot Prompts ----
    SCHLAGER_CLAP_PROMPTS: list[tuple[str, float]] = [
        ("Deutscher Schlager mit Akkordeon und Melodie", 0.25),
        ("German Schlager music with accordion and folk singing", 0.20),
        ("Volksmusik mit Schlagzeug und Bläsern", 0.15),
        ("German folk pop music with simple chord progression", 0.15),
        ("Schunkelmusik Blaskapelle Volksfest", 0.12),
        ("Oompah music accordion brass band", 0.08),
        ("Marschmusik Deutschland Blasorchester", 0.05),
    ]

    NON_SCHLAGER_NEGATIVE_PROMPTS: list[str] = [
        "jazz improvisation complex harmony",
        "orchestral classical music symphony",
        "electronic dance music synthesizer",
        "hip hop rap rhythm and blues",
        "heavy metal electric guitar distortion",
    ]

    # ---- Schwellwerte ----
    SCHLAGER_CONFIDENCE_THRESHOLD: float = 0.52
    CLAP_POSITIVE_THRESHOLD: float = 0.26
    ACCORDION_AM_FREQ_RANGE: tuple[float, float] = (5.0, 15.0)
    ACCORDION_TREMOLO_RANGE: tuple[float, float] = (4.0, 8.0)
    ACCORDION_FREQ_BAND: tuple[float, float] = (150.0, 2500.0)
    HSI_THRESHOLD: float = 0.82
    REPETITION_THRESHOLD: float = 0.42
    BPM_RANGES: dict[str, tuple[float, float]] = {
        "schunkel": (108.0, 162.0),
        "walzer": (140.0, 200.0),
        "marsch": (96.0, 132.0),
        "discoschlager": (116.0, 134.0),
    }

    # Individuelle Tier-Schwellwerte für Voting
    _TIER_THRESHOLDS: list[float] = [0.50, 0.75, 0.55, 0.50, 0.42]

    def classify(self, audio: np.ndarray, sr: int) -> SchlagerClassificationResult:
        """Klassifiziert Audio als Schlager oder Non-Schlager.

        Args:
            audio: float32/64 nd-array, mono oder stereo
            sr:    Sample-Rate in Hz — muss exakt 48000 sein (Spec §3.x).

        Returns:
            SchlagerClassificationResult mit allen Schicht-Scores.
        """
        # SR-agnostic: analysis modules work at native import SR (Spec §Performance-Budget)
        if not np.isfinite(audio).all():
            audio = np.nan_to_num(audio, nan=0.0, posinf=0.0, neginf=0.0)

        # Mono-Konvertierung + Resampling auf 22050 Hz für Analyse
        mono = self._to_mono(audio)
        mono = self._resample(mono, sr, 22050)
        sr_a = 22050

        # Spektrale Flachheit (Wiener-Entropie) als Rausch-Vorfilter.
        # Weißes Rauschen hat Flatness ≈ 1.0; echte Musik typisch ≤ 0.4.
        # Ist das Signal rauschartig, kann es kein Schlager sein.
        if not self._is_music_like(mono):
            return SchlagerClassificationResult(
                is_schlager=False,
                confidence=0.0,
                genre_label="Unbekannt",
                clap_score=0.0,
                accordion_score=0.0,
                harmonic_simplicity=0.5,
                rhythm_score=0.0,
                vocal_german_prior=0.5,
                melodic_repetition=0.35,
                subgenre="unknown",
                bpm=0.0,
                key="?",
                reasoning="Signal ist rauschähnlich (hohe spektrale Flachheit) — kein Schlager.",
            )

        # Tier-1: CLAP (optional)
        clap_score = self._compute_clap_score(mono, sr_a)

        # Tier-2: Akkordeon
        accordion_score = self._compute_accordion_score(mono, sr_a)

        # Tier-3: Harmonische Simplizität
        hsi = self._compute_harmonic_simplicity(mono, sr_a)

        # Tier-4: Rhythmus
        rhythm_score, subgenre, bpm = self._classify_rhythm_pattern(mono, sr_a)

        # Tier-5: Vokal-Prior
        vocal_prior = self._compute_german_vocal_prior(mono, sr_a)

        # Tier-6: Melodische Wiederholung
        melodic_rep = self._compute_melodic_repetition(mono, sr_a)

        # Ensemble-Voting
        tier_scores = [accordion_score, hsi, rhythm_score, vocal_prior, melodic_rep]
        n_active = sum(1 for s, t in zip(tier_scores, self._TIER_THRESHOLDS) if s >= t)
        weighted_mean = (
            0.20 * accordion_score
            + 0.20 * hsi
            + 0.20 * rhythm_score
            + 0.10 * vocal_prior
            + 0.15 * melodic_rep
            + 0.15 * hsi  # doppeltes Gewicht für HSI (wichtigstes DSP-Merkmal)
        ) / 1.0  # Normalisierung bereits 1.0
        confidence = float(np.clip(0.30 * clap_score + 0.70 * weighted_mean, 0.0, 1.0))

        is_schlager = (n_active >= 3) and (confidence >= self.SCHLAGER_CONFIDENCE_THRESHOLD)

        # Genre-Label + Subgenre
        if is_schlager:
            genre_label = self._determine_genre_label(subgenre, bpm)
        else:
            # Multi-genre fallback: score Rock / Jazz / Klassik
            alt_genre, alt_conf = self._classify_non_schlager_genre(mono, sr_a, hsi, bpm)
            genre_label = alt_genre
            # Use the higher confidence (schlager near-miss vs. alternative genre)
            if alt_conf > confidence:
                confidence = alt_conf

        # Tonart (einfache Schätzung)
        key = self._estimate_key(mono, sr_a)

        reasoning = self._build_reasoning(
            is_schlager,
            confidence,
            clap_score,
            accordion_score,
            hsi,
            rhythm_score,
            vocal_prior,
            melodic_rep,
            n_active,
            subgenre,
        )

        if is_schlager:
            logger.info(
                "🎵 Deutscher Schlager erkannt — Akkordeon-Klangcharakter und "
                "Schunkelrhythmus werden sorgfältig bewahrt. "
                "Konfidenz=%.2f, Subgenre=%s",
                confidence,
                subgenre,
            )

        return SchlagerClassificationResult(
            is_schlager=is_schlager,
            confidence=confidence,
            genre_label=genre_label,
            clap_score=float(np.clip(clap_score, 0.0, 1.0)),
            accordion_score=float(np.clip(accordion_score, 0.0, 1.0)),
            harmonic_simplicity=float(np.clip(hsi, 0.0, 1.0)),
            rhythm_score=float(np.clip(rhythm_score, 0.0, 1.0)),
            vocal_german_prior=float(np.clip(vocal_prior, 0.0, 1.0)),
            melodic_repetition=float(np.clip(melodic_rep, 0.0, 1.0)),
            subgenre=subgenre,
            bpm=float(bpm),
            key=key,
            reasoning=reasoning,
        )

    # ---- Tier-2: Akkordeon-Reed-Beating-Fingerprint ----

    def _is_music_like(self, mono: np.ndarray) -> bool:
        """Prüft via spektrale Flachheit (Wiener-Entropie) ob das Signal musikähnlich ist.

        Weißes Rauschen hat Flatness ≈ 1.0; Musik typisch ≤ 0.40.
        Stille (alle Nullen) wird als nicht-musikähnlich behandelt.

        Returns:
            True  → Signal ist musikähnlich, Klassifikation fortsetzen.
            False → Signal ist rauschähnlich/still, sofort non-Schlager.
        """
        if len(mono) < 32:
            return True  # zu kurz für die Analyse — konservativ fortsetzen
        rms = float(np.sqrt(np.mean(mono**2)))
        if rms < 1e-6:
            return False  # Stille
        try:
            # Spektrale Flachheit = geometrischer / arithmetischer Mittelwert |X(f)|²
            window = np.blackman(min(2048, len(mono)))
            n = len(window)
            segment = mono[:n] * window
            spectrum = np.abs(np.fft.rfft(segment)) ** 2
            spectrum = np.clip(spectrum, 1e-30, None)
            log_mean = float(np.exp(np.mean(np.log(spectrum))))
            arith_mean = float(np.mean(spectrum))
            flatness = float(log_mean / (arith_mean + 1e-30))
            # Flatness > 0.65 → rauschähnlich → kein Schlager möglich
            return flatness <= 0.65
        except Exception:
            return True  # bei Fehler: konservativ fortsetzen

    def _compute_accordion_score(self, mono: np.ndarray, sr: int) -> float:
        """Akkordeon-Reed-Beating via AM-Demodulation.

        Physikalischer Hintergrund: Akkordeon-Reeds sind paarweise leicht verstimmt
        (5–15 Hz Schwebung), sichtbar als Amplitudenmodulation.
        """
        try:
            from scipy.signal import butter, hilbert, sosfilt

            # Bandpass [150, 2500] Hz
            low, high = self.ACCORDION_FREQ_BAND
            nyq = sr / 2.0
            lo_n = float(np.clip(low / nyq, 1e-6, 0.9999))
            hi_n = float(np.clip(high / nyq, 1e-6, 0.9999))
            if lo_n >= hi_n:
                return 0.0
            sos = butter(4, [lo_n, hi_n], btype="band", output="sos")
            filtered = sosfilt(sos, mono)

            # Hüllkurve via Hilbert
            analytic = hilbert(filtered)
            envelope = np.abs(analytic)

            # Subsampling der Hüllkurve auf 100 Hz
            hop = max(1, sr // 100)
            env_sub = envelope[::hop].astype(np.float32)
            env_sub = np.nan_to_num(env_sub)

            if len(env_sub) < 10:
                return 0.0

            # FFT der Hüllkurve
            fft_env = np.abs(np.fft.rfft(env_sub))
            freqs = np.fft.rfftfreq(len(env_sub), d=1.0 / 100)

            total_energy = float(np.sum(fft_env**2)) + 1e-12

            # Reed-Beating [5, 15] Hz
            rb_lo, rb_hi = self.ACCORDION_AM_FREQ_RANGE
            rb_mask = (freqs >= rb_lo) & (freqs <= rb_hi)
            reed_energy = float(np.sum(fft_env[rb_mask] ** 2))

            # Balgzug-Tremolo [4, 8] Hz
            tr_lo, tr_hi = self.ACCORDION_TREMOLO_RANGE
            tr_mask = (freqs >= tr_lo) & (freqs <= tr_hi)
            tremolo_energy = float(np.sum(fft_env[tr_mask] ** 2))

            score = float(np.clip((reed_energy + 0.5 * tremolo_energy) / total_energy * 20.0, 0.0, 1.0))
            return float(np.nan_to_num(score))

        except Exception as e:
            logger.debug("AccordionScore Fallback: %s", e)
            return 0.0

    # ---- Tier-3: Harmonischer Simplizitäts-Index ----

    def _compute_harmonic_simplicity(self, audio: np.ndarray, sr: int) -> float:
        """Harmonischer Simplizitäts-Index (HSI) via CQT-Chroma-Analyse.

        Schlager: HSI ≥ 0.82 (I-IV-V-Dominanz, einfache Harmonik)
        Jazz: HSI ≤ 0.60 (komplexe Harmonik)
        """
        try:
            import librosa

            if len(audio) < sr // 4:
                return 0.5  # neutral bei sehr kurzem Audio

            hop_len = int(sr * 0.5)  # 500-ms-Hop
            hop_len = max(512, hop_len)

            chroma = librosa.feature.chroma_cqt(y=audio, sr=sr, hop_length=hop_len)
            chroma = np.nan_to_num(chroma)

            if chroma.shape[1] < 2:
                return 0.5

            # Chromatische Übergänge
            chroma_idx = np.argmax(chroma, axis=0)  # Dominante Klasse pro Frame
            n_total = len(chroma_idx) - 1
            if n_total < 1:
                return 0.5

            # Quintenkreis-Abstand
            transitions = np.abs(np.diff(chroma_idx.astype(int)))
            # Minimum-Abstand im Kreissinn (Wrapping bei 12)
            transitions = np.minimum(transitions, 12 - transitions)
            n_simple = int(np.sum(transitions <= 2))
            hsi = float(n_simple / n_total)

            return float(np.clip(np.nan_to_num(hsi), 0.0, 1.0))

        except Exception as e:
            logger.debug("HSI Fallback: %s", e)
            return 0.5

    # ---- Tier-4: Rhythmus-Muster-Klassifikation ----

    def _classify_rhythm_pattern(self, audio: np.ndarray, sr: int) -> tuple[float, str, float]:
        """Schunkel/Marsch/Walzer-Klassifikation via Beat-Tracking.

        Returns: (rhythm_score, subgenre_label, bpm)
        """
        try:
            import librosa

            if len(audio) < sr:
                return 0.35, "unknown", 120.0

            tempo, _beats = librosa.beat.beat_track(y=audio, sr=sr)
            bpm = float(tempo)
            if bpm <= 0:
                return 0.35, "unknown", 120.0

            # Half/double-tempo robustness: librosa sometimes estimates
            # double or half the true tempo.  Try original, half, and double
            # candidates and pick the one with the best sub-genre match.
            candidates = [bpm]
            if bpm > 60:
                candidates.append(bpm / 2.0)
            if bpm < 200:
                candidates.append(bpm * 2.0)

            best_score = 0.0
            best_subgenre = "unknown"
            best_bpm = bpm

            for candidate_bpm in candidates:
                for subgenre, (lo, hi) in self.BPM_RANGES.items():
                    if lo <= candidate_bpm <= hi:
                        center = (lo + hi) / 2.0
                        width = (hi - lo) / 2.0
                        dist = abs(candidate_bpm - center) / (width + 1e-8)
                        score = float(np.clip(1.0 - dist * 0.5, 0.5, 1.0))
                        # Penalize half/double tempo slightly (prefer original)
                        if candidate_bpm != bpm:
                            score *= 0.85
                        if score > best_score:
                            best_score = score
                            best_subgenre = subgenre
                            best_bpm = candidate_bpm

            if best_score == 0.0:
                best_score = 0.25
                best_subgenre = "unknown"

            return float(np.nan_to_num(best_score)), best_subgenre, best_bpm

        except Exception as e:
            logger.debug("RhythmPattern Fallback: %s", e)
            return 0.35, "unknown", 120.0

    # ---- Tier-5: Deutsch-Vokal-Formant-Prior ----

    def _compute_german_vocal_prior(self, audio: np.ndarray, sr: int) -> float:
        """Deutsch-Vokal-Formantraum-Overlap (SAMPA-Referenz).

        Nur als Tie-Breaker: max. ±0.08 Einfluss auf Gesamt-Score.
        """
        try:
            pass

            if len(audio) < sr // 2:
                return 0.5  # neutral

            # Vokal-Segmente via Energie-Schwelle + ZCR
            frame_len = int(sr * 0.025)  # 25 ms
            frames = [audio[i : i + frame_len] for i in range(0, len(audio) - frame_len, frame_len)]

            f1_vals, f2_vals = [], []

            for frame in frames[:200]:  # max 200 Frames
                rms = float(np.sqrt(np.mean(frame**2)))
                if rms < 0.01:
                    continue  # Stille

                # Einfaches LPC-Formant-Tracking via Autokorrelations-Methode
                order = 16
                if len(frame) <= order:
                    continue
                try:
                    # Autokorrelations-LPC
                    r = np.correlate(frame, frame, mode="full")
                    r = r[len(r) // 2 :]
                    R = np.array([r[abs(i - j)] for i in range(order) for j in range(order)]).reshape(order, order)
                    rhs = r[1 : order + 1]
                    lpc_coefs = np.linalg.lstsq(R, rhs, rcond=None)[0]

                    # Wurzeln des LPC-Polynoms
                    poly = np.concatenate([[1.0], -lpc_coefs])
                    roots = np.roots(poly)

                    # Nur komplexe Wurzeln mit positivem Imaginärteil
                    formants = []
                    for root in roots:
                        if np.imag(root) > 0:
                            freq = np.angle(root) * sr / (2 * np.pi)
                            if 200 < freq < 3500:
                                formants.append(freq)
                    formants.sort()

                    if len(formants) >= 2:
                        f1_vals.append(formants[0])
                        f2_vals.append(formants[1])
                except Exception:
                    continue

            if len(f1_vals) < 5:
                return 0.5  # zu wenig Daten

            f1_arr = np.array(f1_vals)
            f2_arr = np.array(f2_vals)

            # Deutsche Vokal-Polygone (SAMPA)
            german_regions = [
                # ä: F1 ∈ [600, 900], F2 ∈ [1700, 2200]
                ((600, 900), (1700, 2200)),
                # ö: F1 ∈ [380, 520], F2 ∈ [1300, 1700]
                ((380, 520), (1300, 1700)),
                # ü: F1 ∈ [270, 380], F2 ∈ [1900, 2300]
                ((270, 380), (1900, 2300)),
                # a: F1 ∈ [700, 1100], F2 ∈ [1000, 1600]
                ((700, 1100), (1000, 1600)),
            ]

            n_in = 0
            for (f1lo, f1hi), (f2lo, f2hi) in german_regions:
                mask = (f1_arr >= f1lo) & (f1_arr <= f1hi) & (f2_arr >= f2lo) & (f2_arr <= f2hi)
                n_in += int(np.sum(mask))

            overlap = n_in / len(f1_vals)
            prior = float(np.clip(2.0 * overlap, 0.0, 1.0))
            return float(np.nan_to_num(prior))

        except Exception as e:
            logger.debug("VocalPrior Fallback: %s", e)
            return 0.5

    # ---- Tier-6: Melodische Wiederholungsrate ----

    def _compute_melodic_repetition(self, audio: np.ndarray, sr: int) -> float:
        """Melodische Wiederholungsrate via MFCC-Self-Similarity-Matrix.

        Schlager (Refrain 3-6×): 0.42 – 0.70
        Jazz (Improvisation): 0.10 – 0.25
        """
        try:
            import librosa

            min_duration_s = 30.0
            if len(audio) < sr * min_duration_s:
                return 0.35  # neutral bei kurzen Dateien

            int(sr * 1.0)  # 1-s-Frames
            hop_len = int(sr * 0.5)  # 0.5-s-Hop
            n_mfcc = 20
            min_gap_frames = 16  # ≥ 8 s bei 0.5s-Hop

            mfcc = librosa.feature.mfcc(y=audio, sr=sr, n_mfcc=n_mfcc, hop_length=hop_len)
            mfcc = np.nan_to_num(mfcc)

            T = mfcc.shape[1]
            if min_gap_frames * 2 > T:
                return 0.35

            # SSM (Kosinus-Ähnlichkeit)
            norms = np.linalg.norm(mfcc, axis=0, keepdims=True) + 1e-8
            mfcc_n = mfcc / norms  # [n_mfcc, T]

            # Nur Stichprobe für Performance
            max_frames = min(T, 200)
            idx = np.linspace(0, T - 1, max_frames, dtype=int)
            mfcc_s = mfcc_n[:, idx].T  # [max_frames, n_mfcc]

            # Kosinus-SSM
            ssm = mfcc_s @ mfcc_s.T  # [max_frames, max_frames]

            # Ähnliche Paare mit Mindestabstand
            n_total = 0
            n_similar = 0
            for i in range(max_frames):
                for j in range(i + min_gap_frames, max_frames):
                    n_total += 1
                    if ssm[i, j] >= 0.85:
                        n_similar += 1

            if n_total == 0:
                return 0.35

            score = float(n_similar / n_total)
            score = float(np.clip(score * 2.0, 0.0, 1.0))
            return float(np.nan_to_num(score))

        except Exception as e:
            logger.debug("MelodicRepetition Fallback: %s", e)
            return 0.35

    # ---- Multi-Genre Scoring (Rock / Jazz / Klassik / Oper) ----

    @staticmethod
    def _spectral_centroid_hz(mono: np.ndarray, sr: int) -> float:
        """Weighted mean frequency of the power spectrum (brightness indicator)."""
        n_fft = min(4096, len(mono))
        if n_fft < 256:
            return 2000.0
        hop = n_fft // 2
        centroids: list[float] = []
        for start in range(0, max(1, len(mono) - n_fft), hop):
            frame = mono[start : start + n_fft] * np.hanning(n_fft)
            mag = np.abs(np.fft.rfft(frame))
            freqs = np.fft.rfftfreq(n_fft, 1.0 / sr)
            total = float(np.sum(mag)) + 1e-12
            c = float(np.sum(freqs * mag) / total)
            centroids.append(c)
            if len(centroids) >= 200:
                break
        return float(np.median(centroids)) if centroids else 2000.0

    @staticmethod
    def _onset_rate(mono: np.ndarray, sr: int) -> float:
        """Transient onset density (onsets per second)."""
        try:
            import librosa

            if len(mono) < sr:
                return 2.0
            onsets = librosa.onset.onset_detect(y=mono, sr=sr, units="time")
            duration_s = len(mono) / sr
            return float(len(onsets) / max(duration_s, 1.0))
        except Exception:
            return 2.0

    @staticmethod
    def _dynamic_range_db(mono: np.ndarray, sr: int) -> float:
        """Frame-energy P95-P5 spread in dB."""
        import math as _math

        frame_size = max(1, sr // 10)
        n_frames = len(mono) // frame_size
        if n_frames < 5:
            return 25.0
        energies = np.array([np.mean(mono[i * frame_size : (i + 1) * frame_size] ** 2) for i in range(n_frames)])
        energies = energies[energies > 1e-6]
        if len(energies) < 5:
            return 25.0
        p95 = float(np.percentile(energies, 95))
        p5 = float(np.percentile(energies, 5))
        if p5 < 1e-18:
            return 40.0
        return float(np.clip(10.0 * _math.log10(max(p95 / p5, 1.0)), 5.0, 70.0))

    def _score_rock(
        self,
        centroid_hz: float,
        onset_rate: float,
        hsi: float,
        bpm: float,
    ) -> float:
        """Rock genre score: bright spectrum + dense transients + moderate harmony."""
        score = 0.0
        # High spectral centroid → bright/aggressive sound
        if centroid_hz > 2800:
            score += 0.30
        elif centroid_hz > 2200:
            score += 0.15
        # High onset density (drum attacks, power chords)
        if onset_rate > 3.5:
            score += 0.25
        elif onset_rate > 2.5:
            score += 0.12
        # Moderate harmonic complexity (not simple Schlager, not complex Jazz)
        if 0.40 <= hsi <= 0.72:
            score += 0.20
        # Typical Rock BPM range (90–170)
        if 90 <= bpm <= 170:
            score += 0.15
        return float(np.clip(score, 0.0, 1.0))

    def _score_jazz(
        self,
        centroid_hz: float,
        hsi: float,
        dr_db: float,
        bpm: float,
    ) -> float:
        """Jazz genre score: complex harmony + wide dynamics + moderate tempo."""
        score = 0.0
        # Low HSI = complex harmony (quintessential Jazz feature)
        if hsi < 0.50:
            score += 0.40
        elif hsi < 0.65:
            score += 0.20
        # Wide dynamic range (expressive playing)
        if dr_db > 35:
            score += 0.20
        elif dr_db > 25:
            score += 0.08
        # Moderate spectral centroid (warm, not aggressive)
        if 1400 < centroid_hz < 3200:
            score += 0.15
        # Jazz BPM range is extremely variable; moderate tempos common
        if 80 <= bpm <= 200:
            score += 0.10
        return float(np.clip(score, 0.0, 1.0))

    def _score_classical(
        self,
        centroid_hz: float,
        onset_rate: float,
        hsi: float,
        dr_db: float,
    ) -> float:
        """Classical genre score: extreme dynamics + low onset density + diatonic."""
        score = 0.0
        # Very high dynamic range (orchestral pianissimo → fortissimo)
        if dr_db > 42:
            score += 0.35
        elif dr_db > 32:
            score += 0.15
        # Low onset density (no percussion-heavy rhythm)
        if onset_rate < 1.5:
            score += 0.25
        elif onset_rate < 2.5:
            score += 0.10
        # Diatonic but not trivially simple harmony
        if 0.55 <= hsi <= 0.88:
            score += 0.15
        # Lower spectral centroid (rich mids, warm strings)
        if centroid_hz < 2200:
            score += 0.15
        return float(np.clip(score, 0.0, 1.0))

    def _classify_non_schlager_genre(
        self,
        mono: np.ndarray,
        sr: int,
        hsi: float,
        bpm: float,
    ) -> tuple[str, float]:
        """Multi-genre scoring for non-Schlager tracks.

        Computes Rock/Jazz/Classical scores and returns the best match
        if it exceeds a minimum confidence threshold.

        Returns:
            (genre_label, confidence): e.g. ("Rock", 0.65) or ("Unbekannt", 0.0)
        """
        centroid = self._spectral_centroid_hz(mono, sr)
        onset = self._onset_rate(mono, sr)
        dr_db = self._dynamic_range_db(mono, sr)

        rock_s = self._score_rock(centroid, onset, hsi, bpm)
        jazz_s = self._score_jazz(centroid, hsi, dr_db, bpm)
        classical_s = self._score_classical(centroid, onset, hsi, dr_db)

        scores = {"Rock": rock_s, "Jazz": jazz_s, "Klassik": classical_s}
        best_genre = max(scores, key=scores.get)  # type: ignore[arg-type]
        best_score = scores[best_genre]

        logger.debug(
            "Multi-Genre-Scores: Rock=%.2f Jazz=%.2f Klassik=%.2f centroid=%.0fHz onsets=%.1f/s DR=%.1fdB → %s (%.2f)",
            rock_s,
            jazz_s,
            classical_s,
            centroid,
            onset,
            dr_db,
            best_genre,
            best_score,
        )

        # Minimum threshold to assign a non-Schlager genre
        if best_score >= 0.45:
            return best_genre, best_score
        return "Unbekannt", 0.0

    # ---- Tier-1: CLAP (optional) ----

    def _compute_clap_score(self, audio: np.ndarray, sr: int) -> float:
        """LAION-CLAP Zero-Shot (optionaler weicher Prior).

        Setzt AURIK_ENABLE_CLAP=1 (Env-Variable) voraus, um den schweren
        `transformers`-Import zu erlauben. Ohne diese Variable wird sofort
        der neutrale Prior 0.35 zurückgegeben (verhindert 30 s Timeout in Tests).
        """
        import os

        if not os.environ.get("AURIK_ENABLE_CLAP"):
            return 0.35  # neutraler Prior ohne CLAP-Import
        try:
            # Versuche CLAP zu laden
            from plugins.laion_clap_plugin import get_laion_clap as get_clap_plugin

            clap = get_clap_plugin()
            if clap is None:
                return 0.35  # neutral wenn nicht verfügbar

            # Schlager-Ähnlichkeit via Genre-Tags schätzen
            # tag() mit Schlager-assoziierten text_queries aufrufen
            schlager_prompts = [p for p, _ in self.SCHLAGER_CLAP_PROMPTS[:3]]
            try:
                tag_result = clap.tag(audio, sr, text_queries=schlager_prompts)
                # Genre-Tags: "schlager", "volksmusik", "folk" als Proxy-Scores
                genre_scores_dict = tag_result.genre_tags
                proxy_keys = ["schlager", "volksmusik", "folk", "german", "pop"]
                proxy_score = 0.0
                for key in proxy_keys:
                    if key in genre_scores_dict:
                        proxy_score = max(proxy_score, genre_scores_dict[key])
                clap_score = float(np.clip(proxy_score, 0.0, 1.0))
            except Exception:
                clap_score = 0.35

            pos_scores = [clap_score]
            pos_total = float(np.mean(pos_scores)) if pos_scores else 0.35

            neg_scores: list[float] = []
            try:
                neg_tag = clap.tag(audio, sr, text_queries=self.NON_SCHLAGER_NEGATIVE_PROMPTS[:3])
                _neg_dict = neg_tag.genre_tags if hasattr(neg_tag, "genre_tags") else {}
                for v in _neg_dict.values():
                    neg_scores.append(float(v))
            except Exception:
                neg_scores = []
            neg_mean = (
                float(np.mean(neg_scores)) if neg_scores else 0.0
            )  # Negativ-Prior via NON_SCHLAGER_NEGATIVE_PROMPTS
            clap_score = float(np.clip(pos_total - 0.5 * neg_mean, 0.0, 1.0))
            return float(np.nan_to_num(clap_score))

        except (ImportError, Exception) as e:
            logger.debug("CLAP nicht verfügbar, neutraler Prior: %s", e)
            return 0.35  # neutral

    # ---- Hilfsfunktionen ----

    def _to_mono(self, audio: np.ndarray) -> np.ndarray:
        """Konvertiert Stereo → Mono."""
        if audio.ndim == 2:
            return np.asarray(audio.mean(axis=0), dtype=np.float32)
        return np.asarray(audio, dtype=np.float32)

    def _resample(self, audio: np.ndarray, sr_in: int, sr_out: int) -> np.ndarray:
        """Resampelt auf Ziel-Sample-Rate."""
        if sr_in == sr_out:
            return audio
        try:
            import librosa

            return np.asarray(librosa.resample(audio, orig_sr=sr_in, target_sr=sr_out), dtype=np.float32)
        except Exception:
            return audio

    def _estimate_key(self, audio: np.ndarray, sr: int) -> str:
        """Einfache Tonart-Schätzung via Chroma."""
        try:
            import librosa

            chroma = librosa.feature.chroma_cqt(y=audio, sr=sr)
            chroma_mean = np.nan_to_num(chroma.mean(axis=1))
            key_idx = int(np.argmax(chroma_mean))
            key_names = ["C", "C#", "D", "Eb", "E", "F", "F#", "G", "Ab", "A", "Bb", "H"]
            return f"{key_names[key_idx]}-Dur"
        except Exception:
            return "Unbekannt"

    def _determine_genre_label(self, subgenre: str, bpm: float) -> str:
        """Bestimmt das Genre-Label aus Subgenre und BPM."""
        mapping = {
            "schunkel": "Schlager",
            "walzer": "Walzer",
            "marsch": "Marsch",
            "discoschlager": "Disco-Schlager",
            "unknown": "Schlager",
        }
        return mapping.get(subgenre, "Schlager")

    def _build_reasoning(
        self,
        is_schlager: bool,
        confidence: float,
        clap: float,
        accordion: float,
        hsi: float,
        rhythm: float,
        vocal: float,
        melodic: float,
        n_active: int,
        subgenre: str,
    ) -> str:
        parts = []
        if accordion >= 0.50:
            parts.append(f"Akkordeon-Charakteristik erkannt ({accordion:.2f})")
        if hsi >= self.HSI_THRESHOLD:
            parts.append(f"Harmonische Simplizität hoch ({hsi:.2f})")
        if rhythm >= 0.55:
            parts.append(f"Schlager-Rhythmus '{subgenre}' erkannt ({rhythm:.2f})")
        if melodic >= self.REPETITION_THRESHOLD:
            parts.append(f"Hohe melodische Wiederholungsrate ({melodic:.2f})")
        verdict = "Schlager erkannt" if is_schlager else "Kein Schlager"
        return f"{verdict} (Konfidenz={confidence:.2f}, {n_active}/5 DSP-Schichten aktiv). " + "; ".join(parts)


# ---------------------------------------------------------------------------
# SCHLAGER_RESTORATION_PROFILE — Pipeline-Anpassungen bei Schlager-Erkennung (§2.19.3)
# ---------------------------------------------------------------------------

SCHLAGER_RESTORATION_PROFILE: dict = {
    # Akkordeon-Sättigung BEWAHREN (→ DefectType.SOFT_SATURATION-Schutz)
    "soft_saturation_preserve": True,
    "clipping_repair_threshold_db": -3.5,  # Konservativer als Standard (−2.0)
    # TonalCenterMetric verschärft (kein Tonart-Shift bei Schlager)
    "tonal_center_threshold": 0.97,  # Statt Standard 0.95
    # Harmonischer Exciter deaktiviert (Schlager-Timbres sind original genug)
    "phase_21_exciter_enabled": False,
    # Groove-Erhalt kritisch (Schunkelrhythmus darf nicht begradigt werden)
    "groove_dtw_max_ms": 5.0,  # Strenger als Standard 8.0 ms
    # De-Esser an typischen Schlager-Gesang angepasst
    "deessing_target_hz": 6500,
    "deessing_strength_cap": 0.45,  # Max. 45 % (Standard: 80 %)
    # Brillanz-Ziel leicht gesenkt (Schlager klingt warm, nicht "modern crisp")
    "brillanz_target": 0.82,  # Statt Standard 0.85
    # Wärme-Ziel angehoben (charakteristisch für das Genre)
    "waerme_target": 0.88,  # Statt Standard 0.80
    # Stereo-Breite: historischer Schlager oft Mono/Narrow-Stereo
    "stereo_width_max_era_aware": True,
    # GP-Optimizer Warmstart aus Schlager-spezifischem Gedächtnis
    "gp_memory_key": "schlager",  # ~/.aurik/gp_memory/schlager.json
}

# Subgenre-Erweiterungen (werden über das Basis-Profil gelegt)
_SUBGENRE_EXTENSIONS: dict = {
    "schlager_1950s": {"audiosr_disabled": True, "max_bandwidth_hz": 12000},
    "schlager_modern": {"audiosr_disabled": True},
    "volksmusik": {"phase_45_priority": "high"},
    "marsch": {"transient_preservation_strength": 1.0, "snare_attack_max_ms": 1.0},
    "walzer": {"groove_meter": "3/4"},
    "discoschlager": {"bass_kraft_target": 0.90, "kick_preserve": True},
}


# ── Genre-Restaurierungsprofile (Spec §2.20) ────────────────────────────────
JAZZ_RESTORATION_PROFILE: dict = {
    "groove_dtw_max_ms": 4.0,
    "tonal_center_threshold": 0.92,
    "harmonic_exciter_enabled": False,
    "dereverb_strength_cap": 0.30,
    "deessing_strength_cap": 0.50,
    "compression_ratio_cap": 1.8,
    "gp_memory_key": "jazz",
}

KLASSIK_RESTORATION_PROFILE: dict = {
    "phase_20_dereverb_enabled": False,
    "phase_49_dereverb_enabled": False,
    "transient_preservation_strength": 1.0,
    "compression_ratio_cap": 1.3,
    "brillanz_target": 0.88,
    "waerme_target": 0.82,
    "spatial_depth_threshold": 0.82,
    "groove_dtw_max_ms": 10.0,
    "gp_memory_key": "orchestral",
}

OPER_RESTORATION_PROFILE: dict = {
    "deessing_target_hz": 7000,
    "deessing_strength_cap": 0.35,
    "formant_pearson_threshold": 0.97,
    "phase_20_dereverb_enabled": False,
    "vibrato_rate_tolerance_hz": 0.20,
    "de_esser_voice_adaptive": True,
    "gp_memory_key": "opera",
}

ROCK_RESTORATION_PROFILE: dict = {
    "transient_preservation_strength": 1.0,
    "brillanz_target": 0.90,
    "soft_saturation_preserve": True,
    "clipping_repair_threshold_db": -2.0,
    "groove_dtw_max_ms": 6.0,
    "compression_ratio_cap": 2.5,
    "gp_memory_key": "rock",
}

# Alle Profile in einem Dict — für Tests und Iteration
# Keys: Kleinschreibung (intern) UND Großschreibung (Test-Kompatibilität / genre_label)
GENRE_RESTORATION_PROFILES: dict[str, dict] = {
    "schlager": SCHLAGER_RESTORATION_PROFILE,
    "jazz": JAZZ_RESTORATION_PROFILE,
    "klassik": KLASSIK_RESTORATION_PROFILE,
    "oper": OPER_RESTORATION_PROFILE,
    "rock": ROCK_RESTORATION_PROFILE,
    # Kapitalisierte Aliases (GermanSchlagerClassifier.genre_label-Format)
    "Schlager": SCHLAGER_RESTORATION_PROFILE,
    "Jazz": JAZZ_RESTORATION_PROFILE,
    "Klassik": KLASSIK_RESTORATION_PROFILE,
    "Oper": OPER_RESTORATION_PROFILE,
    "Rock": ROCK_RESTORATION_PROFILE,
}


def get_restoration_profile(subgenre: str = "unknown") -> dict:
    """Gibt das Restaurierungsprofil für ein Genre/Subgenre zurück.

    Unterstützte Genre-Label (exakt wie GermanSchlagerClassifier.genre_label):
        'Schlager', 'Walzer', 'Marsch', 'Disco-Schlager', 'Jazz', 'Klassik',
        'Oper', 'Rock', 'Volksmusik'
    Unterstützte Subgenre-Keys (SCHLAGER_SUBGENRE_EXTENSIONS):
        'schunkel', 'walzer', 'marsch', 'discoschlager', 'schlager_1950s',
        'schlager_modern', 'volksmusik'

    Args:
        subgenre: Genre-Label oder Subgenre-Key (Groß-/Kleinschreibung egal).

    Returns:
        Profil-Dict; leeres Dict wenn unbekannt.
    """
    key = subgenre.strip().lower()
    # Genre-Label → kanonisches Profil
    label_map: dict[str, dict] = {
        "schlager": SCHLAGER_RESTORATION_PROFILE,
        "walzer": {**SCHLAGER_RESTORATION_PROFILE, **_SUBGENRE_EXTENSIONS.get("walzer", {})},
        "marsch": {**SCHLAGER_RESTORATION_PROFILE, **_SUBGENRE_EXTENSIONS.get("marsch", {})},
        "disco-schlager": {**SCHLAGER_RESTORATION_PROFILE, **_SUBGENRE_EXTENSIONS.get("discoschlager", {})},
        "discoschlager": {**SCHLAGER_RESTORATION_PROFILE, **_SUBGENRE_EXTENSIONS.get("discoschlager", {})},
        "volksmusik": {**SCHLAGER_RESTORATION_PROFILE, **_SUBGENRE_EXTENSIONS.get("volksmusik", {})},
        "schlager_1950s": {**SCHLAGER_RESTORATION_PROFILE, **_SUBGENRE_EXTENSIONS.get("schlager_1950s", {})},
        "schlager_modern": {**SCHLAGER_RESTORATION_PROFILE, **_SUBGENRE_EXTENSIONS.get("schlager_modern", {})},
        "jazz": JAZZ_RESTORATION_PROFILE,
        "klassik": KLASSIK_RESTORATION_PROFILE,
        "oper": OPER_RESTORATION_PROFILE,
        "rock": ROCK_RESTORATION_PROFILE,
    }
    return dict(label_map.get(key, {}))  # leere Kopie wenn unbekannt


# ---- Thread-sicherer Singleton (Double-Checked Locking, §3.2) ----
_instance: GermanSchlagerClassifier | None = None
_lock = threading.Lock()


def get_genre_classifier() -> GermanSchlagerClassifier:
    """Thread-sicherer Singleton-Accessor (Double-Checked Locking)."""
    global _instance
    if _instance is None:
        with _lock:
            if _instance is None:
                _instance = GermanSchlagerClassifier()
    return _instance


def classify_genre(audio: np.ndarray, sr: int) -> SchlagerClassificationResult:
    """Convenience-Wrapper für Genre-Klassifikation."""
    return get_genre_classifier().classify(audio, sr)
