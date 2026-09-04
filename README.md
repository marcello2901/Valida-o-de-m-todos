# Sistema de Validação de Métodos Analíticos

Plataforma web para laboratórios de pequeno e médio porte executarem e
documentarem a validação de seus métodos analíticos, seguindo os procedimentos
descritos nas normas CLSI.

## Estado atual

O que já está pronto e testado:

| Parte | Situação |
|---|---|
| Motor de cálculo (estatística) | ✅ Pronto — 90 testes automatizados |
| Gráficos (regressão, Bland-Altman, Levey-Jennings) | ✅ Pronto — SVG sem dependências |
| Modelos de dados e rastreabilidade | ✅ Pronto — 56 testes automatizados |
| Cadastro de laboratórios e usuários | ✅ Pronto (painel administrativo) |
| Controle dos módulos contratados | ✅ Pronto |
| Quadro de validações e fichas de analito | ✅ Pronto |
| Tela de resultado com as faixas condensáveis | ✅ Pronto |
| Calcular, congelar o veredito e liberar | ✅ Pronto |
| Lançar réplicas e amostras fora do `/admin/` | ⏳ A fazer |
| Assistente de nova validação | ⏳ A fazer |
| Relatório em PDF | ⏳ A fazer |

## Os três módulos comercializáveis

| Módulo | O que avalia | O que **não** consegue avaliar |
|---|---|---|
| **Precisão** | Imprecisão (CV) das réplicas de material de controle | Erro Total e Sigma |
| **Comparabilidade** | Erro sistemático (bias) entre método antigo e novo | Erro Total e Sigma |
| **Precisão + Comparabilidade** | Tudo, incluindo Erro Total e métrica Sigma | — |

A limitação dos módulos isolados não é uma escolha comercial, é uma consequência
da matemática: o Erro Total é `|bias%| + 1,65 × CV%`. Sem os dois insumos
medidos no mesmo estudo, ele não existe. O sistema recusa-se a apresentar um
veredito de validação nesses casos, em vez de estimar a parte que falta.

## Os dois desenhos do estudo de precisão

O laboratório escolhe, e a escolha muda o que o estudo consegue enxergar:

| Desenho | O que mede | O que fica invisível |
|---|---|---|
| **Múltiplas corridas** (5 dias × 5 réplicas) | Repetibilidade **e** precisão intermediária | — |
| **Corrida única** (mínimo 10 réplicas no mesmo dia) | Apenas repetibilidade | Variação entre dias: recalibração, troca de operador, novo frasco de reagente |

A precisão intermediária é sempre maior que a repetibilidade, e é ela que
representa o método na rotina. Um Erro Total calculado a partir de corrida única
**subestima** o erro real — o sistema permite o desenho, mas registra o aviso no
relatório. Esconder essa ressalva seria entregar um número mais bonito do que o
método merece.

## O que a comparabilidade entrega

| Medida | Pergunta que responde |
|---|---|
| Erro sistemático médio | Em média, o método novo lê acima ou abaixo do antigo? |
| Regressão de Deming e Passing-Bablok | Existe erro constante ou proporcional? |
| Regressão linear (r e r²) | A faixa de concentrações estudada foi ampla o bastante? |
| Concordância de Lin (ρc) | Os pontos caem sobre a reta de identidade? |
| Concordância analítica | Quantas amostras ficaram dentro do Erro Total permitido? |
| Concordância clínica | Quantas amostras seriam interpretadas do mesmo jeito pelo médico? |

Duas advertências que o relatório sempre imprime:

**r não mede concordância.** Dois métodos podem ter r = 0,999 com um lendo 30%
acima do outro. Correlação mostra que os pontos seguem *uma* reta, não que seguem
a reta certa. O coeficiente de Lin é que responde isso, porque separa precisão de
acurácia.

**A média esconde amostra fora do limite.** Um método pode ter erro sistemático
médio de 0% e ainda assim ter metade das amostras fora do Erro Total permitido —
basta que os desvios se cancelem. Por isso a concordância analítica conta amostra
a amostra.

A concordância clínica exige o **intervalo de referência** cadastrado no
mensurando. Sem ele o sistema não calcula e diz o porquê, em vez de omitir a
medida silenciosamente.

## Como rodar na sua máquina

Precisa ter o Python 3.11 ou mais novo instalado.

Abra o **PowerShell** (no Windows: botão direito na pasta do projeto →
"Abrir no Terminal") e rode, na ordem:

```powershell
# 1. Instalar as dependências
pip install -r requirements-dev.txt

# 2. Criar o banco de dados local
python manage.py migrate

# 3. Popular com dados de demonstração (opcional, mas recomendado na 1ª vez)
python manage.py dados_exemplo

# 4. Subir o sistema
python manage.py runserver
```

Depois abra <http://localhost:8000/> no navegador. **É esse endereço, sem
`/admin/` no fim** — o `/admin/` mostra os cadastros, não o quadro.

O comando `dados_exemplo` cria o usuário `analista.demo` com a senha
`demonstracao-2026`, quatro validações em estados diferentes e as fichas de
analito correspondentes. Ele se recusa a rodar com `DEBUG=False`, porque cria um
usuário de senha conhecida.

Para entrar com um usuário seu em vez do de demonstração:

```powershell
python manage.py createsuperuser
```

Nada disso precisa de banco de dados instalado: em desenvolvimento o sistema
cria sozinho um arquivo `banco-local.sqlite3`. O PostgreSQL só entra em
produção.

## Como colocar no ar

O passo a passo está em [DEPLOY.md](DEPLOY.md) — escrito para quem nunca
publicou um site, no plano gratuito do Render.

