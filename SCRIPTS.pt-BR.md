# Scripts do Earendel — o que é cada um (pt-BR)

> Regra de ouro: rode o que é PARA RODAR, não edite nada dentro de
> `src/` e `.venv/`. Configuração se faz por comando (`earendel -conf ...`),
> nunca editando arquivo na mão.

## Pode rodar (feitos para você)

| Script | O que faz | Efeito fora da pasta? |
|---|---|---|
| `./scripts/install.sh` | Instala tudo: `.venv`, modelos, symlink, pacotes do sistema (pergunta), service | Sim, mas pergunta antes e registra tudo em `.test-install.log` |
| `./scripts/uninstall.sh` | Remove tudo que o install fez (lê o log) | Desfaz o de cima; pergunta antes de apagar `.venv/models` |
| `./scripts/reload.sh` | Reinicia o daemon p/ aplicar código/config novo | Não (só reinicia o service local) |
| `./scripts/test-word.sh [frase]` | Teste de ditado: grava 6s e mostra o que o modelo ouviu | Não |
| `./scripts/test-wake.sh` | Teste do porteiro: grava 8s e diz se ativaria | Não |
| `./earendel -conf -setup` | O app instala/ativa sozinho o que falta (pacotes, ydotool, palavra) | Sim, perguntando antes |

## Não mexa (gerenciados pelo app)

| Arquivo/pasta | Por quê não mexer |
|---|---|
| `src/` | Código-fonte. Mudança aqui precisa de `reload.sh` e pode quebrar tudo |
| `.venv/` | Python isolado (470MB). Apagar = reinstalar via `install.sh` |
| `models/` (580MB) | Modelos integrados. Apagar = o app referencia `install.sh` no erro |
| `config.json` | Config viva. Use `earendel -conf -mic/-key/-word` (aplica sozinho) |
| `rtf.json` | Calibração de velocidade do app. Apaga sozinho se corromper |
| `.test-install.log` | Prova do que foi instalado. Sem ele o uninstall não sabe o que tirar |

## Fluxos típicos (copie e cole)

```bash
# instalar do zero em outra máquina
./scripts/install.sh          # venv + modelos + symlink + service
earendel -conf -setup         # palavra + digitador (pergunta tudo)

# trocar a palavra (aplica sozinho, sem reload manual)
earendel -conf -word "malu, hey computer"

# ver o que está ativo
earendel --status              # mic, atalho, palavra, modelos
earendel -conf -word           # só a palavra

# remover tudo
./scripts/uninstall.sh        # pergunta antes de cada parte
```

## Perguntas rápidas

- **Apaguei `config.json` sem querer?** Rode `./scripts/install.sh` que ele
  recria o padrão (sem palavra; escolha de novo com `-conf -word`).
- **Mudei de microfone no sistema?** Nada a fazer: o app segue o padrão
  sozinho (a menos que tenha fixado com `-conf -mic "nome"`).
- **Troquei de distro?** Rode `install.sh` de novo; ele detecta a nova.

## Limitações assumidas (não são bugs)

1. **Atalho do app no Wayland**: o sistema pode não entregar a tecla; ligue sua
   tecla na DE para `earendel --toggle`.
2. **Palavra de ativação**: só palavra do dicionário pt/en (o porteiro avisa
   na hora se não for; `earendel -conf -word` valida).
3. **Terminal**: colar automático é Ctrl+V; no terminal use Ctrl+Shift+V
   (o texto certo está sempre no clipboard).
4. **Autostart**: assume systemd (`systemctl --user`). Sem systemd, rode
   `./earendel` manual.
5. **Distros**: instalador cobre arch/debian/fedora/suse/alpine; fora
   dessas, ele diz o que instalar na mão.
6. **GPU**: inferência é CPU (stack sem suporte à sua AMD); VRAM não é usada.
