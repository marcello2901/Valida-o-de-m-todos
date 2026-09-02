"""Estatística de base do motor de validação.

Só biblioteca padrão do Python — nenhuma dependência externa. Isso mantém o
motor portátil, auditável e testável sem instalar nada, o que importa quando o
resultado destes cálculos vai para um registro de qualidade de laboratório.
"""

from __future__ import annotations

import math
from typing import Sequence

# Quantis da normal padrão usados nos cálculos.
Z_95_BILATERAL = 1.96  # limites de concordância, intervalos de confiança
Z_95_UNILATERAL = 1.65  # fator do Erro Total de Westgard


def e_numero(valor) -> bool:
    """Diz se o valor é um número real utilizável (descarta texto, vazio, NaN, infinito)."""
    try:
        return math.isfinite(float(valor))
    except (TypeError, ValueError):
        return False


def limpar(valores: Sequence) -> list[float]:
    """Converte para float e descarta o que não for número, preservando a ordem."""
    return [float(v) for v in valores if e_numero(v)]


def parear(x: Sequence, y: Sequence) -> list[tuple[float, float]]:
    """Pares (x, y) em que AMBOS os lados são números.

    Descartar o par inteiro — e não só o lado faltante — é o que impede que uma
    amostra sem resultado num dos métodos desalinhe toda a comparação.
    """
    return [(float(a), float(b)) for a, b in zip(x, y) if e_numero(a) and e_numero(b)]


def media(valores: Sequence[float]) -> float | None:
    dados = limpar(valores)
    return sum(dados) / len(dados) if dados else None


def desvio_padrao(valores: Sequence[float]) -> float | None:
    """Desvio padrão amostral (n−1), que é o usado em validação analítica.

    Com menos de duas observações não existe dispersão a estimar: o retorno é
    ``None``, nunca zero. Zero afirmaria precisão perfeita.
    """
    dados = limpar(valores)
    n = len(dados)
    if n < 2:
        return None
    m = sum(dados) / n
    return math.sqrt(sum((x - m) ** 2 for x in dados) / (n - 1))


def coeficiente_variacao(valores: Sequence[float]) -> float | None:
    """CV% = DP / média × 100. Indefinido (``None``) quando a média é zero."""
    m = media(valores)
    dp = desvio_padrao(valores)
    if m is None or dp is None or m == 0:
        return None
    return (dp / m) * 100


def mediana(valores: Sequence[float]) -> float | None:
    dados = sorted(limpar(valores))
    n = len(dados)
    if n == 0:
        return None
    meio = n // 2
    return dados[meio] if n % 2 else (dados[meio - 1] + dados[meio]) / 2


def intervalo_wilson(
    sucessos: int, total: int, z: float = Z_95_BILATERAL
) -> tuple[float, float] | None:
    """Intervalo de confiança de Wilson para uma proporção, em pontos percentuais.

    Preferido ao intervalo clássico (Wald) porque não colapsa em zero quando a
    proporção é 0% ou 100% e não extrapola para fora de [0, 100] — situações
    corriqueiras em validação qualitativa, onde o n costuma ser pequeno.
    """
    if total <= 0 or sucessos < 0 or sucessos > total:
        return None

    p = sucessos / total
    denominador = 1 + z**2 / total
    centro = (p + z**2 / (2 * total)) / denominador
    margem = (z / denominador) * math.sqrt(p * (1 - p) / total + z**2 / (4 * total**2))

    return (max(0.0, (centro - margem) * 100), min(100.0, (centro + margem) * 100))
