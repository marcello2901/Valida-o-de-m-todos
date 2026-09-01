---
name: rtk
description: >-
  Comprime a saída de comandos de terminal antes que ela entre no contexto, usando o
  proxy RTK (Rust Token Killer, rtk-ai/rtk). Use ao rodar comandos verbosos — pytest,
  ruff, mypy, pip/uv, cargo, jest, go test, builds, linters, git status/log/diff,
  ls/find/grep, docker/kubectl — e quando o usuário pedir para instalar, configurar,
  verificar ou diagnosticar o RTK (rtk init, rtk gain, hook de auto-rewrite).
allowed-tools: Bash
---

# RTK — proxy de compressão de saída de comandos

`rtk <comando>` executa o comando real e devolve uma versão filtrada da saída.
O ganho é medido em **bytes de saída do bash** (60–99% conforme o comando), o que
**não** é o mesmo que 60–99% de redução de custo: a saída do bash é apenas um dos
contribuintes dos tokens de entrada, e os tokens de entrada são apenas parte da conta.
O RTK não embarca tokenizer — ele estima tokens como `bytes / 4`, então as
**porcentagens são confiáveis, os números absolutos são aproximados**.

## 1. Pré-voo (uma vez por sessão, antes do primeiro `rtk`)

```bash
if command -v rtk >/dev/null 2>&1 && rtk gain >/dev/null 2>&1; then
  echo "rtk disponivel: $(rtk --version)"
else
  echo "rtk indisponivel"
fi
```

- **`rtk disponivel`** → siga a seção 2.
- **`rtk indisponivel`** → **não** prefixe nada com `rtk`; rode os comandos crus e siga
  normalmente. Só instale se o usuário pedir (`references/instalacao.md`); nunca instale
  binário por conta própria no meio de outra tarefa.
- `rtk --version` funciona mas `rtk gain` falha → está instalado o **pacote errado**
  (`reachingforthejack/rtk`, "Rust Type Kit", homônimo no crates.io). Trate como
  indisponível e avise o usuário — ver `references/instalacao.md`.

## 2. Como usar

Prefixe o comando com `rtk`. Os argumentos nativos passam adiante.

| Em vez de | Use | Redução típica |
|---|---|---|
| `pytest` | `rtk pytest` | 80–90% (só falhas) |
| `ruff check .` | `rtk ruff check .` | ~75% (agrupado por regra/arquivo) |
| `mypy .` | `rtk mypy .` | ~75% (agrupado por arquivo) |
| `pip install -r requirements.txt` | `rtk pip install -r requirements.txt` | ~70% (sem barras de progresso) |
| `uv run pytest` | `rtk uv run pytest` | 80–90% |
| `git status` / `git log` / `git diff` | `rtk git status` / `rtk git log -n 10` / `rtk git diff` | 70–93% |
| `ls -la` / `find` / `grep -r` | `rtk ls .` / `rtk find "*.py" .` / `rtk grep "padrao" .` | 70–80% |
| `cargo test` / `cargo clippy` | `rtk cargo test` / `rtk cargo clippy` | 80–90% |
| `npm test` / `jest` / `vitest` / `tsc` | `rtk test npm test` / `rtk jest` / `rtk vitest` / `rtk tsc` | 75–99% |
| `go test ./...` | `rtk go test ./...` | 80–90% |
| `docker ps` / `kubectl get pods` | `rtk docker ps` / `rtk kubectl pods` | 60–65% |
| qualquer comando verboso | `rtk test <cmd>` (só falhas) ou `rtk err <cmd>` (só erros) | até 90% |

Catálogo completo (100+ comandos, AWS, PHP, Ruby, Java/Maven, Scala, GitLab, psql):
`references/comandos.md`.

Flag global útil: `--ultra-compact` (ícones ASCII, formato inline). O `-u` citado em
READMEs antigos **não existe** na CLI atual — use o nome longo.

## 3. Quando NÃO usar RTK

Isto é filtragem com perda. O RTK decide o que você **não** vai ver. Rode cru quando:

- **Você precisa da saída exata**: stack trace completo, mensagem literal de erro,
  diff byte a byte, output que será parseado por outro script.
- **A falha está no que foi filtrado**: se `rtk pytest` mostra "2 falhas" e o motivo não
  ficou claro, **rode `pytest` cru** naquele teste em vez de adivinhar.
- **Comandos que dependem de confirmação detalhada**: `git push` vira `ok main`,
  `git commit` vira `ok abc1234`. Se o resultado da operação importa (rejeição de push,
  conflito de merge, saída de deploy), rode cru ou confira o estado depois.
- **Comandos interativos, TTY, watchers ou streaming** (`pytest -f`, `npm run dev`,
  `docker logs -f`): o filtro pressupõe saída finita.
- **`rtk read` nunca é base para edição.** `rtk read -l aggressive` remove corpos de
  função e devolve só assinaturas. Para editar um arquivo, leia com a ferramenta Read
  (conteúdo íntegro) — usar a visão comprimida leva a edições em cima de código que
  você não viu.

Mitigação embutida: por padrão o RTK salva a saída bruta em disco quando o comando
falha (`[tee] mode = "failures"` em `~/.config/rtk/config.toml`). A mensagem filtrada
indica o caminho do arquivo.

## 4. Diagnóstico

```bash
rtk --version          # versão instalada
rtk gain               # painel de economia acumulada
rtk gain -p            # só o projeto atual (diretório corrente)
rtk gain --graph       # gráfico ASCII dos últimos 30 dias
rtk gain --failures    # comandos em que o filtro falhou e caiu para execução crua
rtk discover           # comandos rodados crus que teriam economizado
rtk init --show        # estado do hook / RTK.md / settings.json
```

## 5. Hook de auto-rewrite (opcional, mais eficaz que esta skill)

Esta skill só age quando é carregada. O modo recomendado pelo próprio RTK é o hook
`PreToolUse`, que reescreve **todo** comando Bash antes da execução, em toda conversa e
todo subagente, sem custo de contexto por comando:

```bash
rtk init -g            # instala hook + RTK.md e altera ~/.claude/settings.json
rtk init --show        # confere
rtk init -g --uninstall  # remove
```

Isto **altera a configuração global do Claude Code** do usuário, fora deste repositório.
Só execute a pedido explícito. Detalhes, escopo e desinstalação: `references/instalacao.md`.

Limite conhecido do hook: ele só intercepta chamadas da ferramenta **Bash**. `Read`,
`Grep` e `Glob` do Claude Code não passam por ele e não são reescritos.
