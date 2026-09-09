"""Motor de veredito — decide aprovação, reprovação ou recusa de decidir.

Regra que governa este módulo inteiro: **um veredito só existe quando todos os
dados que o sustentam existem.** Quando falta insumo, o resultado é
``INDETERMINADO`` acompanhado da lista do que falta — nunca um número plausível
preenchendo a lacuna.

Consequência de produto, que precisa estar clara na hora de vender os módulos:

- O **módulo de precisão** isolado mede imprecisão (CV) e a compara com o limite
  de imprecisão. Ele **não pode** calcular Erro Total nem métrica Sigma, porque
  ambos exigem o bias — que só o estudo de comparabilidade produz.
- O **módulo de comparabilidade** isolado mede o bias e o compara com o limite de
  bias. Também **não pode** calcular Erro Total nem Sigma, pela razão simétrica.
- Só o **pacote completo** fecha a conta: TE% = |bias%| + 1,65 × CV%.

Prometer "validação do método" no plano de módulo isolado seria vender um
veredito que o próprio cálculo não sustenta.
"""

from __future__ import annotations

from . import especificacoes as espec

APROVADO = "APROVADO"
REPROVADO = "REPROVADO"
INDETERMINADO = "INDETERMINADO"

MODULO_PRECISAO = "precisao"
MODULO_COMPARABILIDADE = "comparabilidade"
MODULO_COMPLETO = "completo"

# Fator z do Erro Total de Westgard (95% unilateral).
FATOR_ERRO_TOTAL = 1.65

# --- De onde vem o bias ------------------------------------------------------
#
# São dois erros sistemáticos diferentes, medidos por estudos diferentes, e
# tratá-los como um só indicador "bias" tirava a exatidão de quem tem direito a
# ela:
#
# * **Interlaboratorial** — a média das réplicas contra a média do mesmo lote de
#   controle no grupo de pares. Sai inteira do estudo de PRECISÃO: são as
#   réplicas do laboratório e um número do boletim do programa. Não depende de
#   amostra pareada nenhuma.
# * **Regressão** — o bias estimado pela reta, na concentração do nível. Sai do
#   estudo de COMPARABILIDADE, que é onde existem amostras de paciente medidas
#   nos dois sistemas.
#
# Antes as duas eram a capacidade "bias", atribuída à comparabilidade. Quem
# contratava só precisão lançava a média do grupo de pares, via a exatidão
# calculada na tela e não recebia limite nem situação — o número aparecia sem
# veredito, que é a pior forma de mostrá-lo.
BIAS_INTERLABORATORIAL = "bias_interlaboratorial"
BIAS_REGRESSAO = "bias_regressao"

# A origem que o serviço informa, traduzida para a capacidade que ela exige.
_CAPACIDADE_DA_ORIGEM = {
    "interlaboratorial": BIAS_INTERLABORATORIAL,
    "regressao": BIAS_REGRESSAO,
}

_CAPACIDADES = {
    MODULO_PRECISAO: {"imprecisao", BIAS_INTERLABORATORIAL},
    MODULO_COMPARABILIDADE: {BIAS_REGRESSAO},
    MODULO_COMPLETO: {
        "imprecisao", BIAS_INTERLABORATORIAL, BIAS_REGRESSAO, "erro_total", "sigma"
    },
}


def capacidades(modulo: str) -> set[str]:
    """O que o módulo contratado é capaz de avaliar."""
    return _CAPACIDADES.get(modulo, set())


def _comparar(valor: float | None, limite: dict) -> dict:
    """Compara um valor observado com um limite resolvido, em pontos percentuais."""
    if valor is None:
        return {"status": INDETERMINADO, "motivo": "valor observado ausente"}
    if not limite["definido"] or limite["limite_pct"] is None:
        return {"status": INDETERMINADO, "motivo": "limite de aceitação não definido"}

    return {
        "status": APROVADO if abs(valor) <= limite["limite_pct"] else REPROVADO,
        "motivo": None,
    }


