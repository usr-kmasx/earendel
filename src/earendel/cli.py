"""CLI `earendel`.

Formas aceitas (com 1 ou 2 traços — o pedido original usa 1 traço):
  earendel                                   -> daemon (wake-word sempre ativo)
  earendel -conf -key "ctrl+alt+e"          -> salva atalho GLOBAL DO APP
  earendel -conf -key                       -> mostra atalho atual
  earendel -conf -mic                       -> lista microfones
  earendel -conf -mic "usb"                 -> seleciona mic por nome/índice
  earendel --toggle                         -> UMA ditada avulsa (p/ ligar na DE se o Wayland bloquear o hotkey)
  earendel --status                         -> mostra config atual
  earendel -h / --help                      -> ajuda
"""
from __future__ import annotations

import sys

from . import config as cfgmod
from . import hotkey as hotkeymod

HELP = """Earendel — STT offline pt-BR/en-US (Faster-Whisper)

Uso:
  earendel                                  daemon: fica ouvindo 'earendel'
  earendel -conf -key "ctrl+alt+e"          salva o atalho GLOBAL DO APP (ouvido só com o daemon rodando)
  earendel -conf -key                       mostra o atalho atual
  earendel -conf -mic                       lista os microfones
  earendel -conf -mic "parte-do-nome|idx"   fixa um microfone
  earendel -conf -mic default               volta a seguir o padrão do sistema
  earendel -conf -word " Jarvis"              troca a palavra de ativação (wake-word)
  earendel -conf -word                       mostra a palavra atual
  earendel -conf -setup                      instala/ativa tudo sozinho (ydotool etc)
  earendel --toggle                         faz UMA ditada agora (p/ atalho da DE)
  earendel --status                         mostra config (mic, atalho, modelos)
  earendel -h | --help                      esta ajuda

Exemplos:
  earendel -conf -mic
  earendel -conf -mic "USB Composite"
  earendel -conf -key "ctrl+alt+e"
  earendel -conf -word "jarvis"   (ou "jarvis, computador" p/ várias)

Notas:
- O atalho é DO APP, não do sistema (não mexe em GNOME/KDE).
- No Wayland, se o atalho do app não disparar, ligue a tecla do sistema
  para o comando `earendel --toggle` apontando p/ esta pasta.
- Tudo (venv, modelos, config) fica DENTRO desta pasta. Nada vai p/ o sistema,
  exceto o que scripts/install.sh fizer de forma registrada.
""".strip()


def _normalize_argv(argv: list[str]) -> list[str]:
    """Aceita 1 ou 2 traços p/ opções longas: -conf -> --conf, -key -> --key, etc."""
    mapping = {
        "-conf": "--conf", "-key": "--key", "-mic": "--mic",
        "-word": "--word", "-word-en": "--word", "-setup": "--setup",
        "-h": "--help", "-help": "--help",
        "-toggle": "--toggle", "-status": "--status",
        "-version": "--version", "-v": "--version",
        "-model": "--model", "-lang": "--lang",
    }
    out = []
    for a in argv:
        if a in mapping:
            out.append(mapping[a])
            continue
        # gruda tipo -key"ctrl+alt+e" ou -mic"usb"
        for single, double in mapping.items():
            if a.startswith(single) and len(a) > len(single) and not a.startswith("--"):
                rest = a[len(single):].lstrip("= ")
                out.append(double)
                if rest:
                    out.append(rest)
                break
        else:
            out.append(a)
    return out


def _pop_value(args: list[str], *names: str) -> str | None:
    for n in names:
        if n in args:
            i = args.index(n)
            if i + 1 < len(args) and not args[i + 1].startswith("--"):
                return args[i + 1]
            return ""  # flag presente sem valor
    return None


