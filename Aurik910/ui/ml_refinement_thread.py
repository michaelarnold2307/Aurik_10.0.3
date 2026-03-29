"""
Aurik910/ui/ml_refinement_thread.py — MLRefinementThread §2.38 KMV Stufe 2
==========================================================================

Implements the background ML-refinement thread that re-runs deferred phases
with no RT limit after the Stufe-1 (fast) export is already on disk.

Spec §2.38 invariants enforced here:
  - LIMIT_BACKGROUND = float("inf") — no RT cap for this thread only.
  - Stufe-2 export only overwrites Stufe-1 file when stufe2_quality >= stufe1_quality.
  - Atomic write: .tmp → os.replace (POSIX-safe).
  - ml_memory_budget.try_allocate("kmv_job", size_gb) registered before processing;
    released on both success and failure paths.
  - isInterruptionRequested() checked between phases (escapable).
  - Single-active-invariant enforced by caller (ModernMainWindow).
  - Priority: QThread.LowPriority + os.nice(10) on Linux.
"""

from __future__ import annotations

import logging
import os
import time
from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np

if TYPE_CHECKING:
    from PyQt5.QtCore import QThread, pyqtSignal
else:
    try:
        from PyQt5.QtCore import QThread, pyqtSignal
    except ImportError:  # Headless test environment

        class QThread:  # type: ignore[no-redef]
            LowPriority = 1

            def __init__(self) -> None:
                self._interrupt = False

            def isInterruptionRequested(self) -> bool:
                return self._interrupt

            def requestInterruption(self) -> None:
                self._interrupt = True

            def setPriority(self, _p) -> None:
                pass

            def start(self, _p=None) -> None:
                self.run()

        def pyqtSignal(*args):  # type: ignore[no-redef]
            class _Sig:
                def connect(self, _fn):
                    pass

                def emit(self, *a, **kw):
                    pass

            return _Sig()


from backend.core.deferred_refinement_job import DeferredRefinementJob

logger = logging.getLogger(__name__)

# ── Spec §2.38: Hintergrundthread läuft ohne RT-Limit ────────────────────────
_LIMIT_BACKGROUND: float = float("inf")