def avaliar_imprecisao(
    cv_pct: float | None,
    limite: espec.LimiteQualidade,
    concentracao: float | None,
) -> dict:
    """Compara o CV observado com a imprecisão máxima especificada para o nível."""
    resolvido = limite.aplicar(concentracao)
    comparacao = _comparar(cv_pct, resolvido)

    return {
        "indicador": "imprecisão",
        "observado_pct": cv_pct,
        "limite_pct": resolvido["limite_pct"],
        "tipo_limite": resolvido["tipo"],
        "referencia": resolvido["referencia"],
        "status": comparacao["status"],
        "motivo": comparacao["motivo"],
    }


def avaliar_bias(
    bias_pct: float | None,
    limite: espec.LimiteQualidade,
    concentracao: float | None,
) -> dict:
    """Compara o erro sistemático observado com o bias máximo especificado."""
    resolvido = limite.aplicar(concentracao)
    comparacao = _comparar(bias_pct, resolvido)

    return {
        "indicador": "bias",
        "observado_pct": bias_pct,
        "limite_pct": resolvido["limite_pct"],
        "tipo_limite": resolvido["tipo"],
        "referencia": resolvido["referencia"],
        "status": comparacao["status"],
        "motivo": comparacao["motivo"],
    }


def calcular_erro_total(bias_pct: float | None, cv_pct: float | None) -> float | None:
    """Erro Total de Westgard: TE% = |bias%| + 1,65 × CV%."""
    if bias_pct is None or cv_pct is None:
        return None
    return abs(bias_pct) + FATOR_ERRO_TOTAL * cv_pct


def avaliar_erro_total(
    bias_pct: float | None,
    cv_pct: float | None,
    limite: espec.LimiteQualidade,
    concentracao: float | None,
) -> dict:
    """Compara o Erro Total calculado com o erro total máximo especificado."""
    te = calcular_erro_total(bias_pct, cv_pct)
    resolvido = limite.aplicar(concentracao)
    comparacao = _comparar(te, resolvido)

    faltantes = []
    if cv_pct is None:
        faltantes.append("CV% do estudo de precisão")
    if bias_pct is None:
        faltantes.append("bias% do estudo de comparabilidade")

    return {
        "indicador": "erro total",
        "observado_pct": te,
        "limite_pct": resolvido["limite_pct"],
        "tipo_limite": resolvido["tipo"],
        "referencia": resolvido["referencia"],
        "status": comparacao["status"],
        "motivo": comparacao["motivo"],
        "faltantes": faltantes,
    }


def calcular_sigma(
    erro_total_max_pct: float | None,
    bias_pct: float | None,
    cv_pct: float | None,
) -> float | None:
    """Métrica Sigma: σ = (TEa% − |bias%|) / CV%.

    ``None`` quando o CV é zero: sem dispersão medida não há sigma. Um CV zerado
    quase sempre significa réplicas idênticas demais para serem reais — dados
    digitados errado ou copiados — e não um método perfeito.
    """
    if erro_total_max_pct is None or bias_pct is None or cv_pct is None or cv_pct == 0:
        return None
    return (erro_total_max_pct - abs(bias_pct)) / cv_pct


def classificar_sigma(sigma: float | None) -> str:
    """Escala Sigma usual em laboratório clínico."""
    if sigma is None:
        return "não calculável"
    if sigma >= 6:
        return "classe mundial (σ ≥ 6)"
    if sigma >= 5:
        return "excelente (5 ≤ σ < 6)"
    if sigma >= 4:
        return "bom (4 ≤ σ < 5)"
    if sigma >= 3:
        return "marginal (3 ≤ σ < 4)"
    return "inaceitável (σ < 3)"


