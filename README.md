# Sistema de Validação de Métodos Analíticos

Plataforma web para laboratórios de pequeno e médio porte executarem e
documentarem a validação de seus métodos analíticos, seguindo os procedimentos
descritos nas normas CLSI.

## Estado atual

O que já está pronto e testado:

| Parte | Situação |
|---|---|
| Motor de cálculo (estatística) | ✅ Pronto — 59 testes automatizados |
| Modelos de dados e rastreabilidade | ✅ Pronto — 8 testes automatizados |
| Cadastro de laboratórios e usuários | ✅ Pronto (painel administrativo) |
| Controle dos módulos contratados | ✅ Pronto |
| Telas para o laboratório usar | ⏳ A fazer |
| Relatório em PDF | ⏳ A fazer |
| Gráficos (Levey-Jennings, Bland-Altman) | ⏳ A fazer |

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

## Como rodar na sua máquina

Precisa ter o Python 3.11 ou mais novo instalado.

```bash
# 1. Instalar as dependências
pip install -r requirements-dev.txt

# 2. Criar o banco de dados local
python manage.py migrate

# 3. Criar o seu usuário de administrador
python manage.py createsuperuser

# 4. Subir o sistema
python manage.py runserver
```

Depois abra <http://localhost:8000/admin/> no navegador e entre com o usuário
que você criou.

Nada disso precisa de banco de dados instalado: em desenvolvimento o sistema
cria sozinho um arquivo `banco-local.sqlite3`. O PostgreSQL só entra em
produção.

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
  especificacoes.py   Limites de aceitação (EQA) e suas referências
  veredito.py         Decisão: aprovado, reprovado ou indeterminado

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