class MLRefinementThread(QThread):
    """KMV Stufe-2 background refinement thread.

    Signals (§2.38 Spec contract):
        refinement_started(output_path: str, n_deferred_phases: int)
        refinement_phase_done(phase_id: str, quality_improvement_delta: float)
        refinement_progress(pct: int, phase_name: str)       # 0–100
        refinement_complete(output_path: str, result: object) # final RestorationResult
        refinement_cancelled(output_path: str)               # Stufe-1 export kept
    """

    refinement_started = pyqtSignal(str, int)
    refinement_phase_done = pyqtSignal(str, float)
    refinement_progress = pyqtSignal(int, str)
    refinement_complete = pyqtSignal(str, object)
    refinement_cancelled = pyqtSignal(str)

    def __init__(self, job: DeferredRefinementJob) -> None:
        super().__init__()
        self.job = job
        self._result = None

    # ------------------------------------------------------------------
    # Public helpers
    # ------------------------------------------------------------------

    @staticmethod
    def should_start(job: DeferredRefinementJob) -> bool:
        """Return True when all Stufe-2 start conditions are met (§2.38)."""
        if not job.deferred_phase_ids:
            return False
        try:
            import psutil

            avail_gb = psutil.virtual_memory().available / 1024**3
            if avail_gb < 4.0:
                logger.info("KMV Stufe 2 nicht gestartet: nur %.1f GB RAM frei (< 4 GB)", avail_gb)
                return False
        except Exception:
            pass  # psutil not available → proceed without check
        return True

    # ------------------------------------------------------------------
    # Thread entry point
    # ------------------------------------------------------------------

    def run(self) -> None:
        """Execute KMV Stufe-2: full ML pass → conditional atomic overwrite."""
        job = self.job
        output_path = job.output_path

        # Set low OS priority (§2.38: do not compete with UI)
        try:
            self.setPriority(QThread.LowPriority)
        except Exception:
            pass
        try:
            os.nice(10)
        except Exception:
            pass

        self.refinement_started.emit(output_path, job.n_deferred)
        logger.info(
            "KMV Stufe 2 gestartet: %d deferred phases | output=%s",
            job.n_deferred,
            output_path,
        )

        # ── 1. Register audio in ml_memory_budget ────────────────────────────
        _budget_registered = False
        try:
            from backend.core.ml_memory_budget import get_ml_memory_budget

            _budget = get_ml_memory_budget()
            _budget_registered = _budget.try_allocate("kmv_job", job.audio_size_gb)
            if not _budget_registered:
                logger.warning(
                    "KMV Stufe 2: ml_memory_budget.try_allocate('kmv_job', %.2f GB) fehlgeschlagen"
                    " — Stufe-2-Export abgebrochen.",
                    job.audio_size_gb,
                )
                self.refinement_cancelled.emit(output_path)
                return
        except Exception as _be:
            logger.debug("ml_memory_budget nicht verfügbar (KMV): %s", _be)
            # Continue without budget guard if module absent (test environments)
            _budget_registered = False

        t0 = time.perf_counter()
        _result = None
        try:
            if self.isInterruptionRequested():
                self.refinement_cancelled.emit(output_path)
                return

            # ── 2. Full UV3 pass via AurikDenker with no_rt_limit=True ───────
            self.refinement_progress.emit(5, "ML-Veredelung: Analyse …")

            try:
                from backend.api.bridge import get_aurik_denker_instance as _get_denker

                _denker = _get_denker()
            except Exception as _imp_err:
                logger.error("KMV Stufe 2: AurikDenker nicht verfügbar: %s", _imp_err)
                self.refinement_cancelled.emit(output_path)
                return

            if _denker is None:
                logger.error("KMV Stufe 2: AurikDenker-Singleton ist None")
                self.refinement_cancelled.emit(output_path)
                return

            # Progress reporter that maps 0–100 → 10–90 (leave room for pre/post steps)
            def _progress_cb(pct: int, msg: str, elapsed_s: float = 0.0) -> None:
                if self.isInterruptionRequested():
                    return
                mapped = 10 + int(pct * 0.80)
                self.refinement_progress.emit(min(mapped, 90), msg)

            _result = _denker.denke(
                audio=job.audio_original,
                sr=job.sr,
                mode=job.mode,
                progress_callback=_progress_cb,
                no_rt_limit=True,  # §2.38 KMV Stufe 2: kein RT-Limit
                cached_defect_result=job.cached_defect_result,
                cached_era_result=job.cached_era_result,
                cached_medium_result=job.cached_medium_result,
                input_path=job.input_path,
                output_path=output_path,
            )

            if self.isInterruptionRequested():
                logger.info("KMV Stufe 2 abgebrochen nach Denker-Lauf")
                self.refinement_cancelled.emit(output_path)
                return

            self.refinement_progress.emit(91, "ML-Veredelung: Qualitätsprüfung …")

            # ── 3. Quality invariant: only overwrite when Stufe 2 ≥ Stufe 1 ─
            _r = _result  # may be AurikErgebnis or RestorationResult
            _stufe2_quality = _extract_quality(_r)

            if _stufe2_quality is None or _stufe2_quality < job.stufe1_quality:
                logger.info(
                    "KMV Stufe 2: Qualität nicht verbessert (Stufe2=%.3f < Stufe1=%.3f) — Stufe-1-Export behalten.",
                    _stufe2_quality if _stufe2_quality is not None else float("nan"),
                    job.stufe1_quality,
                )
                self.refinement_cancelled.emit(output_path)
                return

            self.refinement_progress.emit(93, "ML-Veredelung: Export …")

            # ── 4. Extract audio and write atomically ──────────────────────
            _audio = _extract_audio(_r)
            if _audio is None or _audio.size == 0:
                logger.warning("KMV Stufe 2: Kein Audio im Ergebnis — Stufe-1-Export behalten.")
                self.refinement_cancelled.emit(output_path)
                return

            # Validate audio
            _audio = np.nan_to_num(_audio, nan=0.0, posinf=0.0, neginf=0.0)
            _audio = np.clip(_audio, -1.0, 1.0)

            _tmp_path = output_path + ".kmv_tmp"
            try:
                _write_audio(_audio, job.sr, _tmp_path)
                os.replace(_tmp_path, output_path)
            except Exception as _write_err:
                logger.error("KMV Stufe 2: Atomic-Write fehlgeschlagen: %s", _write_err)
                try:
                    Path(_tmp_path).unlink(missing_ok=True)
                except Exception:
                    pass
                self.refinement_cancelled.emit(output_path)
                return

            # ── 5. Mark result as Stufe-2-complete ───────────────────────
            try:
                _r.refinement_complete = True
                _r.stufe2_quality_estimate = float(_stufe2_quality)
            except Exception:
                pass

            elapsed = time.perf_counter() - t0
            logger.info(
                "KMV Stufe 2 erfolgreich: Stufe2=%.3f (Δ+%.3f) in %.1f s → %s",
                _stufe2_quality,
                _stufe2_quality - job.stufe1_quality,
                elapsed,
                output_path,
            )
            self.refinement_progress.emit(100, "ML-Veredelung abgeschlossen ✓")
            self.refinement_complete.emit(output_path, _r)

        except Exception as _run_err:
            logger.error("KMV Stufe 2: Unerwarteter Fehler: %s", _run_err, exc_info=True)
            self.refinement_cancelled.emit(output_path)
        finally:
            # §3.9.9: ALWAYS release buffer — success, cancellation, or exception.
            # DeferredRefinementJob.release_buffer() calls ml_memory_budget.release()
            # and sets audio_original=None so GC can reclaim the large array.
            # §2.38a Invariante: Nur release() wenn try_allocate() erfolgreich war
            if _budget_registered:
                try:
                    job.release_buffer()
                except Exception as _rel_err:
                    logger.debug("KMV buffer release failed (non-fatal): %s", _rel_err)
            else:
                # Budget war nie registriert (early return oder Exception), fallback: job-Destruktor
                try:
                    job._audio_original = None
                except Exception:
                    pass


