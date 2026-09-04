"""Módulo de Precisão — avaliação de réplicas de material de controle.

Procedimento de referência: CLSI EP15 (verificação de precisão pelo usuário).

O que o estudo entrega, por nível de controle:

- **Média intracorrida, desvio padrão e CV de cada corrida** — a leitura do dia.
- **CV agrupado** (pooled) das corridas — a dispersão que é comparada com o CV
  máximo estabelecido para aquele nível.
- **Bias absoluto e relativo** — a média global das réplicas contra a média do
  material no estudo interlaboratorial (e-Lab, Unity, fleet). Sem essa média
  informada, a exatidão não é avaliada: não há contra o que comparar.

Uma ressalva que o módulo mantém à vista. O CV agrupado é dispersão **dentro**
de corrida: ele não enxerga o que muda entre os dias — recalibração, troca de
operador, frasco novo de reagente. A precisão intermediária, que inclui essa
variação, continua sendo calculada e comparada com o mesmo limite. Quando as
duas discordam, ``avisos`` diz — porque aí o método passa no papel e falha na
rotina, e é justamente esse o caso em que ninguém quer ser avisado tarde.
"""

from __future__ import annotations

import math
from typing import Sequence

from . import estatistica as est


def resumo_replicas(valores: Sequence[float]) -> dict:
    """Estatística descritiva de uma série de réplicas de um mesmo nível."""
    dados = est.limpar(valores)
    return {
        "n": len(dados),
        "media": est.media(dados),
        "desvio_padrao": est.desvio_padrao(dados),
        "cv": est.coeficiente_variacao(dados),
        "minimo": min(dados) if dados else None,
        "maximo": max(dados) if dados else None,
    }


def estatisticas_por_corrida(corridas: Sequence[Sequence[float]]) -> list[dict]:
    """Média intracorrida, desvio padrão e CV de cada corrida, na ordem."""
    saida = []
    for numero, valores in enumerate(corridas, start=1):
        resumo = resumo_replicas(valores)
        resumo["corrida"] = numero
        saida.append(resumo)
    return saida


def desvio_padrao_agrupado(corridas: Sequence[Sequence[float]]) -> float | None:
    """Desvio padrão agrupado (pooled) das corridas.

    Média ponderada das variâncias pelos graus de liberdade de cada corrida:
    ``s² = Σ(nᵢ−1)·sᵢ² / Σ(nᵢ−1)``. Corridas com uma réplica só não têm
    variância e apenas não entram na conta — não zeram o resultado.

    Vale registrar que este número é a **repetibilidade**: é dispersão dentro de
    corrida. O agrupamento junta as corridas para ganhar graus de liberdade, não
    para incorporar a variação entre elas.
    """
    numerador = 0.0
    graus = 0
    for valores in corridas:
        dados = est.limpar(valores)
        desvio = est.desvio_padrao(dados)
        if desvio is None:
            continue
        graus_da_corrida = len(dados) - 1
        numerador += graus_da_corrida * desvio**2
        graus += graus_da_corrida

    if graus <= 0:
        return None
    return math.sqrt(numerador / graus)


def bias_analitico(media_obtida: float | None, media_alvo: float | None) -> dict:
    """Bias da média global das réplicas contra a média interlaboratorial.

    ``media_alvo`` é a média do mesmo lote de controle no grupo de pares (e-Lab,
    Unity, fleet). Sem ela, devolve ``avaliavel=False`` e nenhum número
    inventado — a exatidão simplesmente não é avaliada.
    """
    if media_obtida is None or media_alvo is None:
        return {
            "avaliavel": False,
            "media_obtida": media_obtida,
            "media_alvo": media_alvo,
            "absoluto": None,
            "relativo_pct": None,
            "motivo": "média do estudo interlaboratorial não informada",
        }
    if media_alvo == 0:
        return {
            "avaliavel": False,
            "media_obtida": media_obtida,
            "media_alvo": media_alvo,
            "absoluto": media_obtida - media_alvo,
            "relativo_pct": None,
            "motivo": "média interlaboratorial igual a zero: bias relativo indefinido",
        }

    absoluto = media_obtida - media_alvo
    return {
        "avaliavel": True,
        "media_obtida": media_obtida,
        "media_alvo": media_alvo,
        "absoluto": absoluto,
        "relativo_pct": absoluto / media_alvo * 100,
        "motivo": None,
    }


