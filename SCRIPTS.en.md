# Earendel scripts — what each one is (English)

> Golden rule: run what is MEANT TO RUN, don't edit anything inside
> `src/` or `.venv/`. Configure via commands (`earendel -conf ...`),
> never by hand-editing files.

## Safe to run (made for you)

| Script | What it does | Effects outside the folder? |
|---|---|---|
| `./scripts/install.sh` | Installs everything: `.venv`, models, symlink, system packages (asks), service | Yes, but asks first and logs all in `.test-install.log` |
| `./scripts/uninstall.sh` | Removes everything install did (reads the log) | Undoes the above; asks before wiping `.venv/models` |
| `./scripts/reload.sh` | Restarts the daemon to apply new code/config | No (only restarts the local service) |
| `./scripts/test-word.sh [phrase]` | Dictation test: records 6s and shows what the model heard | No |
| `./scripts/test-wake.sh` | Porter test: records 8s and tells if it would trigger | No |
| `./earendel -conf -setup` | The app installs/enables missing pieces itself (packages, ydotool, word) | Yes, asking first |

## Do not touch (app-managed)

| File/folder | Why not |
|---|---|
| `src/` | Source code. Changes need `reload.sh` and can break everything |
| `.venv/` (470MB) | Isolated Python. Deleting = reinstall via `install.sh` |
| `models/` (580MB) | Bundled models. Deleting = the app points you to `install.sh` |
| `config.json` | Live config. Use `earendel -conf -mic/-key/-word` (self-applying) |
| `rtf.json` | App speed calibration. Safe to ignore |
| `.test-install.log` | Proof of what was installed. Without it uninstall can't clean up |

## Typical flows (copy & paste)

```bash
# install from scratch on another machine
./scripts/install.sh          # venv + models + symlink + service
earendel -conf -setup         # word + typer (asks everything)

# change the word (self-applying, no manual reload)
earendel -conf -word "malu, hey computer"

# see what is active
earendel --status              # mic, hotkey, word, models
earendel -conf -word           # just the word

# remove everything
./scripts/uninstall.sh        # asks before each part
```

## Quick questions

- **Deleted `config.json` by accident?** Run `./scripts/install.sh`; it
  recreates defaults (no word; pick again with `-conf -word`).
- **Switched system microphone?** Nothing to do: the app follows the default
  alone (unless pinned with `-conf -mic "name"`).
- **Switched distro?** Run `install.sh` again; it detects the new one.

## Accepted limitations (not bugs)

1. **In-app hotkey on Wayland**: the system may not deliver the key; bind
   your DE key to `earendel --toggle` instead.
2. **Wake word**: only pt/en dictionary words (the porter warns immediately;
   `earendel -conf -word` validates).
3. **Terminal**: auto-paste is Ctrl+V; in terminals use Ctrl+Shift+V
   (the right text is always in the clipboard).
4. **Autostart**: assumes systemd (`systemctl --user`). Without it, run
   `./earendel` manually.
5. **Distros**: installer covers arch/debian/fedora/suse/alpine; elsewhere
   it tells you what to install by hand.
6. **GPU**: inference is CPU-only (no AMD support in this stack); VRAM unused.