def main(argv: list[str] | None = None) -> int:
    raw = list(sys.argv[1:] if argv is None else argv)
    args = _normalize_argv(raw)

    if not args:
        from . import daemon as daemonmod
        daemonmod.run_daemon()
        return 0

    if "--help" in args or "-h" in raw:
        print(HELP)
        return 0

    if "--version" in args:
        from . import __version__
        print(f"earendel {__version__}")
        return 0

    if "--status" in args:
        cfg = cfgmod.load()
        mic = cfg.get("mic")
        print(f"config: {cfgmod.config_path()}")
        print(f"models: {cfgmod.models_dir()}")
        print(f"mic: {mic!r} ({cfg.get('mic_name') or 'sistema (padrão)'})")
        print(f"key (atalho do app): {cfg.get('key')!r}")
        print(f"wake_model: {cfg.get('wake_model')}  stt_model: {cfg.get('stt_model')}  lang: {cfg.get('language')}")
        print(f"idle_unload_s: {cfg.get('idle_unload_s')} (0 = sempre carregado)")
        return 0

    if "--toggle" in args:
        from . import daemon as daemonmod
        cfg = cfgmod.load()
        daemonmod.dictate_once(cfg)
        return 0

    if "--conf" in args:
        # --- setup guiado (cuida de tudo sozinho) ---
        if "--setup" in args:
            from . import setup as setupmod
            auto = any(a.lower() in ("auto", "yes", "-y", "--yes")
                       for a in args if a != "--setup" and a != "--conf")
            return setupmod.run_setup(auto=auto)
        # --- atalho do APP ---
        if "--key" in args:
            val = _pop_value(args, "--key")
            if val is None or val == "":
                cur = cfgmod.load().get("key")
                print(f"atalho atual do app: {cur!r}")
                print('defina com: earendel -conf -key "ctrl+alt+e"')
                return 0
            combo = hotkeymod.normalize_combo(val.strip().strip('"').strip("'"))
            cfgmod.save({"key": combo})
            print(f"atalho do app salvo: {combo}")
            print("ele vale enquanto `earendel` estiver rodando (é do app, não do sistema).")
            if cfgmod.maybe_reload_service():
                print("service recarregado: já valendo.")
            return 0
        # --- palavra de ativação (wake-word, vale p/ pt+en) ---
        if "--word" in args:
            val = _pop_value(args, "--word")
            if val is None or val == "":
                cur = cfgmod.load().get("wake_words")
                print(f"wake-word atual: {cur or 'nenhuma (usuário escolhe)'}")
                print('defina com: earendel -conf -word "malu" | remover: -conf -word off')
                return 0
            raw = val.strip().strip('"').strip("'")
            if raw.lower() in ("off", "none", "-", "nenhuma"):
                cfgmod.save({"wake_words": []})
                print("wake-word removida (sem gatilho de voz).")
                if cfgmod.maybe_reload_service():
                    print("service recarregado: já valendo.")
                else:
                    print("rode ./scripts/reload.sh p/ aplicar.")
                return 0
            words = [w.strip().lower() for w in raw.split(",")]
            words = [w for w in words if w]
            if not words:
                print("informe ao menos uma palavra. Ex: earendel -conf -word \"malu\"")
                return 1
            if any(len(w) < 4 for w in words):
                print("aviso: palavra curta (<4 letras) dispara à toa com facilidade.")
            from . import wake_vosk
            for w in words:
                base = w.replace("-", " ")
                ok_pt = wake_vosk.in_vocab(base, "pt")
                ok_en = wake_vosk.in_vocab(base, "en")
                if ok_pt is False and ok_en is False:
                    print(f"AVISO: '{w}' fora do vocabulário (pt e en) — "
                          f"NUNCA vai ativar. Use palavra do dicionário.")
                elif ok_pt is None and ok_en is None:
                    print(f"(não deu p/ validar '{w}' agora)")
            cfgmod.save({"wake_words": words})
            print(f"wake-word salvo: {words}")
            if cfgmod.maybe_reload_service():
                print("service recarregado: já valendo.")
            else:
                print("rode ./scripts/reload.sh p/ aplicar no daemon em execução.")
            return 0
        # --- microfone ---
        if "--mic" in args:
            val = _pop_value(args, "--mic")
            from . import audio as audiomod
            if val is None or val == "":
                # sem nome: lista (pedido original)
                try:
                    print(audiomod.print_mics())
                except Exception as e:
                    print(f"falha ao listar mics: {e}")
                    print("rode scripts/install.sh (sounddevice fica no .venv isolado).")
                    return 1
                return 0
            name = val.strip().strip('"').strip("'")
            if name.lower() in ("default", "sistema", "auto", "padrao", "padrão"):
                cfgmod.save({"mic": None, "mic_name": "sistema (padrão)"})
                print("mic: seguindo o padrão do sistema.")
                print("(troque na DE à vontade; o daemon acompanha sozinho)")
                if cfgmod.maybe_reload_service():
                    print("service recarregado: já valendo.")
                return 0
            try:
                m = audiomod.resolve_mic(name)
            except Exception as e:
                print(f"falha ao listar mics: {e}")
                return 1
            if not m:
                print(f"mic '{name}' não encontrado. Disponíveis:")
                try:
                    print(audiomod.print_mics())
                except Exception:
                    pass
                return 1
            cfgmod.save({"mic": m["index"], "mic_name": m["name"]})
            print(f"mic salvo: [{m['index']}] {m['name']}")
            if cfgmod.maybe_reload_service():
                print("service recarregado: já valendo.")
            return 0
        # --- modelo / idioma (extras) ---
        if "--model" in args:
            val = (_pop_value(args, "--model") or "").strip()
            if not val:
                print(f"stt_model atual: {cfgmod.load().get('stt_model')}")
                return 0
            cfgmod.save({"stt_model": val})
            print(f"stt_model salvo: {val} (tiny/base/small/medium)")
            if cfgmod.maybe_reload_service():
                print("service recarregado: já valendo.")
            return 0
        if "--lang" in args:
            val = (_pop_value(args, "--lang") or "").strip().lower()
            lang = None if val in ("", "auto") else val
            cfgmod.save({"language": lang})
            print(f"idioma salvo: {lang or 'auto (pt/en)'}")
            if cfgmod.maybe_reload_service():
                print("service recarregado: já valendo.")
            return 0
        print(HELP)
        return 0

    print(HELP)
    print(f"\nopção desconhecida: {' '.join(raw)}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