def componentes_precisao(corridas: Sequence[Sequence[float]]) -> dict:
    """Decompõe a variação de um nível em repetibilidade e precisão intermediária.

    ``corridas`` é uma lista de corridas (ou dias); cada corrida é a lista de
    réplicas medidas nela. O desenho típico do EP15 é 5 corridas × 5 réplicas.

    O cálculo é uma ANOVA de fator único (corrida). Aceita corridas com número
    diferente de réplicas: nesse caso usa o tamanho efetivo de grupo (n₀), a
    correção padrão para desenhos desbalanceados.

    Detalhe que costuma ser implementado errado: quando a variação entre
    corridas estimada sai negativa — o que acontece por flutuação amostral —
    ela é truncada em zero, e a precisão intermediária passa a igualar a
    repetibilidade. Variância negativa não existe; propagá-la produziria uma
    raiz quadrada de número negativo ou um DP menor que o intra-ensaio.
    """
    grupos = [est.limpar(c) for c in corridas]
    grupos = [g for g in grupos if len(g) >= 1]

    k = len(grupos)
    total = sum(len(g) for g in grupos)

    if k < 2 or total <= k:
        # Sem pelo menos duas corridas e mais observações que corridas não há
        # graus de liberdade para separar as duas fontes de variação.
        return _componentes_indeterminados(
            k, total, "são necessárias no mínimo 2 corridas com réplicas"
        )

    grande_media = sum(sum(g) for g in grupos) / total
    medias = [sum(g) / len(g) for g in grupos]

    soma_quadrados_entre = sum(
        len(g) * (m - grande_media) ** 2 for g, m in zip(grupos, medias)
    )
    soma_quadrados_dentro = sum(
        sum((x - m) ** 2 for x in g) for g, m in zip(grupos, medias)
    )

    gl_entre = k - 1
    gl_dentro = total - k

    if gl_dentro <= 0:
        return _componentes_indeterminados(
            k, total, "cada corrida precisa de ao menos 2 réplicas"
        )

    quadrado_medio_entre = soma_quadrados_entre / gl_entre
    quadrado_medio_dentro = soma_quadrados_dentro / gl_dentro

    # Tamanho efetivo de grupo: iguala len(g) em desenho balanceado.
    n_efetivo = (total - sum(len(g) ** 2 for g in grupos) / total) / gl_entre

    variancia_repetibilidade = quadrado_medio_dentro
    variancia_entre = max(
        0.0, (quadrado_medio_entre - quadrado_medio_dentro) / n_efetivo
    )
    variancia_intermediaria = variancia_repetibilidade + variancia_entre

    dp_repetibilidade = math.sqrt(variancia_repetibilidade)
    dp_intermediaria = math.sqrt(variancia_intermediaria)

    return {
        "n_corridas": k,
        "n_total": total,
        "media": grande_media,
        "desvio_padrao_repetibilidade": dp_repetibilidade,
        "desvio_padrao_intermediaria": dp_intermediaria,
        "cv_repetibilidade": _cv(dp_repetibilidade, grande_media),
        "cv_intermediaria": _cv(dp_intermediaria, grande_media),
        "variancia_entre_corridas": variancia_entre,
        "graus_liberdade_repetibilidade": gl_dentro,
        "observacao": None,
    }


def _cv(desvio: float | None, media: float | None) -> float | None:
    if desvio is None or media is None or media == 0:
        return None
    return (desvio / media) * 100