def avaliar_nivel(
    modulo: str,
    nivel: int,
    especificacao: espec.EspecificacaoQualidade,
    concentracao: float | None = None,
    cv_pct: float | None = None,
    bias_pct: float | None = None,
    origem_do_bias: str | None = None,
) -> dict:
    """Avalia um nível de controle com tudo que o módulo contratado permite.

    ``origem_do_bias`` diz qual estudo produziu o erro sistemático — e portanto
    qual módulo precisa estar contratado para que ele seja avaliado. Ver a nota
    em ``_CAPACIDADES``.
    """
    permitido = capacidades(modulo)
    indicadores = []
    nao_contratados = []

    if "imprecisao" in permitido:
        indicadores.append(
            avaliar_imprecisao(
                cv_pct, especificacao.imprecisao_do_nivel(nivel), concentracao
            )
        )
    else:
        nao_contratados.append("imprecisão")

    # Origem conhecida decide pela capacidade correspondente. Origem ausente —
    # porque não há bias medido, ou porque quem chamou não informou — cai na
    # regra antiga: basta o módulo avaliar algum bias. É o que faz o indicador
    # continuar entrando como INDETERMINADO quando falta a média do grupo de
    # pares, em vez de sumir e o veredito não registrar que faltou.
    exigida = _CAPACIDADE_DA_ORIGEM.get(origem_do_bias or "")
    if exigida is None:
        avalia_bias = bool(permitido & {BIAS_INTERLABORATORIAL, BIAS_REGRESSAO})
    else:
        avalia_bias = exigida in permitido

    if avalia_bias:
        indicadores.append(avaliar_bias(bias_pct, especificacao.bias, concentracao))
    else:
        nao_contratados.append("bias")

    sigma = None
    if "erro_total" in permitido:
        indicadores.append(
            avaliar_erro_total(bias_pct, cv_pct, especificacao.erro_total, concentracao)
        )
        limite_te = especificacao.erro_total.aplicar(concentracao)["limite_pct"]
        sigma = calcular_sigma(limite_te, bias_pct, cv_pct)
    else:
        nao_contratados.append("erro total")
        nao_contratados.append("métrica sigma")

    return {
        "nivel": nivel,
        "concentracao": concentracao,
        "indicadores": indicadores,
        "sigma": sigma,
        "classificacao_sigma": classificar_sigma(sigma),
        "status": consolidar_status([i["status"] for i in indicadores]),
        "nao_contratados": nao_contratados,
    }


def consolidar_status(status: list[str]) -> str:
    """Combina vários status num só.

    Ordem de precedência deliberada: uma reprovação em qualquer indicador
    reprova o conjunto; na ausência de reprovação, qualquer indeterminação
    impede a aprovação. Aprovar um conjunto que contém indicador não avaliado
    seria emitir garantia sobre o que não foi medido.
    """
    if not status:
        return INDETERMINADO
    if REPROVADO in status:
        return REPROVADO
    if INDETERMINADO in status:
        return INDETERMINADO
    return APROVADO


def avaliar_estudo(
    modulo: str,
    especificacao: espec.EspecificacaoQualidade,
    niveis: list[dict],
) -> dict:
    """Veredito do estudo inteiro, nível a nível.

    Cada item de ``niveis`` é um dicionário com ``nivel`` e, conforme o módulo,
    ``concentracao``, ``cv_pct``, ``bias_pct`` e ``origem_do_bias``.
    """
    pendencias = especificacao.pendencias()

    avaliacoes = [
        avaliar_nivel(
            modulo=modulo,
            nivel=n.get("nivel"),
            especificacao=especificacao,
            concentracao=n.get("concentracao"),
            cv_pct=n.get("cv_pct"),
            bias_pct=n.get("bias_pct"),
            # Ausente quando quem chamou não informa: aí vale a regra permissiva
            # de ``avaliar_nivel``. Fixar um padrão aqui faria a comparabilidade
            # perder o bias da reta por causa de uma origem que ela não declarou.
            origem_do_bias=n.get("origem_do_bias"),
        )
        for n in niveis
    ]

    status_geral = consolidar_status([a["status"] for a in avaliacoes])

    # Especificação incompleta nunca produz aprovação, mesmo que os números
    # observados estejam dentro de algum limite parcialmente preenchido.
    if pendencias and status_geral == APROVADO:
        status_geral = INDETERMINADO

    return {
        "modulo": modulo,
        "status": status_geral,
        "niveis": avaliacoes,
        "pendencias_especificacao": pendencias,
    }
