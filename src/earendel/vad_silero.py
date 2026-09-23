"""VAD neural (Silero v4, ONNX ~2MB, CPU): 'tem voz aqui?' a cada 32ms.

Troca o portão de energia no fim de fala: entende sílaba baixa e ignora
ruído por conteúdo, não por volume. Modelo integrado em ./models
(offline: só bootstrap/setup baixa).
"""
from __future__ import annotations

import os

URL = ("https://github.com/snakers4/silero-vad/raw/v4.0/files/"
       "silero_vad.onnx")
FNAME = "silero_vad.onnx"
WIN = 512  # amostras @16kHz por janela


def model_path() -> str:
    from . import config as cfgmod
    env = os.environ.get("EARENDEL_SILERO")
    if env:
        return env
    return os.path.join(cfgmod.models_dir(), FNAME)


def ensure_model() -> str:
    import urllib.request
    from .stt import allow_download
    p = model_path()
    if os.path.exists(p) and os.path.getsize(p) > 1000000:
        return p
    if not allow_download():
        raise RuntimeError(
            "silero_vad.onnx ausente e modo offline: rode scripts/install.sh")
    print("[earendel] baixando VAD neural (~2MB)...")
    urllib.request.urlretrieve(URL, p)
    print("[earendel] VAD pronto.")
    return p


class SileroVAD:
    def __init__(self, sr=16000):
        import numpy as np
        import onnxruntime as ort
        self.sr = sr
        self.session = ort.InferenceSession(
            ensure_model(), providers=["CPUExecutionProvider"])
        self._np = np
        self.reset()

    def reset(self):
        import numpy as np
        self.h = np.zeros((2, 1, 64), dtype=np.float32)
        self.c = np.zeros((2, 1, 64), dtype=np.float32)
        self._was_voice = False

    def prob(self, frame) -> float:
        """Probabilidade de voz (0..1) em 512 amostras; com estado."""
        import numpy as np
        x = np.asarray(frame, dtype=np.float32).reshape(-1)
        if x.size < WIN:
            x = np.pad(x, (0, WIN - x.size))
        else:
            x = x[-WIN:]
        ort_inputs = {"input": x.reshape(1, -1),
                      "sr": np.array(self.sr, dtype=np.int64),
                      "h": self.h, "c": self.c}
        out, self.h, self.c = self.session.run(None, ort_inputs)
        return float(out[0][0])

    def is_voice(self, frame, start=0.5, cont=0.35) -> bool:
        p = self.prob(frame)
        th = cont if self._was_voice else start
        self._was_voice = p >= th
        return self._was_voice