Três limites do plano gratuito que decidem se ele serve para você: o site dorme
depois de 15 minutos sem acesso, o banco de dados é apagado depois de 30 dias, e
os servidores ficam fora do Brasil. Serve para testar e demonstrar. **Não serve
para dado real de paciente** — identificação de amostra é dado pessoal sensível
pela LGPD.

## Como atualizar para a versão mais nova

O código muda no GitHub. A cópia na sua máquina **não se atualiza sozinha** —
baixar de novo é o que traz as mudanças.

**1. Confira qual versão você tem.** Antes de baixar qualquer coisa, olhe se
existe o arquivo `templates\base.html` dentro da pasta do projeto. Se não
existir, sua cópia é antiga.

**2. Baixe a versão nova.** Em <https://github.com/marcello2901/Valida-o-de-m-todos>,
botão verde **Code** → **Download ZIP**. Confira antes, logo acima do botão, se
a branch selecionada é a que você quer:

- `main` — o que já foi revisado e aceito por você;
- `claude/instalar-como-skill-leleth` — o que está em desenvolvimento, ainda
  não aceito.

**3. Extraia num lugar novo.** O Windows costuma criar
`Valida-o-de-m-todos-main (1)` em vez de substituir a pasta antiga — e aí você
roda a antiga sem perceber. Apague ou renomeie a pasta velha antes, ou confirme
o caminho que aparece no PowerShell.

**4. Rode os comandos de novo**, na pasta nova:

```powershell
pip install -r requirements-dev.txt
python manage.py migrate
python manage.py dados_exemplo
python manage.py runserver
```

O `migrate` é obrigatório a cada atualização: é ele que ajusta o banco às
mudanças na estrutura dos dados.

### Sobre "dar commit"

Você não precisa. Commit e envio para o GitHub são feitos por quem escreve o
código. O que chega até você é o resultado: ou já em `main`, se você aceitou o
pull request, ou na branch de desenvolvimento, se ainda não.

O seu papel no fluxo é aceitar (ou não) o pull request, e depois baixar.

## Como rodar os testes

```bash
python -m pytest testes/     # testes do motor de cálculo
python manage.py test        # testes dos modelos de dados
```

Os testes do motor foram escritos com números conferíveis à mão: quem entende do
ensaio consegue validar os resultados com uma calculadora, sem ler código.

## Organização do projeto

```
motor/          Cálculo estatístico puro, sem interface e sem banco de dados
  precisao.py         CLSI EP15 — repetibilidade e precisão intermediária
  comparabilidade.py  CLSI EP09 — Deming, Passing-Bablok, Bland-Altman
  qualitativo.py      CLSI EP12 — sensibilidade, especificidade, kappa
  concordancia.py     Lin, concordância analítica e concordância clínica
  especificacoes.py   Limites de aceitação (EQA) e suas referências
  veredito.py         Decisão: aprovado, reprovado ou indeterminado
  graficos.py         Gráficos SVG do relatório, gerados sem dependências

contas/         Laboratórios (clientes), usuários e módulos contratados
catalogo/       Rastreabilidade: equipamentos, reagentes, calibradores, controles
estudos/        Estudos de validação: dados brutos e vereditos
config/         Configuração do Django
testes/         Testes automatizados do motor
```

O motor fica separado de propósito. Ele não depende do Django nem de banco de
dados, o que permite testá-lo isoladamente e auditá-lo número a número — a parte
que decide aprovação de método é a que mais precisa ser verificável.

## Rastreabilidade

Todo estudo exige, antes de qualquer dado bruto:

- **Mensurando**: nome, unidade de medida, material biológico
- **Sistema Analítico em Teste (S.A.t)**: equipamento, número de série,
  metodologia, intervalo analítico
- **Sistema Analítico de Comparação (S.A.c)**: os mesmos dados do método em uso
- **Reagente, calibrador e material de controle**: nome, lote e validade
- **Especificação da Qualidade Analítica (EQA)**: erro total máximo, bias máximo
  e imprecisão máxima por nível, cada um com a **referência científica** que o
  justifica

A referência científica é obrigatória. Um limite de aceitação sem origem
declarada não sustenta auditoria — a pergunta "por que 12%?" precisa de resposta
documentada. O sistema bloqueia a aprovação de um estudo cuja especificação
tenha limite sem referência.

## Decisões de projeto que valem conhecer

**Nenhum veredito sem dado.** Quando falta qualquer insumo do cálculo, o
resultado é `INDETERMINADO` com a lista do que falta — nunca um número estimado
preenchendo a lacuna.

**O veredito é congelado.** Ao concluir um estudo, o resultado do cálculo é
gravado junto com a versão do motor que o produziu. Um relatório emitido hoje
continuará mostrando exatamente os mesmos números daqui a cinco anos, mesmo que
o motor evolua.

**Dado bruto não se apaga.** Réplicas e amostras descartadas do cálculo são
marcadas como excluídas, com justificativa obrigatória, e permanecem no
registro.

**Estudo liberado não se edita.** Depois de assinado pelo responsável técnico,
o estudo vira registro de qualidade: para corrigir, cancela-se e abre-se outro,
deixando o histórico visível.

## Aviso sobre as normas CLSI

Este sistema implementa procedimentos estatísticos descritos nos documentos CLSI
(EP05, EP09, EP12, EP15). Os documentos CLSI são protegidos por direito autoral
e devem ser adquiridos junto ao próprio CLSI — este repositório não os reproduz.
O sistema não é certificado, aprovado nem endossado pelo CLSI, e a
responsabilidade pela validação dos métodos permanece do laboratório e de seu
responsável técnico.
