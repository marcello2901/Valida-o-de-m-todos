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
