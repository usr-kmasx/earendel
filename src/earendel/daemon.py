"""Loop principal: wake-word 'earendel' -> popup wave -> grava -> transcreve -> digita."""
from __future__ import annotations

import queue
import threading
import time

import numpy as np

from . import audio as audiomod
from . import config as cfgmod
from . import hotkey as hotkeymod
from . import popup as popupmod
from . import stt as sttmod
from . import typer as typermod

TRIGGER_HOTKEY = threading.Event()


class GaplessMic:
    """Stream contínuo: elimina o ponto-cego entre gravar e transcrever.

    O loop antigo gravava 3s, PARAVA p/ transcrever (~1s surdo) e repetia.
    Aqui o microfone nunca fecha: cada ciclo transcreve os últimos N segundos
    enquanto o stream continua enchendo o buffer.
    """

    def __init__(self, sr: int, device, keep_s: float = 12.0):
        self.sr = sr
        self.device = device  # None = seguir o padrão do sistema
        self.keep = int(sr * keep_s)
        self._buf = np.zeros(0, dtype=np.float32)
        self._lock = threading.Lock()
        self._stream = None
        self.bound_index: int | None = None  # device real em uso
        self._total = 0      # amostras já anexadas (monotônico)
        self._base = 0       # amostras descartadas pelo trim (monotônico)
        self._consumed = 0   # amostras já lidas via read_new (monotônico)

    def _cb(self, indata, _frames, _time, _status):
        with self._lock:
            blk = indata.reshape(-1)
            self._buf = np.concatenate([self._buf, blk])
            self._total += blk.size
            if len(self._buf) > self.keep:
                drop = len(self._buf) - self.keep
                self._buf = self._buf[-self.keep:]
                self._base += drop

    def start(self):
        import sounddevice as sd
        from . import audio as audiomod
        # resolve p/ saber em qual device amarramos (None = padrão do sistema agora)
        dev = self.device
        self.bound_index = (audiomod.current_default_index()
                            if dev is None else int(dev))
        self._stream = sd.InputStream(samplerate=self.sr, channels=1,
                                      dtype="float32", device=self.device,
                                      callback=self._cb)
        self._stream.start()

    def restart(self):
        """Reabre o stream (usado quando o padrão do sistema muda)."""
        self.stop()
        with self._lock:
            self._buf = np.zeros(0, dtype=np.float32)
            self._total = self._base = self._consumed = 0
        self.start()

    def window(self, seconds: float) -> np.ndarray:
        with self._lock:
            return self._buf[-int(self.sr * seconds):].copy()

    def read_new(self) -> np.ndarray:
        """Áudio anexado desde a última leitura (p/ o porteiro, sem repetir)."""
        with self._lock:
            start = max(0, self._consumed - self._base)
            out = self._buf[start:].copy()
            self._consumed = self._total
            return out

    def stop(self):
        try:
            if self._stream:
                self._stream.stop()
                self._stream.close()
        except Exception:
            pass
        self._stream = None


def _record(seconds: float, sr: int, device, status_q=None) -> np.ndarray:
    import sounddevice as sd
    frames: list[np.ndarray] = []

    def cb(indata, _frames, _time, status):
        if status and status_q is not None:
            pass
        frames.append(indata.copy())

    with sd.InputStream(samplerate=sr, channels=1, dtype="float32",
                        device=device, callback=cb):
        time.sleep(seconds)
    if not frames:
        return np.zeros(int(seconds * sr), dtype=np.float32)
    return np.concatenate(frames, axis=0).reshape(-1)


def _rms(block) -> float:
    return float(np.sqrt(np.mean(np.asarray(block, dtype=np.float64) ** 2) + 1e-12))


def _voice_thresh(noise_floor: float) -> float:
    """Limiar adaptativo: acompanha o ruído do ambiente em vez de fixo."""
    return min(0.06, max(0.012, noise_floor * 2.0 + 0.003))


