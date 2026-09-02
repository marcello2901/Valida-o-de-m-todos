"""Módulo de Precisão — avaliação de réplicas de material de controle.

Procedimento de referência: CLSI EP15 (verificação de precisão pelo usuário).

Dois resultados distintos, frequentemente confundidos:

- **Repetibilidade** (precisão intra-ensaio): dispersão entre réplicas medidas
  nas mesmas condições, na mesma corrida. É o piso do erro aleatório.
- **Precisão intermediária** (precisão intralaboratorial): dispersão que inclui
  também a variação entre corridas/dias. É sempre maior ou igual à
  repetibilidade, e é ela que representa o desempenho real do método na rotina.

Um laboratório que reporta só a repetibilidade subestima o próprio erro.
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

REPETIBILIDADE = "repetibilidade"
INTERMEDIARIA = "precisão intermediária"


def avaliar_precisao(corridas: Sequence[Sequence[float]], desenho: str) -> dict:
    """Executa o estudo de precisão conforme o desenho escolhido pelo laboratório.

    A escolha do desenho não é uma preferência de conveniência: ela determina
    **qual erro o estudo consegue enxergar**.

    - **Múltiplas corridas** (5 dias × 5 réplicas): mede repetibilidade e
      precisão intermediária. A precisão intermediária é a que representa o
      desempenho na rotina, porque incorpora recalibrações, trocas de operador e
      variação entre dias.
    - **Corrida única** (≥10 réplicas no mesmo dia): mede apenas repetibilidade.
      Tudo que varia entre dias fica invisível.

    Consequência prática registrada em ``avisos``: um Erro Total calculado a
    partir de repetibilidade **subestima** o erro real do método. O laboratório
    pode escolher esse desenho, mas o relatório precisa dizer o que ele não viu.
    """
    grupos = [est.limpar(c) for c in corridas]
    grupos = [g for g in grupos if g]
    todas = [valor for grupo in grupos for valor in grupo]

    avisos: list[str] = []

    if desenho == DESENHO_CORRIDA_UNICA:
        return _precisao_corrida_unica(grupos, todas, avisos)
    if desenho == DESENHO_MULTIPLAS_CORRIDAS:
        return _precisao_multiplas_corridas(grupos, todas, avisos)

    return {
        "desenho": desenho,
        "n_corridas": len(grupos),
        "n_total": len(todas),
        "media": est.media(todas),
        "cv_repetibilidade": None,
        "cv_intermediaria": None,
        "cv_aplicavel": None,
        "tipo_cv_aplicavel": None,
        "atende_minimo": False,
        "avisos": [f"Desenho de estudo desconhecido: {desenho!r}."],
    }


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
        "cv_repetibilidade": resumo["cv"],
        "cv_intermediaria": None,
        "cv_aplicavel": resumo["cv"],
        "tipo_cv_aplicavel": REPETIBILIDADE if resumo["cv"] is not None else None,
        "atende_minimo": atende,
        "avisos": avisos,
    }


def _precisao_multiplas_corridas(grupos, todas, avisos) -> dict:
    componentes = componentes_precisao(grupos)

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
    if componentes["observacao"]:
        avisos.append(componentes["observacao"])

    cv_aplicavel = componentes["cv_intermediaria"]
    tipo = INTERMEDIARIA if cv_aplicavel is not None else None

    return {
        "desenho": DESENHO_MULTIPLAS_CORRIDAS,
        "n_corridas": componentes["n_corridas"],
        "n_total": componentes["n_total"],
        "media": componentes["media"],
        "cv_repetibilidade": componentes["cv_repetibilidade"],
        "cv_intermediaria": componentes["cv_intermediaria"],
        "cv_aplicavel": cv_aplicavel,
        "tipo_cv_aplicavel": tipo,
        "atende_minimo": corridas_suficientes and replicas_suficientes,
        "avisos": avisos,
    }
