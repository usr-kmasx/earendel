# Earendel — wake-word + STT offline (pt-BR/en-US)

CLI `earendel`: fica ouvindo **"earendel"**, abre popup wave inferior-central,
transcreve (Faster-Whisper, 100% offline) e **digita onde o foco está** + clipboard.

## Isolamento (regra do projeto)

- `src/`, `.venv/`, `models/`, `config.json` ficam **DENTRO desta pasta**.
- Nenhum `pip install` vai para o sistema — só para `.venv`.
- Teste no PC de forma controlada: `scripts/install.sh` (registra tudo em
  `.test-install.log`) e `scripts/uninstall.sh` remove tudo.

## Uso

```bash
./scripts/install.sh          # 1ª vez: cria .venv isolado + deps (só aqui dentro)
./earendel --help
./earendel -conf -mic           # lista microfones (sem nome = lista)
./earendel -conf -mic "USB"     # fixa um mic
./earendel -conf -mic default   # volta a seguir o padrão do sistema (padrão)
./earendel -conf -key "ctrl+alt+e"  # atalho GLOBAL DO APP (só vale com ele rodando)
./earendel -conf -word "jarvis"     # troca a palavra de ativação (+ ./scripts/reload.sh)
./earendel -conf -setup             # ele mesmo instala/ativa o que falta (arch/debian/fedora/suse/alpine)
./earendel                      # daemon: wake-word sempre ativo
./earendel --toggle             # UMA ditada avulsa (p/ ligar numa tecla da DE)
./earendel --status
```

Modelos (`small` + porteiros pt/en, ~580MB) vêm integrados em `./models`
via `install.sh` — em uso, **nada baixa nada** (trava offline; faltando,
o erro manda rodar o install).

Modelos ficam **carregados em RAM** após o 1º uso e são **descarregados após
3 min sem uso** (`idle_unload_s` no `config.json`; `0` = sempre carregado).
No daemon, o modelo de wake fica quente enquanto escuta; o de transcrição
descarrega sozinho quando você para de ditar.

## Atalho: do app, não do sistema

- `-conf -key` salva em `config.json` e o daemon ouve via pynput **enquanto roda**.
- Wayland pode bloquear hotkey global: nesse caso, na sua DE (KDE: Configurações →
  Atalhos → Adicionar comando) aponte a tecla para `/caminho/earendel --toggle`.

## Popup wave

- Tk translúcido inferior-central (qualquer DE) → notify sem Tk.
  Barras reagem à sua voz (FFT do mic); texto longo vira `...`.

## Digitar onde está o foco

- Wayland wlroots/Sway: `wtype` · **KDE Wayland: `ydotool`** (KWin não tem
  protocolo de teclado virtual, `wtype` falha) · X11: `ydotool` também.
- Clipboard sempre (`wl-copy`/`xclip`) como rede de segurança.
- Sem digitador funcionando, o popup avisa `[copiado — cole com Ctrl+V]`.
- `ydotool` é oferecido pelo `install.sh` (opcional, registrado no log).

## Remover teste

```bash
./scripts/uninstall.sh
```

## Recarregar após mudanças

```bash
./scripts/reload.sh   # reinicia o service p/ aplicar código/config novo + mostra log
```
