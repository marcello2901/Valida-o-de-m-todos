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
Deming e Passing-Bablok, que admitem erro nos dois eixos.
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


def passing_bablok(comparacao: Sequence[float], teste: Sequence[float]) -> dict:
    """Regressão de Passing-Bablok de Y (teste) sobre X (comparação).

    Estimador não paramétrico: a inclinação é a mediana deslocada de todas as
    inclinações entre pares de pontos. Não supõe distribuição normal dos erros e
    resiste a valores discrepantes, o que a torna preferível quando as amostras
    de pacientes trazem alguns pontos fora do comportamento geral.

    Custo: o número de inclinações cresce com o quadrado do número de amostras.
    """
    pares = est.parear(comparacao, teste)
    n = len(pares)

    if n < 3:
        return _regressao_vazia(
            n, "Passing-Bablok", "são necessárias ao menos 3 amostras pareadas"
        )

    inclinacoes = []
    deslocamento = 0  # inclinações abaixo de −1, usadas para deslocar a mediana

    for i in range(n):
        for j in range(i + 1, n):
            x_i, y_i = pares[i]
            x_j, y_j = pares[j]
            if x_i == x_j:
                continue  # pares com mesmo X não definem inclinação
            s = (y_j - y_i) / (x_j - x_i)
            if s == -1:
                continue  # descartado pelo procedimento original
            if s < -1:
                deslocamento += 1
            inclinacoes.append(s)

    total = len(inclinacoes)
    if total == 0:
        return _regressao_vazia(
            n,
            "Passing-Bablok",
            "não há pares com valores distintos no método de comparação",
        )

    inclinacoes.sort()
    inclinacao = _mediana_deslocada(inclinacoes, deslocamento)

    if inclinacao is None:
        return _regressao_vazia(
            n, "Passing-Bablok", "distribuição de inclinações não permite estimativa"
        )

    intercepto = est.mediana([y - inclinacao * x for x, y in pares])

    return {
        "metodo": "Passing-Bablok",
        "n": n,
        "inclinacao": inclinacao,
        "intercepto": intercepto,
        "atende_minimo_ep09": n >= MINIMO_AMOSTRAS_EP09,
        "observacao": None,
    }


def _mediana_deslocada(ordenadas: list[float], deslocamento: int) -> float | None:
    """Mediana deslocada de ``deslocamento`` posições, conforme Passing-Bablok."""
    total = len(ordenadas)

    if total % 2 == 1:
        indice = (total + 1) // 2 + deslocamento - 1  # converte de 1-based para 0-based
        if 0 <= indice < total:
            return ordenadas[indice]
        return None

    primeiro = total // 2 + deslocamento - 1
    segundo = primeiro + 1
    if 0 <= primeiro and segundo < total:
        return (ordenadas[primeiro] + ordenadas[segundo]) / 2
    return None


def _regressao_vazia(n: int, metodo: str, motivo: str) -> dict:
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
