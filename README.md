# Earendel — wake-word + STT offline (pt-BR/en-US)

CLI `earendel`: fica ouvindo **sua palavra de ativação**, abre popup wave
inferior-central, transcreve (Faster-Whisper, 100% offline) e **digita onde
o foco está** + clipboard.

## Isolamento (regra do projeto)

- `src/`, `.venv/`, `models/`, `config.json` ficam **DENTRO desta pasta**.
- Nenhum `pip install` vai para o sistema — só para `.venv`.
- Teste no PC de forma controlada: `scripts/install.sh` (registra tudo em
  `.test-install.log`) e `scripts/uninstall.sh` remove tudo.

## Uso

```bash
./scripts/install.sh               # 1ª vez: .venv + modelos + symlink + service
./earendel -conf -setup            # palavra de ativação + digitador (pergunta tudo)
./earendel --help
./earendel -conf -mic              # lista microfones (sem nome = lista)
./earendel -conf -mic "USB"        # fixa um mic
./earendel -conf -mic default      # volta a seguir o padrão do sistema
./earendel -conf -key "ctrl+alt+e" # atalho DO APP (só vale com ele rodando)
./earendel -conf -word "malu"      # palavra de ativação (vale pt+en, auto-aplica)
./earendel --toggle                # UMA ditada avulsa (p/ tecla da DE)
./earendel --status
./earendel                         # daemon: escuta sempre ativo
```

Toda alteração de `-conf` **aplica sozinha** (reinicia o service);
sem service, ele pede `./scripts/reload.sh`.

## Palavra de ativação

- Sem palavra padrão: você escolhe na setup ou com `-conf -word`.
- Vale para os dois porteiros (pt+en) ao mesmo tempo; várias separadas
  por vírgula (`"malu, hey computer"`).
- Dispara só com a palavra **sozinha** (match exato, sem tolerância).
- Só vale palavra do dicionário pt/en — o comando **avisa na hora**
  se nunca ativaria. `off` remove.

## Modelos (`small` + porteiros pt/en, ~580MB)

- Vêm integrados em `./models` via `install.sh` — em uso, **nada baixa
  nada** (trava offline; faltando, o erro manda rodar o install).
- Porteiros (Vosk pt+en): **sempre residentes** (~150–200MB, ~8% CPU).
- Transcritor (`small`): carrega na ditada, **descarrega após 3 min sem
  uso** (`idle_unload_s`; `0` = sempre carregado).

## Atalho: do app, não do sistema

- `-conf -key` salva em `config.json` e o daemon ouve via pynput **enquanto roda**.
- Wayland pode bloquear hotkey global: nesse caso, na sua DE (KDE: Configurações →
  Atalhos → Adicionar comando) aponte a tecla para `/caminho/earendel --toggle`.

## Popup wave

- Tk translúcido inferior-central no monitor primário (qualquer DE) → notify sem Tk.
  Barras reagem à sua voz (FFT do mic); transcrição mostra %; texto longo vira `...`.

## Digitar onde está o foco

- ASCII digita tecla por tecla; com acento cola em fatias (animação equivalente).
- Clipboard sempre como rede de segurança (Klipper no KDE, `wl-copy` fora).
- Sem digitador funcionando, o popup avisa `[copiado — cole com Ctrl+V]`
  (no terminal, cole com Ctrl+Shift+V).
- `ydotool` é oferecido pelo `-conf -setup` (opcional, registrado no log).

## Remover / recarregar

```bash
./scripts/uninstall.sh  # remove tudo (pergunta cada parte)
./scripts/reload.sh     # só p/ mudança de CÓDIGO (config auto-aplica)
```
