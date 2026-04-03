from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field

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
    vocal_language_score: float = 0.5  # 1.0 = klar Deutsch, 0.0 = klar Englisch
    dsp_language_score: float = 0.5
    lyrics_language_hint: float = 0.0
    genre_family: str = "unknown"
    genre_family_confidence: float = 0.0
    top_genres: list[tuple[str, float]] = field(default_factory=list)
    open_set_unknown: bool = False
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
        "English pop singing british accent",
        "American country music english vocals",
        "English language pop ballad singing",
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
    _NON_SCHLAGER_MIN_SCORE: float = 0.35
    _OPEN_SET_MIN_SCORE: float = 0.38
    _OPEN_SET_MARGIN: float = 0.08

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

        # Tier-7: Vokalsprach-Erkennung (Deutsch vs. Englisch)
        lang_de_score = self._detect_vocal_language(mono, sr_a)
        dsp_lang_score = float(lang_de_score)
        lyrics_lang_hint = self._compute_lyrics_language_hint(audio, sr)
        if lyrics_lang_hint > 0.0:
            # Fuse DSP language cue with §2.36 lyrics-guided cue.
            lang_de_score = float(np.clip(max(lang_de_score, lyrics_lang_hint), 0.0, 1.0))

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

        # Sprach-Penalty: klar englischer Gesang (lang_de_score < 0.30) → confidence −15 %
        if lang_de_score < 0.30:
            confidence = float(np.clip(confidence * 0.85, 0.0, 1.0))

        is_schlager = (n_active >= 3) and (confidence >= self.SCHLAGER_CONFIDENCE_THRESHOLD)
        if not is_schlager and self._is_schlager_near_miss(
            n_active=n_active,
            confidence=confidence,
            hsi=hsi,
            rhythm_score=rhythm_score,
            vocal_prior=vocal_prior,
            melodic_rep=melodic_rep,
            lang_de_score=lang_de_score,
        ):
            # Prevent non-Schlager fallback mislabels (e.g. "Jazz") for German
            # Schlager tracks that narrowly miss the strict threshold gate.
            is_schlager = True
            confidence = float(max(confidence, self.SCHLAGER_CONFIDENCE_THRESHOLD))

        centroid = self._spectral_centroid_hz(mono, sr_a)
        onset = self._onset_rate(mono, sr_a)
        dr_db = self._dynamic_range_db(mono, sr_a)
        non_schlager_scores = self._compute_non_schlager_scores(centroid, onset, hsi, dr_db, bpm)
        alt_genre, alt_conf = self._pick_non_schlager_genre(non_schlager_scores)

        # Genre-Label + Subgenre
        if is_schlager:
            genre_label = self._determine_genre_label(subgenre, bpm, lang_de_score)
        else:
            genre_label = alt_genre
            # Use the higher confidence (schlager near-miss vs. alternative genre)
            if alt_conf > confidence:
                confidence = alt_conf

        schlager_family_score = float(
            np.clip(
                0.30 * rhythm_score + 0.30 * hsi + 0.25 * vocal_prior + 0.15 * lang_de_score,
                0.0,
                1.0,
            )
        )
        family_label, family_confidence = self._infer_genre_family(non_schlager_scores, schlager_family_score)

        top_genres = self._build_top_genres(
            is_schlager=is_schlager,
            primary_label=genre_label,
            primary_confidence=confidence,
            non_schlager_scores=non_schlager_scores,
        )
        open_set_unknown = self._is_open_set_unknown(top_genres)
        if not is_schlager and open_set_unknown:
            genre_label = "Unbekannt"
            confidence = 0.0

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
            lang_de_score,
        )

        if is_schlager:
            logger.info(
                "🎵 %s erkannt — Akkordeon-Klangcharakter und "
                "Schunkelrhythmus werden sorgfältig bewahrt. "
                "Konfidenz=%.2f, Subgenre=%s, Sprache=%.2f",
                genre_label,
                confidence,
                subgenre,
                lang_de_score,
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
            vocal_language_score=float(np.clip(lang_de_score, 0.0, 1.0)),
            dsp_language_score=float(np.clip(dsp_lang_score, 0.0, 1.0)),
            lyrics_language_hint=float(np.clip(lyrics_lang_hint, 0.0, 1.0)),
            genre_family=family_label,
            genre_family_confidence=float(np.clip(family_confidence, 0.0, 1.0)),
            top_genres=top_genres,
            open_set_unknown=open_set_unknown,
            subgenre=subgenre,
            bpm=float(bpm),
            key=key,
            reasoning=reasoning,
        )

    def _compute_lyrics_language_hint(self, audio: np.ndarray, sr: int) -> float:
        """Derive a German-language hint from §2.36 lyrics-guided transcription.

        This is only used as an additive cue for borderline genre decisions.
        It must never log or persist lyric text.
        """
        if sr != 48_000:
            return 0.0
        if audio.size < sr * 8:
            return 0.0

        try:
            from backend.core.lyrics_guided_enhancement import get_lyrics_guided_enhancement

            lge = get_lyrics_guided_enhancement()
            transcription = lge.transcribe(audio, sr)
        except Exception as exc:
            logger.debug("Lyrics hint unavailable for genre classification: %s", exc)
            return 0.0

        words = getattr(transcription, "words", []) or []
        lang = str(getattr(transcription, "language", "") or "").lower()
        if not words:
            return 0.0

        # Start from neutral and then lift for confident German language cues.
        score = 0.5
        if lang.startswith("de"):
            score += 0.20
        elif lang.startswith("en"):
            score -= 0.12

        # German diction often carries clear fricative/plosive articulation.
        n_words = max(1, len(words))
        fric_plosive = 0
        stressed = 0
        conf_sum = 0.0
        for w in words:
            ptype = str(getattr(w, "phoneme_type", "") or "")
            if "fricative" in ptype or ptype == "plosive":
                fric_plosive += 1
            if "stressed" in ptype:
                stressed += 1
            conf_sum += float(getattr(w, "confidence", 0.0) or 0.0)

        fp_ratio = fric_plosive / n_words
        stress_ratio = stressed / n_words
        avg_conf = conf_sum / n_words
        score += 0.10 * min(1.0, fp_ratio / 0.30)
        score += 0.08 * min(1.0, stress_ratio / 0.40)
        score += 0.08 * min(1.0, avg_conf / 0.60)

        return float(np.clip(score, 0.0, 1.0))

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
            analytic: np.ndarray = hilbert(np.asarray(filtered, dtype=np.float64))  # type: ignore[assignment]
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
            bpm = float(np.asarray(tempo).flat[0])
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
                if not np.isfinite(rms) or rms < 0.01:
                    continue  # Stille

                # Einfaches LPC-Formant-Tracking via Autokorrelations-Methode
                order = 16
                if len(frame) <= order:
                    continue
                try:
                    # Autokorrelations-LPC
                    r = np.correlate(frame, frame, mode="full")
                    r = r[len(r) // 2 :]
                    if not np.isfinite(r).all() or r[0] < 1e-12:
                        continue
                    R = np.array([r[abs(i - j)] for i in range(order) for j in range(order)]).reshape(order, order)
                    rhs = r[1 : order + 1]
                    lpc_coefs = np.linalg.lstsq(R, rhs, rcond=None)[0]
                    if not np.isfinite(lpc_coefs).all():
                        continue

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

    # ---- Tier-7: Vokalsprach-Erkennung (Deutsch vs. Englisch) ----

    def _detect_vocal_language(self, audio: np.ndarray, sr: int) -> float:
        """Erkennt ob Vokalinhalt eher Deutsch (1.0) oder Englisch (0.0) ist.

        Drei DSP-Merkmale (gewichtetes Mittel):

        1. Umlaut-F2-F1-Gap (Gewicht 0.50):
           Deutsch ü/ö haben F2-F1 > 1400 Hz bei gleichzeitig F1 < 550 Hz.
           Kein englisches Vokal-Phonem besetzt diesen Bereich systematisch.
           Hoher Anteil solcher Frames → klar Deutsch.

        2. F2-Varianz-Bimodalität (Gewicht 0.30):
           Deutsch kontrastiert stark zwischen front-gerundeten Vokalen (ü, ö → hohe F2)
           und Rückenvokalen (u, o → niedrige F2). Englisch hat weniger front-gerundete
           Vokale → niedrigere F2-Standardabweichung relativ zum Mittelwert.
           Normierte F2-Std (σ/µ) > 0.35 → eher Deutsch.

        3. Konsonant-Cluster-Fricative-Band (Gewicht 0.20):
           Deutsch /ch/ (Ich-Laut ~2.5 kHz, Ach-Laut ~1.5 kHz) erzeugt charakteristische
           Energie im 1.2–3.5 kHz Band während stimmloser Passagen. Englisch fehlt dieses
           Paar weitgehend (/ʃ/ konzentriert sich in 3–8 kHz).
           Ratio E(1.2–3.5kHz) / E(3.5–8kHz) in stillen Segmenten > 1.2 → eher Deutsch.

        Args:
            audio: Mono float32, bereits auf 22050 Hz umgetastet.
            sr:    22050.

        Returns:
            lang_de_score ∈ [0.0, 1.0] — 1.0 = klar Deutsch, 0.0 = klar Englisch.
            0.5 = neutral / kein Gesang erkennbar.
        """
        try:
            if len(audio) < sr // 2:
                return 0.5

            frame_len = int(sr * 0.025)  # 25 ms
            hop = frame_len
            frames = [audio[i : i + frame_len] for i in range(0, len(audio) - frame_len, hop)]

            f1_vals: list[float] = []
            f2_vals: list[float] = []
            order = 16

            for frame in frames[:300]:
                rms = float(np.sqrt(np.mean(frame**2)))
                if not np.isfinite(rms) or rms < 0.01:
                    continue
                if len(frame) <= order:
                    continue
                try:
                    r = np.correlate(frame, frame, mode="full")
                    r = r[len(r) // 2 :]
                    if not np.isfinite(r).all() or r[0] < 1e-12:
                        continue
                    R = np.array([r[abs(i - j)] for i in range(order) for j in range(order)]).reshape(order, order)
                    rhs = r[1 : order + 1]
                    lpc_coefs = np.linalg.lstsq(R, rhs, rcond=None)[0]
                    if not np.isfinite(lpc_coefs).all():
                        continue
                    poly = np.concatenate([[1.0], -lpc_coefs])
                    roots = np.roots(poly)
                    formants: list[float] = []
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

            # --- Merkmal 1: Umlaut-Score (F2-F1 > 1400, F1 < 550) ---
            umlaut_score = 0.5
            if len(f1_vals) >= 5:
                f1_arr = np.array(f1_vals)
                f2_arr = np.array(f2_vals)
                umlaut_mask = (f2_arr - f1_arr > 1400.0) & (f1_arr < 550.0)
                umlaut_frac = float(np.sum(umlaut_mask)) / len(f1_vals)
                # 0 Frames → 0.15 (neutral-negativ); > 20 % Frames → 1.0
                umlaut_score = float(np.clip(0.15 + umlaut_frac * 4.25, 0.0, 1.0))

            # --- Merkmal 2: F2-Bimodalität (normierte F2-Standardabweichung) ---
            f2_bimodal_score = 0.5
            if len(f2_vals) >= 10:
                f2_arr = np.array(f2_vals)
                f2_mean = float(np.mean(f2_arr))
                if f2_mean > 100.0:
                    f2_cv = float(np.std(f2_arr)) / f2_mean  # Variationskoeffizient
                    # Deutsch: σ/µ typisch 0.35–0.60; Englisch: 0.20–0.35
                    f2_bimodal_score = float(np.clip((f2_cv - 0.20) / 0.25, 0.0, 1.0))

            # --- Merkmal 3: Konsonant-Cluster /ch/-Band-Ratio ---
            ch_score = 0.5
            try:
                spec = np.abs(np.fft.rfft(audio, n=min(len(audio), 4096 * 8)))
                freqs = np.fft.rfftfreq(min(len(audio), 4096 * 8), d=1.0 / sr)
                ch_band = (freqs >= 1200.0) & (freqs <= 3500.0)
                hf_band = (freqs > 3500.0) & (freqs <= 8000.0)
                e_ch = float(np.mean(spec[ch_band] ** 2)) if np.any(ch_band) else 1e-12
                e_hf = float(np.mean(spec[hf_band] ** 2)) if np.any(hf_band) else 1e-12
                ratio = e_ch / (e_hf + 1e-12)
                # Ratio > 1.2 → eher Deutsch; < 0.8 → eher Englisch
                ch_score = float(np.clip((ratio - 0.8) / 0.8, 0.0, 1.0))
            except Exception as _exc:
                logger.debug("Operation failed (non-critical): %s", _exc)

            lang_de_score = float(
                np.clip(
                    0.50 * umlaut_score + 0.30 * f2_bimodal_score + 0.20 * ch_score,
                    0.0,
                    1.0,
                )
            )
            logger.debug(
                "VocalLanguage: umlaut=%.2f f2_bimodal=%.2f ch_ratio=%.2f → lang_de=%.2f",
                umlaut_score,
                f2_bimodal_score,
                ch_score,
                lang_de_score,
            )
            return float(np.nan_to_num(lang_de_score, nan=0.5))

        except Exception as exc:
            logger.debug("VocalLanguage Fallback: %s", exc)
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

    def _is_schlager_near_miss(
        self,
        *,
        n_active: int,
        confidence: float,
        hsi: float,
        rhythm_score: float,
        vocal_prior: float,
        melodic_rep: float,
        lang_de_score: float,
    ) -> bool:
        """Identify German Schlager near-miss cases to avoid wrong fallback labels.

        This guard is intentionally strict and only triggers when core Schlager
        cues are present but the hard gate is narrowly missed.
        """
        if n_active < 2:
            return False
        if confidence < (self.SCHLAGER_CONFIDENCE_THRESHOLD - 0.08):
            return False
        if hsi < 0.68 or rhythm_score < 0.55:
            return False
        if vocal_prior < 0.52 or lang_de_score < 0.58:
            return False
        if melodic_rep < 0.36:
            return False
        return True

    def _score_oper(
        self,
        centroid_hz: float,
        onset_rate: float,
        hsi: float,
        dr_db: float,
    ) -> float:
        """Opera genre score: extreme dynamics + vocal-range centroid + diatonic harmony.

        Key differentiators from Klassik (pure orchestral):
        - Singer's formant (2–3 kHz) raises spectral centroid above purely orchestral material.
        - Very wide DR (singer piano/forte contrasts exceed orchestral range).
        - Moderate onset density: vocal consonants + orchestra, but less than rock.
        """
        score = 0.0
        # Very high dynamic range — even wider than Klassik (singer's piano/forte extremes)
        if dr_db > 48:
            score += 0.35
        elif dr_db > 38:
            score += 0.15
        # Vocal-range spectral centroid: singer's formant (2–3 kHz) elevates centroid
        # above purely orchestral material (Klassik: centroid < 2200 Hz)
        if 1800 < centroid_hz < 3200:
            score += 0.25
        elif 1400 < centroid_hz <= 1800:
            score += 0.10
        # Moderate onset density — vocal consonants + orchestra; less than rock
        if 0.8 < onset_rate < 2.8:
            score += 0.15
        # Diatonic harmony (tonal, like Klassik)
        if 0.55 <= hsi <= 0.88:
            score += 0.15
        return float(np.clip(score, 0.0, 1.0))

    def _compute_non_schlager_scores(
        self,
        centroid_hz: float,
        onset_rate: float,
        hsi: float,
        dr_db: float,
        bpm: float,
    ) -> dict[str, float]:
        rock_s = self._score_rock(centroid_hz, onset_rate, hsi, bpm)
        jazz_s = self._score_jazz(centroid_hz, hsi, dr_db, bpm)
        classical_s = self._score_classical(centroid_hz, onset_rate, hsi, dr_db)
        oper_s = self._score_oper(centroid_hz, onset_rate, hsi, dr_db)
        return {
            "Rock": float(np.clip(rock_s, 0.0, 1.0)),
            "Jazz": float(np.clip(jazz_s, 0.0, 1.0)),
            "Klassik": float(np.clip(classical_s, 0.0, 1.0)),
            "Oper": float(np.clip(oper_s, 0.0, 1.0)),
        }

    def _pick_non_schlager_genre(self, scores: dict[str, float]) -> tuple[str, float]:
        if not scores:
            return "Unbekannt", 0.0
        best_genre = max(scores, key=scores.get)  # type: ignore[arg-type]
        best_score = float(scores[best_genre])
        if best_score >= self._NON_SCHLAGER_MIN_SCORE:
            return best_genre, best_score
        return "Unbekannt", 0.0

    def _infer_genre_family(
        self,
        non_schlager_scores: dict[str, float],
        schlager_family_score: float,
    ) -> tuple[str, float]:
        family_scores = {
            "schlager_folk": float(np.clip(schlager_family_score, 0.0, 1.0)),
            "rock": float(np.clip(non_schlager_scores.get("Rock", 0.0), 0.0, 1.0)),
            "jazz": float(np.clip(non_schlager_scores.get("Jazz", 0.0), 0.0, 1.0)),
            "klassik": float(np.clip(non_schlager_scores.get("Klassik", 0.0), 0.0, 1.0)),
            "oper": float(np.clip(non_schlager_scores.get("Oper", 0.0), 0.0, 1.0)),
        }
        label = max(family_scores, key=family_scores.get)  # type: ignore[arg-type]
        score = float(family_scores[label])
        if score < self._OPEN_SET_MIN_SCORE:
            return "unknown", 0.0
        return label, score

    def _build_top_genres(
        self,
        *,
        is_schlager: bool,
        primary_label: str,
        primary_confidence: float,
        non_schlager_scores: dict[str, float],
    ) -> list[tuple[str, float]]:
        top: list[tuple[str, float]] = []
        if primary_label and primary_label.lower() not in ("unknown", "unbekannt"):
            top.append((str(primary_label), float(np.clip(primary_confidence, 0.0, 1.0))))
        ranked = sorted(non_schlager_scores.items(), key=lambda x: x[1], reverse=True)
        for label, score in ranked:
            if score < self._NON_SCHLAGER_MIN_SCORE:
                continue
            if any(lbl.lower() == label.lower() for lbl, _ in top):
                continue
            top.append((label, float(np.clip(score, 0.0, 1.0))))
            if len(top) >= 3:
                break
        if not top and is_schlager:
            top.append(("Schlager", float(np.clip(primary_confidence, 0.0, 1.0))))
        return top

    def _is_open_set_unknown(self, top_genres: list[tuple[str, float]]) -> bool:
        if not top_genres:
            return True
        scores = sorted((float(score) for _, score in top_genres), reverse=True)
        best = scores[0]
        if best < self._OPEN_SET_MIN_SCORE:
            return True
        second = scores[1] if len(scores) > 1 else 0.0
        return (best - second) < self._OPEN_SET_MARGIN

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

    def _determine_genre_label(self, subgenre: str, bpm: float, lang_de_score: float = 0.5) -> str:
        """Bestimmt das Genre-Label aus Subgenre, BPM und Sprachscore.

        lang_de_score >= 0.55 → Deutscher Schlager (eindeutig deutschsprachig).
        lang_de_score < 0.30 → Internationaler Schlager (englischsprachig vermutet).
        0.30–0.55 → Schlager (Sprache unsicher).
        """
        mapping = {
            "schunkel": "Schlager",
            "walzer": "Walzer",
            "marsch": "Marsch",
            "discoschlager": "Disco-Schlager",
            "unknown": "Schlager",
        }
        base_label = mapping.get(subgenre, "Schlager")
        if lang_de_score < 0.30:
            return f"Internationaler {base_label}"
        if lang_de_score >= 0.55 and base_label == "Schlager":
            return f"Deutscher {base_label}"
        return base_label

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
        lang_de_score: float = 0.5,
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
        if lang_de_score >= 0.55:
            parts.append(f"Deutschsprachiger Gesang erkannt ({lang_de_score:.2f})")
        elif lang_de_score < 0.30:
            parts.append(f"Englischsprachiger Gesang vermutet ({lang_de_score:.2f}) → Sprach-Penalty")
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
