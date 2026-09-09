"""Módulo de Comparabilidade — método de comparação (S.A.c) contra método testado (S.A.t).

Procedimento de referência: CLSI EP09 (comparação de procedimentos de medição e
estimativa de erro sistemático com amostras de pacientes).

Convenção usada em todo o módulo: **X é o sistema de comparação** (método
antigo) e **Y é o sistema em teste** (método novo). Bias positivo significa que
o método novo lê acima do antigo.

Por que não há mínimos quadrados comum aqui: a regressão linear clássica supõe
que o eixo X é isento de erro. Ao comparar dois métodos analíticos, ambos têm
imprecisão — e essa suposição violada puxa a inclinação sistematicamente para
baixo, criando erro proporcional onde não existe. Por isso o módulo oferece
Deming, que admite erro nos dois eixos.
"""

from __future__ import annotations

import math
from typing import Sequence

from . import estatistica as est

# Número mínimo de amostras que o EP09 pede para uma comparação de métodos.
MINIMO_AMOSTRAS_EP09 = 40


def bland_altman(comparacao: Sequence[float], teste: Sequence[float]) -> dict:
    """Viés médio e limites de concordância entre os dois métodos.

    O viés aqui é a média das diferenças (Y − X) ao longo de todas as amostras.
    Ele responde "o método novo lê mais alto ou mais baixo, em média?" — mas não
    responde quanto ele erra numa concentração específica. Para isso existe
    ``bias_no_nivel``, que é o que importa quando a decisão clínica acontece num
    ponto de corte.
    """
    pares = est.parear(comparacao, teste)
    n = len(pares)

    if n == 0:
        return _bland_altman_vazio()

    diferencas = [y - x for x, y in pares]
    vies = sum(diferencas) / n
    media_comparacao = sum(x for x, _ in pares) / n
    vies_pct = (vies / media_comparacao) * 100 if media_comparacao != 0 else None

    if n < 2:
        return {
            "n": n,
            "vies": vies,
            "vies_pct": vies_pct,
            "desvio_padrao_diferencas": None,
            "limite_inferior": None,
            "limite_superior": None,
            "atende_minimo_ep09": False,
        }

    dp_diferencas = math.sqrt(sum((d - vies) ** 2 for d in diferencas) / (n - 1))

    return {
        "n": n,
        "vies": vies,
        "vies_pct": vies_pct,
        "desvio_padrao_diferencas": dp_diferencas,
        "limite_inferior": vies - est.Z_95_BILATERAL * dp_diferencas,
        "limite_superior": vies + est.Z_95_BILATERAL * dp_diferencas,
        "atende_minimo_ep09": n >= MINIMO_AMOSTRAS_EP09,
    }


def _bland_altman_vazio() -> dict:
    return {
        "n": 0,
        "vies": None,
        "vies_pct": None,
        "desvio_padrao_diferencas": None,
        "limite_inferior": None,
        "limite_superior": None,
        "atende_minimo_ep09": False,
    }


def deming(
    comparacao: Sequence[float],
    teste: Sequence[float],
    lambda_erro: float = 1.0,
) -> dict:
    """Regressão de Deming de Y (teste) sobre X (comparação).

    ``lambda_erro`` é a razão entre a variância do erro analítico de Y e a de X.
    O padrão 1,0 assume imprecisão semelhante nos dois sistemas e reduz o
    estimador à regressão ortogonal. Quando se conhece o CV de cada método, o
    valor correto é (CV_teste / CV_comparação)².
    """
    pares = est.parear(comparacao, teste)
    n = len(pares)

    if n < 3 or lambda_erro <= 0:
        return _regressao_vazia(
            n, "Deming", "são necessárias ao menos 3 amostras pareadas"
        )

    media_x = sum(x for x, _ in pares) / n
    media_y = sum(y for _, y in pares) / n

    s_xx = sum((x - media_x) ** 2 for x, _ in pares)
    s_yy = sum((y - media_y) ** 2 for _, y in pares)
    s_xy = sum((x - media_x) * (y - media_y) for x, y in pares)

    if s_xy == 0:
        return _regressao_vazia(
            n, "Deming", "sem covariância entre os métodos — a reta é indefinida"
        )

    termo = s_yy - lambda_erro * s_xx
    inclinacao = (termo + math.sqrt(termo**2 + 4 * lambda_erro * s_xy**2)) / (2 * s_xy)

    return {
        "metodo": "Deming",
        "n": n,
        "inclinacao": inclinacao,
        "intercepto": media_y - inclinacao * media_x,
        "atende_minimo_ep09": n >= MINIMO_AMOSTRAS_EP09,
        "observacao": None,
    }