def _componentes_indeterminados(k: int, total: int, motivo: str) -> dict:
    return {
        "n_corridas": k,
        "n_total": total,
        "media": None,
        "desvio_padrao_repetibilidade": None,
        "desvio_padrao_intermediaria": None,
        "cv_repetibilidade": None,
        "cv_intermediaria": None,
        "variancia_entre_corridas": None,
        "graus_liberdade_repetibilidade": 0,
        "observacao": motivo,
    }


# --- Desenho do estudo ------------------------------------------------------
#
# O laboratório escolhe entre dois desenhos, e a escolha muda o que o estudo é
# capaz de medir.

DESENHO_MULTIPLAS_CORRIDAS = "multiplas_corridas"
DESENHO_CORRIDA_UNICA = "corrida_unica"

DESENHOS = [
    (DESENHO_MULTIPLAS_CORRIDAS, "Múltiplas corridas — 5 dias consecutivos, 5 réplicas por dia"),
    (DESENHO_CORRIDA_UNICA, "Corrida única — todas as réplicas no mesmo dia (mínimo 10)"),
]

# Desenho de referência do EP15: 5 corridas de 5 réplicas.
MINIMO_CORRIDAS = 5
MINIMO_REPLICAS_POR_CORRIDA = 5

# Em corrida única, o mínimo de réplicas para o CV ter estabilidade aceitável.
MINIMO_REPLICAS_CORRIDA_UNICA = 10

CV_AGRUPADO = "CV agrupado das corridas"
CV_DA_CORRIDA = "CV da corrida"


def avaliar_precisao(
    corridas: Sequence[Sequence[float]],
    desenho: str,
    media_interlaboratorial: float | None = None,
) -> dict:
    """Executa o estudo de precisão conforme o desenho escolhido pelo laboratório.

    Devolve a estatística de cada corrida, o CV que será comparado com o limite
    do nível, e o bias contra a média interlaboratorial quando ela for informada.

    A escolha do desenho não é preferência de conveniência: ela determina qual
    erro o estudo consegue enxergar. Corrida única não observa nada do que varia
    entre dias, e o Erro Total calculado a partir dela sai otimista. O aviso
    correspondente vai em ``avisos``, para constar no relatório.
    """
    grupos = [est.limpar(c) for c in corridas]
    grupos = [g for g in grupos if g]
    todas = [valor for grupo in grupos for valor in grupo]

    avisos: list[str] = []

    if desenho == DESENHO_CORRIDA_UNICA:
        base = _precisao_corrida_unica(grupos, todas, avisos)
    elif desenho == DESENHO_MULTIPLAS_CORRIDAS:
        base = _precisao_multiplas_corridas(grupos, todas, avisos)
    else:
        return {
            "desenho": desenho,
            "n_corridas": len(grupos),
            "n_total": len(todas),
            "media": est.media(todas),
            "corridas": estatisticas_por_corrida(grupos),
            "desvio_padrao": None,
            "cv": None,
            "cv_aplicavel": None,
            "tipo_cv_aplicavel": None,
            "cv_intermediaria": None,
            "bias": bias_analitico(None, media_interlaboratorial),
            "atende_minimo": False,
            "avisos": [f"Desenho de estudo desconhecido: {desenho!r}."],
        }

    base["bias"] = bias_analitico(base["media"], media_interlaboratorial)
    return base