def _record_until_silence(sr: int, device, noise_floor=0.01,
                          silence_s=1.2, no_voice_s=3.0, _blocks=None) -> np.ndarray:
    """Grava até `silence_s` de silêncio APÓS voz real. Sem teto de tempo:
    enquanto houver voz, continua gravando; só para quando você parar.

    Voz = energia ok E harmônica (VoiceGate): barulho alto sem pitch
    (teclada, batida, chiado) não segura a gravação.
    `_blocks` é só p/ testes (lista de blocos em vez do mic real).
    """
    import sounddevice as sd
    from . import dsp as dspmod
    gate = dspmod.VoiceGate(noise_floor, sr)
    frame_n = gate.frame_n
    chunks: list[np.ndarray] = []
    pending = np.zeros(0, dtype=np.float32)
    silent = 0.0
    voiced = 0.0
    elapsed = 0.0

    def feed(block: np.ndarray):
        nonlocal pending, silent, voiced, elapsed
        block = np.asarray(block, dtype=np.float32).reshape(-1)
        chunks.append(block)
        elapsed += block.size / sr
        buf = np.concatenate([pending, block]) if pending.size else block
        n = (buf.size // frame_n) * frame_n
        for i in range(0, n, frame_n):
            if gate.frame_voice(buf[i:i + frame_n]):
                voiced += frame_n / sr
                silent = 0.0
            elif gate.last_energy >= gate.low:
                pass  # alto mas não-vozeado: segura (não corta, não conta)
            else:
                silent += frame_n / sr
        pending = buf[n:]

    def should_stop() -> bool:
        if voiced < 0.5 and elapsed >= no_voice_s:
            return True
        if voiced >= 0.7 and silent >= silence_s:
            return True
        if voiced >= 0.5 and silent >= silence_s + 1.0:
            return True  # elocução curta: janela maior, mas para
        return False

    def finish():
        if not chunks:
            return np.zeros(sr, dtype=np.float32)
        return np.concatenate(chunks, axis=0).reshape(-1)

    if _blocks is not None:
        for blk in _blocks:
            feed(blk)
            if should_stop():
                break
        return finish()

    q: queue.Queue = queue.Queue()
    with sd.InputStream(samplerate=sr, channels=1, dtype="float32",
                        device=device, callback=lambda d, *a: q.put(d.copy())):
        while True:
            try:
                feed(q.get(timeout=2))
            except queue.Empty:
                break
            if should_stop():
                break
    return finish()


def _to_16k(mono: np.ndarray, from_sr: int, to_sr=16000) -> np.ndarray:
    mono = np.asarray(mono, dtype=np.float32).reshape(-1)
    if from_sr == to_sr or mono.size == 0:
        return mono
    # reamostragem linear (sem scipy, p/ manter isolado/leve)
    ratio = to_sr / float(from_sr)
    idx = (np.arange(int(len(mono) * ratio)) / ratio).astype(np.float64)
    i0 = np.floor(idx).astype(int).clip(0, len(mono) - 1)
    i1 = np.minimum(i0 + 1, len(mono) - 1)
    frac = (idx - np.floor(idx)).astype(np.float32)
    return (mono[i0] * (1 - frac) + mono[i1] * frac).astype(np.float32)


def dictate_once(cfg: dict, status_cb=print, mic=None, noise_mag=None) -> str:
    """Uma ditada avulsa: popup + grava + transcreve + digita. Usado pelo wake e pelo --toggle."""
    from . import dsp as dspmod
    sttmod.configure_idle(cfg.get("idle_unload_s", 180))
    sr_native = 16000
    device = audiomod.query_device_index(cfg.get("mic"))
    try:
        import sounddevice as sd
        if device is None:
            info = sd.query_devices(kind="input")
            sr_native = int(info.get("default_samplerate", 16000))
        else:
            info = sd.query_devices(device)
            sr_native = int(info.get("default_samplerate", 16000))
    except Exception:
        pass

    # calibra o ruído do ambiente na hora (do stream contínuo, sem espera extra)
    noise_floor = 0.01
    try:
        if mic is not None:
            tail = mic.window(1.0)
            if tail.size > sr_native // 4:
                noise_floor = _rms(tail)
        else:
            noise_floor = _rms(_record(0.4, sr_native, device))
    except Exception:
        pass

    pop = popupmod.WavePopupProcess("Ouvindo... fale agora")
    pop.show()
    t = {"rec": 0.0, "clean": 0.0, "stt": 0.0, "type": 0.0}
    import time as _time
    import threading as _threading
    # espelha a voz no popup (barras estilo Cava, ~15fps, só gravando)
    stop_bars = _threading.Event()
    agc_peak = [1e-6]
    bars_floor = dspmod.energy_thresh(noise_floor)

    def _bars_sender():
        while not stop_bars.wait(1.0 / 15):
            try:
                if mic is None:
                    return
                seg = mic.window(0.4)
                if seg.size < 1600:
                    continue
                pop.set_bars(dspmod.spectrum_bars(
                    seg, peak=agc_peak, noise_mag=noise_mag,
                    gate_floor=bars_floor))
            except Exception:
                pass

    _bt = _threading.Thread(target=_bars_sender, daemon=True)
    _bt.start()
    try:
        _t0 = _time.perf_counter()
        raw = _record_until_silence(sr_native, device, noise_floor=noise_floor,
                                    silence_s=cfg.get("silence_s", 1.0),
                                    no_voice_s=cfg.get("no_voice_s", 3.0))
        t["rec"] = _time.perf_counter() - _t0
    finally:
        stop_bars.set()

    try:
        audio16 = _to_16k(raw, sr_native, 16000)
        if audio16.size < 16000 * 0.4:
            pop.update_text("Não ouvi nada.")
            time.sleep(1.0)
            return ""
        pop.update_text("Transcrevendo...")
        _t0 = _time.perf_counter()
        if noise_mag is not None and noise_floor >= 0.009:
            audio16 = dspmod.denoise(audio16, noise_mag)
        t["clean"] = _time.perf_counter() - _t0
        text = sttmod.transcribe_with_progress(
            audio16, cfg.get("stt_model", "small"),
            language=cfg.get("language"),
            progress_cb=lambda p: pop.set_progress(p))
        t["stt"] = _time.perf_counter() - _t0 - t["clean"]
        if not text:
            pop.update_text("Não entendi.")
            time.sleep(1.2)
            return ""
        pop.update_text(text)
        _t0 = _time.perf_counter()
        how, method = typermod.type_text(text)
        t["type"] = _time.perf_counter() - _t0
        if how == "clipboard":
            pop.update_text(f"{text}\n[copiado — cole com Ctrl+V]")
        status_cb(f"[earendel] ({how} via {method}) {text}")
        status_cb(f"[earendel] tempos: fala {len(audio16)/16000:.1f}s + "
                  f"fim {t['rec'] - len(audio16)/16000:.1f}s + "
                  f"limpa {t['clean']:.1f}s + modelo {t['stt']:.1f}s + "
                  f"digita {t['type']:.1f}s")
        time.sleep(1.0)
        return text
    finally:
        pop.close()


def run_daemon(cfg: dict | None = None):
    cfg = cfg or cfgmod.load()
    sttmod.configure_idle(cfg.get("idle_unload_s", 180))
    sr = int(cfg.get("sample_rate", 16000))
    device = audiomod.query_device_index(cfg.get("mic"))
    wakes = cfg.get("wake_words", ["earendel", "earende"])
    print(f"[earendel] ouvindo wake-word {wakes} ... (Ctrl+C p/ sair)")
    miss = typermod.missing_helpers()
    if miss:
        print("[earendel] opcionais ausentes (só afetam digitar/clipboard):")
        for m in miss:
            print(f"  - {m}")

    TRIGGER_HOTKEY.clear()

    def on_hotkey():
        TRIGGER_HOTKEY.set()

    hk = hotkeymod.HotkeyListener(cfg.get("key"), on_hotkey)
    hk.start()

    # pré-carrega o porteiro duplo (Vosk pt+en, mesma lista) ou whisper
    vw = None
    legacy_en = cfg.get("wake_words_en", []) or []
    if legacy_en and legacy_en != wakes:
        wakes = list(dict.fromkeys(list(wakes) + legacy_en))  # migração única
    if not wakes and cfg.get("wake_backend", "vosk") == "vosk":
        print("[earendel] SEM wake-word: só atalho/ditada avulsa.")
        print("[earendel] escolha a sua: earendel -conf -word \"sua-palavra\"")
    elif cfg.get("wake_backend", "vosk") == "vosk":
        try:
            from . import wake_vosk
            vw = wake_vosk.DualWake(wakes, wakes, sr)
            print(f"[earendel] porteiro duplo ativo (pt+en): {wakes}.")
        except Exception as e:
            print(f"[earendel] Vosk indisponível ({e}) -> whisper-tiny.")
    if vw is None and wakes:
        try:
            sttmod.get_model(cfg.get("wake_model", "tiny"))
            print(f"[earendel] modelo wake '{cfg.get('wake_model', 'tiny')}' pronto.")
        except Exception as e:
            print(f"[earendel] falha ao carregar modelo wake: {e}")
            print("[earendel] rode scripts/install.sh e verifique ./models.")
            return

    if wakes:
        print(f"[earendel] dica: fale {wakes} + o comando.")
    follow_system = cfg.get("mic") is None
    if follow_system:
        print("[earendel] mic: seguindo o padrão do sistema (troque na DE à vontade).")
    mic = GaplessMic(sr, device)
    try:
        mic.start()
    except Exception as e:
        print(f"[earendel] falha ao abrir o microfone: {e}")
        print("[earendel] veja com: earendel -conf -mic")
        return
    last_resync = time.time()
    from . import dsp as dspmod
    noise_mag = None  # perfil do ambiente: só aprende de trecho quieto
    try:
        while True:
            if TRIGGER_HOTKEY.is_set():
                TRIGGER_HOTKEY.clear()
                print("[earendel] atalho pressionado -> ditando...")
                dictate_once(cfg, mic=mic, noise_mag=noise_mag)
                continue
            # segue o padrão do sistema: se mudou na DE, reabre o stream
            if follow_system and time.time() - last_resync > 5:
                last_resync = time.time()
                cur = audiomod.current_default_index()
                if cur is not None and cur != mic.bound_index:
                    print(f"[earendel] padrão do sistema mudou -> mic device {cur}")
                    try:
                        mic.restart()
                    except Exception as e:
                        print(f"[earendel] falha ao reabrir mic: {e}")
            chunk = mic.window(3.5)
            if chunk.size < sr:  # stream ainda enchendo
                time.sleep(0.3)
                continue
            if vw is None and not wakes:
                time.sleep(0.5)  # sem gatilho: só atalho; não gasta CPU
                continue
            # aprende o ambiente quando está quieto (p/ limpar o áudio)
            if dspmod.rms(chunk) < 0.015:
                prof = dspmod.mag_profile(chunk[:sr])
                if prof is not None:
                    noise_mag = prof
            try:
                if vw is not None:
                    new = mic.read_new()
                    txt = ""
                    if new.size:
                        pcm = (np.clip(new.reshape(-1), -1, 1) * 32767
                               ).astype(np.int16).tobytes()
                        txt = vw.feed(pcm)
                else:
                    listen = dspmod.denoise(chunk, noise_mag) if noise_mag is not None else chunk
                    txt = sttmod.transcribe(listen, cfg.get("wake_model", "tiny"),
                                            language=None)
            except Exception as e:
                print(f"[earendel] erro no wake: {e}")
                time.sleep(0.5)
                continue
            if txt and sttmod.looks_like_wake(
                    txt, vw.words if vw is not None else wakes):
                print(f"[earendel] wake detectado ('{txt.strip()}') -> ouvindo...")
                dictate_once(cfg, mic=mic, noise_mag=noise_mag)
            elif vw is not None:
                time.sleep(0.25)  # cadência: porteiro não precisa girar a toda
    except KeyboardInterrupt:
        print("\n[earendel] encerrado.")
    finally:
        mic.stop()
        hk.stop()
