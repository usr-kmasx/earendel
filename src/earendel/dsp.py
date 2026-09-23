"""DSP próprio (só numpy): voz x ruído sem depender de volume.

Técnica em 2 camadas (antes: só limiar de energia):
1. VoiceGate: energia + HARMONICIDADE. Vogais têm pitch (autocorrelação alta);
   ventilador/tecladada/ruído branco não. Com hangover p/ não cortar
   consoante no meio da palavra. Decide quando PARAR de gravar.
2. denoise(): máscara de Wiener com perfil do ambiente (trecho sem voz).
   Limpa o áudio antes do Whisper -> transcreve melhor com barulho.

Limite honesto: conversa de fundo (TV, outra pessoa) É voz harmônica —
isso nenhum DSP local separa; aí só mic perto da boca / ambiente quieto.
"""
from __future__ import annotations

import numpy as np


def rms(block) -> float:
    return float(np.sqrt(np.mean(np.asarray(block, dtype=np.float64) ** 2) + 1e-12))


def energy_thresh(noise_floor: float) -> float:
    return min(0.06, max(0.012, noise_floor * 2.0 + 0.003))


def is_harmonic(frame, sr=16000, fmin=60, fmax=400, min_peak=0.45) -> bool:
    """Pico de autocorrelação normalizada na faixa de pitch => som vozeado."""
    x = np.asarray(frame, dtype=np.float64)
    x = x - x.mean()
    if x.size < sr // fmax + 8:
        return False
    corr = np.correlate(x, x, "full")[len(x) - 1:]
    if corr[0] <= 1e-12:
        return False
    lo, hi = sr // fmax, sr // fmin
    return bool(corr[lo:hi].max() / corr[0] >= min_peak)


class VoiceGate:
    """Diz se um frame (20ms) é voz: energia ok E harmônico, com hangover.

    `last_energy` guarda a energia do último frame p/ a lógica de parada:
    som ALTO não-harmônico (consoante, barulho) SEGURA o timer em vez de
    acumular silêncio — só quietude de verdade encerra.
    """

    def __init__(self, noise_floor: float, sr=16000, frame_n=320,
                 hangover_s=0.4, min_peak=0.35):
        self.sr = sr
        self.frame_n = frame_n
        self.te = energy_thresh(noise_floor)
        self.te_low = max(0.006, noise_floor * 1.3 + 0.001)  # histerese
        self.low = noise_floor * 1.3 + 0.002  # quietude de verdade
        self.min_peak = min_peak
        self.hang_n = max(1, int(hangover_s * sr / frame_n))
        self._hang = 0
        self.last_energy = 0.0
        self.relaxed = False

    def relax(self):
        """Depois de voz confirmada: aceita sílaba baixa (não corta)."""
        self.relaxed = True

    def frame_voice(self, frame) -> bool:
        fr = np.asarray(frame).reshape(-1)
        self.last_energy = rms(fr)
        te = self.te_low if self.relaxed else self.te
        raw = self.last_energy >= te and \
            is_harmonic(fr, self.sr, min_peak=self.min_peak)
        if raw:
            self._hang = self.hang_n
            return True
        if self._hang > 0:
            self._hang -= 1
            return True
        return False


def mag_profile(audio, sr=16000, frame_n=512) -> np.ndarray | None:
    """Espectro médio (perfil do ambiente) p/ a máscara de Wiener."""
    a = np.asarray(audio, dtype=np.float32).reshape(-1)
    if a.size < frame_n:
        return None
    win = np.hanning(frame_n)
    mags = []
    for i in range(0, a.size - frame_n + 1, frame_n):
        mags.append(np.abs(np.fft.rfft(a[i:i + frame_n] * win)))
    if not mags:
        return None
    return np.mean(mags, axis=0).astype(np.float32)


def denoise(audio, noise_mag, sr=16000, frame_n=512,
            over=1.5, floor=0.02) -> np.ndarray:
    """Subtração espectral (Wiener): tira ruído estacionário, preserva voz."""
    a = np.asarray(audio, dtype=np.float32).reshape(-1)
    if noise_mag is None or a.size < frame_n:
        return a
    hop = frame_n // 2
    win = np.hanning(frame_n).astype(np.float32)
    n_mag = np.asarray(noise_mag, dtype=np.float32)
    out = np.zeros(a.size + frame_n, dtype=np.float32)
    wsum = np.zeros_like(out)
    for i in range(0, a.size - frame_n + 1, hop):
        spec = np.fft.rfft(a[i:i + frame_n] * win)
        mag = np.abs(spec) + 1e-10
        mask = np.maximum(mag ** 2 - over * n_mag ** 2,
                          (floor * mag) ** 2) / mag ** 2
        y = np.fft.irfft(spec * mask, frame_n).astype(np.float32)
        out[i:i + frame_n] += y * win
        wsum[i:i + frame_n] += win ** 2
    wsum[wsum < 0.05] = 1.0  # bordas: janela~0 => saída~0 (sem amplificar pó numérico)
    return (out[:a.size] / wsum[:a.size]).astype(np.float32)


def spectrum_bars(audio, sr=16000, n=24, fmin=80, fmax=8000,
                  noise_mag=None, peak=None, gate_floor=None) -> list:
    """Barras estilo Cava: energia por banda (log) do trecho recente.

    Com `noise_mag` (perfil do ambiente): voz salta, silêncio fica plano.
    Sem: AGC por peak-hold (`peak` = [valor] mutável entre chamadas).
    Com `gate_floor`: abaixo dessa energia retorna tudo zero (sem dança).
    """
    a = np.asarray(audio, dtype=np.float32).reshape(-1)
    if a.size < 1024:
        return [0.0] * n
    if gate_floor is not None and rms(a) < gate_floor:
        return [0.0] * n
    seg = a[-4096:] if a.size >= 4096 else a
    win = np.hanning(len(seg))
    spec = np.abs(np.fft.rfft(seg * win))
    freqs = np.fft.rfftfreq(len(seg), 1.0 / sr)
    edges = np.logspace(np.log10(fmin), np.log10(fmax), n + 1)
    out = np.zeros(n)
    for i in range(n):
        m = (freqs >= edges[i]) & (freqs < edges[i + 1])
        out[i] = spec[m].mean() if m.any() else 0.0
    if noise_mag is not None:
        nm = np.asarray(noise_mag, dtype=np.float64)
        nf = np.fft.rfftfreq(max(2, (len(nm) - 1) * 2), 1.0 / sr)
        nb = np.zeros(n)
        for i in range(n):
            m = (nf >= edges[i]) & (nf < edges[i + 1])
            nb[i] = nm[m].mean() if m.any() else 0.0
        sig = np.maximum(out - nb * 2.0, 0.0)  # tira o chão de ruído
    else:
        sig = out
    if peak is not None and len(peak) == n:
        peak[:] = list(np.maximum(sig, np.array(peak) * 0.95))
        out = sig / (np.maximum(peak, 1e-9))
    elif peak is not None:
        peak[0] = max(float(sig.max()), peak[0] * 0.95)
        out = sig / (peak[0] + 1e-9)
    else:
        out = sig / (sig.max() + 1e-9)
    return [float(min(1.0, max(0.0, v))) for v in out]