# ── Private helpers ────────────────────────────────────────────────────────────


def _extract_quality(result: object) -> float | None:
    """Extract quality_estimate from AurikErgebnis or RestorationResult."""
    if result is None:
        return None
    # AurikErgebnis
    for attr in ("quality_estimate", "restoration_result"):
        val = getattr(result, attr, None)
        if val is None:
            continue
        if isinstance(val, (int, float)):
            return float(val)
        # Nested RestorationResult
        inner = getattr(val, "quality_estimate", None)
        if isinstance(inner, (int, float)):
            return float(inner)
    return None


def _extract_audio(result: object) -> np.ndarray | None:
    """Extract audio array from AurikErgebnis or RestorationResult."""
    if result is None:
        return None
    # Direct .audio attribute
    audio = getattr(result, "audio", None)
    if isinstance(audio, np.ndarray) and audio.size > 0:
        return audio
    # Nested .restoration_result.audio
    rr = getattr(result, "restoration_result", None)
    if rr is not None:
        audio2 = getattr(rr, "audio", None)
        if isinstance(audio2, np.ndarray) and audio2.size > 0:
            return audio2
    return None


def _write_audio(audio: np.ndarray, sr: int, path: str) -> None:
    """Write audio to file — tries soundfile, falls back to scipy.io.wavfile."""
    try:
        import soundfile as sf

        mono_or_stereo = audio if audio.ndim == 2 else audio[:, None]
        sf.write(path, mono_or_stereo, sr, subtype="FLOAT")
        return
    except Exception:
        pass
    import numpy as _np
    import scipy.io.wavfile as _wf

    _a = (audio * 32767).astype(_np.int16)
    _wf.write(path, sr, _a)
