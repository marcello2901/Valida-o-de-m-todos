# Instalação, hook e diagnóstico do RTK

Projeto: <https://github.com/rtk-ai/rtk> (Apache-2.0). Binário Rust único, sem runtime.
Versão de referência desta skill: **0.46.0** (release), master em 0.42.x — o README do
projeto ainda cita `0.28.2` em alguns trechos; ignore, use `rtk --version`.

## Antes de instalar: colisão de nome

Dois projetos diferentes se chamam `rtk`:

| Projeto | O que é |
|---|---|
| `rtk-ai/rtk` | **Rust Token Killer** — este aqui, proxy de compressão |
| `reachingforthejack/rtk` | Rust Type Kit — gera tipos Rust, nada a ver |

`cargo install rtk` pode trazer o errado. Teste definitivo: **`rtk gain`** existe só no
Rust Token Killer (sai 0 mesmo sem histórico). Se `rtk --version` funciona e `rtk gain`
não, desinstale (`cargo uninstall rtk`) antes de reinstalar.

## Métodos de instalação

Em ordem de preferência — do mais auditável ao menos:

```bash
# 1. Homebrew (macOS/Linux) — recomendado
brew install rtk-ai/tap/rtk
#    (existe também um `brew install rtk`; use o tap explícito para não cair no homônimo)

# 2. Binário pré-compilado do release, verificável antes de rodar
#    Linux x86_64: rtk-x86_64-unknown-linux-musl.tar.gz
#    Linux ARM:    rtk-aarch64-unknown-linux-gnu.tar.gz
#    macOS:        rtk-{x86_64,aarch64}-apple-darwin.tar.gz
#    Windows:      rtk-x86_64-pc-windows-msvc.zip
curl -fsSL -o rtk.tar.gz \
  https://github.com/rtk-ai/rtk/releases/latest/download/rtk-x86_64-unknown-linux-musl.tar.gz
tar -xzf rtk.tar.gz -C ~/.local/bin

# 3. Cargo, com URL git explícita (evita a colisão de nome)
cargo install --git https://github.com/rtk-ai/rtk --branch master rtk

# 4. Script de instalação — baixa e executa código remoto sem revisão
curl -fsSL https://raw.githubusercontent.com/rtk-ai/rtk/refs/heads/master/install.sh | sh
```

O método 4 é o divulgado no README, mas `curl | sh` executa, com o seu usuário, o que
estiver naquela URL **no momento da execução**. Se for usá-lo, baixe primeiro
(`curl -fsSL ... -o install.sh`), leia, depois rode. Os métodos 1–3 dão o mesmo resultado
com uma superfície de confiança menor.

Instalação em `~/.local/bin` exige o diretório no PATH:

```bash
echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.bashrc   # ou ~/.zshrc
```

Verificação final:

```bash
rtk --version   # rtk x.y.z
rtk gain        # painel (ou "No tracking data yet." — também é sucesso)
```

## Hook de auto-rewrite (Claude Code)

O hook `PreToolUse` reescreve todo comando Bash antes da execução
(`git status` → `rtk git status`). É o modo mais eficaz: cobre 100% das chamadas, em
todas as conversas e subagentes, sem gastar contexto por comando.

```bash
rtk init -g                  # hook + RTK.md + patch em ~/.claude/settings.json
rtk init -g --auto-patch     # sem prompt (CI)
rtk init -g --hook-only      # só o hook, sem RTK.md
rtk init -g --no-patch       # não toca no settings.json, imprime instruções manuais
rtk init --show              # estado atual
rtk init -g --uninstall      # remove tudo
```

Depois de instalar, **reinicie o Claude Code**.

O que ele mexe, fora deste repositório:

- `~/.claude/settings.json` — adiciona a entrada de hook `PreToolUse`
- `~/.claude/RTK.md` e a referência `@RTK.md` no `~/.claude/CLAUDE.md`
- `~/.config/rtk/config.toml` — configuração do RTK
- `~/.local/share/rtk/` — SQLite de rastreio e `.device_salt`

Por ser configuração global do usuário, isso não deve ser feito por iniciativa do
assistente: peça confirmação.

Escopo do hook: só a ferramenta **Bash**. `Read`, `Grep` e `Glob` do Claude Code não
passam por ele. Para ter filtro nesses fluxos, use comandos de shell
(`cat`/`head`, `rg`, `find`) ou chame `rtk read|grep|find` diretamente.

Outros agentes suportados (16 no total): `rtk init -g --gemini`, `--codex`,
`--copilot`, `--opencode`, `--agent cursor|windsurf|cline|kilocode|antigravity|kimi|pi|hermes|droid|vibe`.

## Configuração

`~/.config/rtk/config.toml` (macOS: `~/Library/Application Support/rtk/config.toml`):

```toml
[hooks]
exclude_commands = ["curl", "playwright"]   # não reescrever estes

[tee]
enabled = true        # salva a saída bruta quando o comando falha
mode = "failures"     # "failures" | "always" | "never"
```

Manter `[tee]` ligado é o que torna a filtragem recuperável: quando um teste quebra e o
resumo não basta, a saída completa está em disco e o caminho aparece na mensagem.

## Telemetria

Desligada por padrão; exige consentimento explícito no `rtk init` ou
`rtk telemetry enable`. Quando ligada, envia um POST HTTPS por dia com: hash anônimo de
dispositivo (SHA-256 de um salt local), versão/SO/arquitetura/método de instalação,
volume de comandos, nomes dos 5 comandos mais usados, tokens estimados economizados.
Não envia conteúdo de comandos nem caminhos.
Gerenciar: `rtk telemetry status | enable | disable | forget`.

O rastreio local (`rtk gain`) é independente e continua funcionando com a telemetria
desligada.

## Problemas comuns

| Sintoma | Causa provável |
|---|---|
| `rtk: command not found` | `~/.local/bin` fora do PATH, ou shell não recarregado |
| `rtk --version` ok, `rtk gain` falha | Pacote errado (Rust Type Kit) — ver topo |
| Hook não reescreve nada | Claude Code não reiniciado, ou `rtk init --show` acusa hook ausente |
| `Binary 'rg' not found on PATH` | Alguns filtros dependem de ripgrep — instale `rg` |
| Comando reescrito atrapalhando | `[hooks] exclude_commands` no config.toml |
| Saída filtrada escondeu o erro | Rode o comando cru, ou recupere o arquivo salvo pelo `[tee]` |

Documentação: <https://www.rtk-ai.app/guide/troubleshooting>