def _precisao_corrida_unica(grupos, todas, avisos) -> dict:
    if len(grupos) > 1:
        avisos.append(
            "Foram informadas várias corridas, mas o desenho escolhido é de corrida "
            "única: as réplicas foram tratadas como um bloco só e a variação entre "
            "corridas não foi avaliada."
        )

    resumo = resumo_replicas(todas)
    n = resumo["n"]
    atende = n >= MINIMO_REPLICAS_CORRIDA_UNICA

    if not atende:
        avisos.append(
            f"Corrida única exige no mínimo {MINIMO_REPLICAS_CORRIDA_UNICA} réplicas "
            f"por nível; foram informadas {n}."
        )

    avisos.append(
        "Desenho de corrida única mede apenas repetibilidade. A variação entre dias "
        "(recalibração, troca de operador, novo frasco de reagente) não foi observada, "
        "portanto o Erro Total calculado a partir deste CV subestima o erro da rotina."
    )

    return {
        "desenho": DESENHO_CORRIDA_UNICA,
        "n_corridas": 1 if todas else 0,
        "n_total": n,
        "media": resumo["media"],
        "corridas": estatisticas_por_corrida([todas] if todas else []),
        "desvio_padrao": resumo["desvio_padrao"],
        "cv": resumo["cv"],
        "cv_aplicavel": resumo["cv"],
        "tipo_cv_aplicavel": CV_DA_CORRIDA if resumo["cv"] is not None else None,
        "cv_intermediaria": None,
        "atende_minimo": atende,
        "avisos": avisos,
    }


def _precisao_multiplas_corridas(grupos, todas, avisos) -> dict:
    por_corrida = estatisticas_por_corrida(grupos)
    media_global = est.media(todas)
    desvio_agrupado = desvio_padrao_agrupado(grupos)
    cv_agrupado = _cv(desvio_agrupado, media_global)

    corridas_suficientes = len(grupos) >= MINIMO_CORRIDAS
    replicas_suficientes = all(len(g) >= MINIMO_REPLICAS_POR_CORRIDA for g in grupos)

    if not corridas_suficientes:
        avisos.append(
            f"O desenho de referência do EP15 pede {MINIMO_CORRIDAS} corridas; "
            f"foram informadas {len(grupos)}."
        )
    if grupos and not replicas_suficientes:
        avisos.append(
            f"O desenho de referência do EP15 pede {MINIMO_REPLICAS_POR_CORRIDA} "
            "réplicas por corrida; ao menos uma corrida tem menos que isso."
        )

    componentes = componentes_precisao(grupos)
    if componentes["observacao"]:
        avisos.append(componentes["observacao"])

    return {
        "desenho": DESENHO_MULTIPLAS_CORRIDAS,
        "n_corridas": len(grupos),
        "n_total": len(todas),
        "media": media_global,
        "corridas": por_corrida,
        "desvio_padrao": desvio_agrupado,
        "cv": cv_agrupado,
        "cv_aplicavel": cv_agrupado,
        "tipo_cv_aplicavel": CV_AGRUPADO if cv_agrupado is not None else None,
        "cv_intermediaria": componentes["cv_intermediaria"],
        "atende_minimo": corridas_suficientes and replicas_suficientes,
        "avisos": avisos,
    }


def alerta_precisao_intermediaria(estatistica: dict, limite_pct: float | None) -> str | None:
    """Avisa quando só a variação entre dias estoura o limite.

    O CV agrupado é dispersão dentro de corrida. Se ele passa no limite e a
    precisão intermediária não passa, o que reprovou o método foi exatamente o
    que o CV agrupado não enxerga: a variação entre os dias. O método passaria no
    relatório e falharia na rotina — o pior desfecho possível para uma validação,
    e por isso este alerta existe.
    """
    if limite_pct is None:
        return None
    agrupado = estatistica.get("cv")
    intermediaria = estatistica.get("cv_intermediaria")
    if agrupado is None or intermediaria is None:
        return None
    if agrupado <= limite_pct < intermediaria:
        return (
            f"O CV agrupado ({agrupado:.2f}%) cabe no limite de {limite_pct:.2f}%, "
            f"mas a precisão intermediária — que inclui a variação entre os dias — "
            f"é de {intermediaria:.2f}%. O que passou no cálculo foi a dispersão "
            "dentro da corrida; na rotina o método tende a ficar fora do limite."
        )
    return None
