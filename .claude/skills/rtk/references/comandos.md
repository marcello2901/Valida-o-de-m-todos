# Catálogo de comandos RTK

Subcomandos confirmados em `rtk --help` na versão **0.46.0**. A CLI pode ganhar
subcomandos novos — em caso de dúvida, rode `rtk --help` ou `rtk <sub> --help`.

Qualquer subcomando repassa as flags nativas do programa real
(`rtk pytest -k test_lod -q`, `rtk git log --oneline -n 5`).

## Arquivos e busca

| Comando | Efeito |
|---|---|
| `rtk ls .` | Árvore compacta, diretórios agrupados, tamanhos legíveis |
| `rtk tree` | Árvore de diretórios filtrada |
| `rtk read arq.py` | Leitura com filtro (`-l none` padrão, `minimal`, `aggressive`) |
| `rtk read arq.py -m 200` | Limita linhas (`--tail-lines N` mantém só o fim) |
| `rtk smart arq.py` | Resumo heurístico de 2 linhas |
| `rtk find "*.py" .` | `find` com saída em árvore (aceita `-name`, `-type`) |
| `rtk grep "padrao" .` | Linhas truncadas, agrupadas por arquivo |
| `rtk rg "padrao" .` | Idem, executando ripgrep nativamente |
| `rtk diff a.py b.py` | Diff condensado (sai 1 se diferem) |
| `rtk wc arq.py` | Contagens sem padding |
| `rtk json config.json` | Estrutura sem valores (`--keys-only`) |
| `rtk log app.log` | Log deduplicado |

> `rtk read` **não** substitui a ferramenta Read para editar arquivos. Ver seção 3 do SKILL.md.

## Git, GitHub, GitLab

| Comando | Efeito |
|---|---|
| `rtk git status` | Formato stat compacto, agrupado por estado |
| `rtk git log -n 10` | Hash + autor + assunto |
| `rtk git diff` | Contexto reduzido, cabeçalhos removidos |
| `rtk git add` / `commit` / `push` / `pull` | Confirmação de uma linha (`ok`, `ok abc1234`, `ok main`) |
| `rtk gh pr list` / `pr view 42` / `issue list` / `run list` | Listagens compactas, sem ASCII art |
| `rtk glab ...` | GitLab CLI compacto |
| `rtk gt log` / `gt status` | Graphite (PRs empilhados) |

## Python

| Comando | Efeito |
|---|---|
| `rtk pytest` | Só falhas, traceback aparado (80–90%) |
| `rtk ruff check .` | Violações agrupadas por regra/arquivo (~75%) |
| `rtk mypy .` | Erros de tipo agrupados por arquivo (~75%) |
| `rtk pip install ...` / `pip list` / `pip outdated` | Sem barras de progresso; detecta uv |
| `rtk uv run pytest` | Preserva o ambiente gerenciado pelo uv |
| `rtk format` | Checador universal de formatação (prettier, black, ruff format) |

## JavaScript / TypeScript

`rtk jest`, `rtk vitest`, `rtk playwright test`, `rtk tsc`, `rtk lint` (ESLint),
`rtk prettier --check .`, `rtk next build`, `rtk npm run <script>`, `rtk npx <tool>`
(roteia tsc/eslint/prisma para os filtros específicos), `rtk pnpm list`,
`rtk prisma generate`.

## Rust, Go, Ruby, PHP, JVM, .NET

- Rust: `rtk cargo build|test|clippy|check`
- Go: `rtk go test ./...`, `rtk golangci-lint run`
- Ruby: `rtk rspec`, `rtk rubocop`, `rtk rake test`, `rtk bundle install`
- PHP: `rtk php`, `rtk phpunit`, `rtk phpstan`, `rtk pest`, `rtk paratest`, `rtk pint`, `rtk ecs`
- JVM: `rtk mvn verify`, `rtk gradlew build`, `rtk sbt test|compile|run`
- .NET: `rtk dotnet build|test|restore|format`

## Infra, dados, rede

`rtk docker ps|images|logs|compose ps`, `rtk kubectl pods|logs|services`,
`rtk oc get pods` (OpenShift), `rtk aws <serviço> <ação>` (força JSON e comprime;
`lambda list-functions` e `iam list-roles` removem segredos e policies),
`rtk psql` (remove bordas de tabela), `rtk curl <url>` (trunca e salva a saída completa),
`rtk wget <url>`, `rtk env -f AWS`, `rtk deps`.

## Genéricos (funcionam com qualquer comando)

| Comando | Efeito |
|---|---|
| `rtk test <cmd>` | Wrapper de testes: só falhas (~90%) |
| `rtk err <cmd>` | Só erros e avisos |
| `rtk summary <cmd>` | Resumo heurístico |
| `rtk pipe` | Lê stdin, aplica filtro, imprime (`cmd \| rtk pipe`) |
| `rtk proxy <cmd>` | Passthrough cru **com** rastreio de uso |
| `rtk run "<cmd>"` | Executa via `sh -c`, cru, **sem** filtro e **sem** rastreio |

## Analytics

| Comando | Efeito |
|---|---|
| `rtk gain` | Resumo de economia |
| `rtk gain --graph` / `--history` / `--daily` | Gráfico ASCII / histórico / dia a dia |
| `rtk gain -p` | Restringe as estatísticas ao projeto atual |
| `rtk gain --failures` | Comandos em que o filtro falhou e caiu para execução crua |
| `rtk gain --all --format json` | Exportação JSON (`--format text\|json\|csv`) |
| `rtk discover` | Comandos rodados crus que teriam economizado (`--all --since 7`) |
| `rtk session` | Adoção do RTK nas sessões recentes do Claude Code |
| `rtk cc-economics` | Cruza gasto (ccusage) com economia do RTK |

Os dados ficam num SQLite local (`~/.local/share/rtk/`). São locais; não confundir com
telemetria (opt-in, ver `instalacao.md`).

## Flags globais

| Flag | Efeito |
|---|---|
| `--ultra-compact` | Ícones ASCII, formato inline (compressão extra) |
| `-v` / `-vv` / `-vvv` | Verbosidade — só é reconhecida **antes** do subcomando |
| `--skip-env` | Define `SKIP_ENV_VALIDATION=1` para processos filhos (Next.js, tsc, lint, prisma) |

## Filtros customizados do projeto

`.rtk/filters.toml` na raiz do repositório sobrepõe filtros globais e nativos:

```toml
schema_version = 1

[filters.meu-tool]
description = "Compacta a saída do meu-tool"
match_command = "^meu-tool\\s+build"
strip_ansi = true
strip_lines_matching = ["^\\s*$", "^Downloading"]
max_lines = 30
on_empty = "meu-tool: ok"
```

Filtros locais precisam ser confiados explicitamente: `rtk trust` (revogar: `rtk untrust`),
e `rtk verify` roda os testes inline dos filtros. Isso existe porque um `filters.toml`
vindo de um repositório de terceiros é código de terceiros decidindo o que você enxerga —
não confie sem ler.