def _regressao_vazia(n: int, metodo: str, motivo: str) -> dict:
    """Resultado de regressão sem reta, dizendo por quê.

    Ficava logo abaixo do Passing-Bablok e saiu junto com ele por descuido; é do
    Deming também. Devolver um dicionário com o motivo, em vez de None, é o que
    permite a tela dizer "não deu para calcular porque..." em vez de sumir com a
    linha.
    """
    return {
        "metodo": metodo,
        "n": n,
        "inclinacao": None,
        "intercepto": None,
        "atende_minimo_ep09": False,
        "observacao": motivo,
    }


def bias_no_nivel(
    inclinacao: float | None, intercepto: float | None, nivel: float
) -> dict:
    """Erro sistemático estimado pela reta num nível de decisão clínica.

    É o número que decide a validação na prática: o erro do método novo na
    concentração em que uma conduta muda — não a média de todas as amostras, que
    pode esconder um viés grande no ponto de corte e pequeno no resto da faixa.
    """
    if inclinacao is None or intercepto is None or not est.e_numero(nivel):
        return {"nivel": nivel, "valor_estimado": None, "bias": None, "bias_pct": None}

    nivel = float(nivel)
    estimado = inclinacao * nivel + intercepto
    bias = estimado - nivel

    return {
        "nivel": nivel,
        "valor_estimado": estimado,
        "bias": bias,
        "bias_pct": (bias / nivel) * 100 if nivel != 0 else None,
    }


def regressao_linear(comparacao: Sequence[float], teste: Sequence[float]) -> dict:
    """Regressão por mínimos quadrados, com coeficientes r e r².

    Incluída porque é esperada em relatórios de validação e porque **r serve
    para julgar a amplitude das amostras**: o EP09 usa r ≥ 0,975 como indício de
    que a faixa de concentrações estudada é ampla o bastante para uma regressão
    simples ser confiável.

    Duas advertências que precisam constar no relatório:

    1. **r não mede concordância.** Dois métodos podem ter r = 0,999 e um deles
       ler 30% acima do outro em toda a faixa. Correlação mede se os pontos
       seguem *uma* reta, não se seguem a reta de identidade.
    2. **A inclinação aqui é enviesada** para baixo, porque mínimos quadrados
       supõe o eixo X isento de erro. Para decidir sobre erro proporcional, use
       a inclinação de Deming, não esta.
    """
    pares = est.parear(comparacao, teste)
    n = len(pares)

    if n < 3:
        return {
            "metodo": "Mínimos quadrados",
            "n": n,
            "inclinacao": None,
            "intercepto": None,
            "r": None,
            "r2": None,
            "erro_padrao_estimativa": None,
            "amplitude_adequada": None,
            "observacao": "são necessárias ao menos 3 amostras pareadas",
        }

    media_x = sum(x for x, _ in pares) / n
    media_y = sum(y for _, y in pares) / n

    s_xx = sum((x - media_x) ** 2 for x, _ in pares)
    s_yy = sum((y - media_y) ** 2 for _, y in pares)
    s_xy = sum((x - media_x) * (y - media_y) for x, y in pares)

    if s_xx == 0 or s_yy == 0:
        return {
            "metodo": "Mínimos quadrados",
            "n": n,
            "inclinacao": None,
            "intercepto": None,
            "r": None,
            "r2": None,
            "erro_padrao_estimativa": None,
            "amplitude_adequada": None,
            "observacao": "sem variação em um dos métodos — a reta é indefinida",
        }

    inclinacao = s_xy / s_xx
    intercepto = media_y - inclinacao * media_x
    r = s_xy / math.sqrt(s_xx * s_yy)

    residuos = [(y - (inclinacao * x + intercepto)) ** 2 for x, y in pares]
    erro_padrao = math.sqrt(sum(residuos) / (n - 2)) if n > 2 else None

    return {
        "metodo": "Mínimos quadrados",
        "n": n,
        "inclinacao": inclinacao,
        "intercepto": intercepto,
        "r": r,
        "r2": r**2,
        "erro_padrao_estimativa": erro_padrao,
        "amplitude_adequada": abs(r) >= 0.975,
        "observacao": None,
    }
