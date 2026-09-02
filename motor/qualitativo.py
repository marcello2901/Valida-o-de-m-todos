"""Módulo Qualitativo — testes com resultado categórico (reagente / não reagente).

Procedimento de referência: CLSI EP12 (avaliação de desempenho de testes
qualitativos pelo usuário).

A estatística aqui não tem nada a ver com a dos métodos quantitativos: não
existe CV nem viés. O que se avalia é a concordância com um método de referência
(ou com o estado clínico verdadeiro), resumida numa tabela 2×2.

Ponto de atenção clínico embutido no cálculo: sensibilidade e especificidade não
dependem da prevalência, mas **valor preditivo positivo e negativo dependem**.
Os VPP/VPN calculados aqui refletem a prevalência da amostra estudada, que
raramente é a da população atendida pelo laboratório. Por isso a função aceita
uma prevalência informada, e o relatório deve deixar claro qual foi usada.
"""

from __future__ import annotations

import math
from typing import Sequence

from . import estatistica as est


def tabela_contingencia(referencia: Sequence[bool], teste: Sequence[bool]) -> dict:
    """Monta a tabela 2×2 a partir de dois vetores de resultados positivos/negativos.

    Cada elemento deve ser algo que represente positivo (``True``) ou negativo
    (``False``). Pares em que qualquer um dos lados esteja ausente são
    descartados inteiros.
    """
    vp = fp = fn = vn = 0
    descartados = 0

    for r, t in zip(referencia, teste):
        r_bool = _para_booleano(r)
        t_bool = _para_booleano(t)
        if r_bool is None or t_bool is None:
            descartados += 1
            continue
        if r_bool and t_bool:
            vp += 1
        elif not r_bool and t_bool:
            fp += 1
        elif r_bool and not t_bool:
            fn += 1
        else:
            vn += 1

    return {
        "verdadeiros_positivos": vp,
        "falsos_positivos": fp,
        "falsos_negativos": fn,
        "verdadeiros_negativos": vn,
        "n": vp + fp + fn + vn,
        "descartados": descartados,
    }


def _para_booleano(valor) -> bool | None:
    """Interpreta as formas usuais de registrar um resultado qualitativo."""
    if isinstance(valor, bool):
        return valor
    if valor is None:
        return None
    if isinstance(valor, (int, float)) and not isinstance(valor, bool):
        if valor in (0, 1):
            return bool(valor)
        return None

    texto = str(valor).strip().lower()
    positivos = {
        "positivo",
        "pos",
        "p",
        "reagente",
        "r",
        "detectavel",
        "detectável",
        "sim",
        "s",
        "1",
        "true",
    }
    negativos = {
        "negativo",
        "neg",
        "n",
        "nao reagente",
        "não reagente",
        "nr",
        "indetectavel",
        "indetectável",
        "nao",
        "não",
        "0",
        "false",
    }

    if texto in positivos:
        return True
    if texto in negativos:
        return False
    return None


def desempenho(tabela: dict, prevalencia_pct: float | None = None) -> dict:
    """Indicadores de desempenho a partir da tabela 2×2, com IC 95% de Wilson.

    ``prevalencia_pct`` recalcula VPP e VPN para a prevalência informada (a da
    população que o laboratório atende). Sem ela, os valores preditivos refletem
    a prevalência da própria amostra estudada — que costuma ser enriquecida em
    positivos e, portanto, superestima o VPP.
    """
    vp = tabela["verdadeiros_positivos"]
    fp = tabela["falsos_positivos"]
    fn = tabela["falsos_negativos"]
    vn = tabela["verdadeiros_negativos"]
    n = tabela["n"]

    positivos_referencia = vp + fn
    negativos_referencia = vn + fp

    sensibilidade = _proporcao(vp, positivos_referencia)
    especificidade = _proporcao(vn, negativos_referencia)
    concordancia = _proporcao(vp + vn, n)

    resultado = {
        "n": n,
        "sensibilidade_pct": sensibilidade,
        "sensibilidade_ic95": est.intervalo_wilson(vp, positivos_referencia),
        "especificidade_pct": especificidade,
        "especificidade_ic95": est.intervalo_wilson(vn, negativos_referencia),
        "concordancia_pct": concordancia,
        "concordancia_ic95": est.intervalo_wilson(vp + vn, n),
        "vpp_pct": _proporcao(vp, vp + fp),
        "vpn_pct": _proporcao(vn, vn + fn),
        "prevalencia_amostra_pct": _proporcao(positivos_referencia, n),
        "prevalencia_usada_pct": None,
        "kappa": None,
        "kappa_ic95": None,
        "classificacao_kappa": classificar_kappa(None),
    }

    if (
        prevalencia_pct is not None
        and sensibilidade is not None
        and especificidade is not None
    ):
        preditivos = _valores_preditivos(sensibilidade, especificidade, prevalencia_pct)
        resultado["vpp_pct"] = preditivos["vpp_pct"]
        resultado["vpn_pct"] = preditivos["vpn_pct"]
        resultado["prevalencia_usada_pct"] = prevalencia_pct

    kappa = _kappa_cohen(vp, fp, fn, vn)
    resultado["kappa"] = kappa["valor"]
    resultado["kappa_ic95"] = kappa["ic95"]
    resultado["classificacao_kappa"] = classificar_kappa(kappa["valor"])

    return resultado


def _proporcao(numerador: int, denominador: int) -> float | None:
    if denominador <= 0:
        return None
    return (numerador / denominador) * 100


def _valores_preditivos(
    sensibilidade_pct: float, especificidade_pct: float, prevalencia_pct: float
) -> dict:
    """VPP e VPN recalculados para uma prevalência externa, via teorema de Bayes."""
    s = sensibilidade_pct / 100
    e = especificidade_pct / 100
    p = prevalencia_pct / 100

    denominador_vpp = s * p + (1 - e) * (1 - p)
    denominador_vpn = e * (1 - p) + (1 - s) * p

    return {
        "vpp_pct": (s * p / denominador_vpp) * 100 if denominador_vpp > 0 else None,
        "vpn_pct": (
            (e * (1 - p) / denominador_vpn) * 100 if denominador_vpn > 0 else None
        ),
    }


def _kappa_cohen(vp: int, fp: int, fn: int, vn: int) -> dict:
    """Kappa de Cohen: concordância além da esperada por acaso.

    Necessário porque a concordância bruta engana quando uma das categorias é
    rara: um teste que responde "negativo" para tudo acerta 98% num cenário de
    2% de prevalência, e ainda assim não tem valor nenhum. O kappa desconta essa
    concordância acidental.
    """
    n = vp + fp + fn + vn
    if n == 0:
        return {"valor": None, "ic95": None}

    concordancia_observada = (vp + vn) / n
    concordancia_esperada = (((vp + fn) * (vp + fp)) + ((fp + vn) * (fn + vn))) / (n**2)

    if concordancia_esperada >= 1:
        # Todos os resultados numa única categoria: kappa é indefinido.
        return {"valor": None, "ic95": None}

    kappa = (concordancia_observada - concordancia_esperada) / (
        1 - concordancia_esperada
    )

    erro_padrao = math.sqrt(
        concordancia_observada
        * (1 - concordancia_observada)
        / (n * (1 - concordancia_esperada) ** 2)
    )
    margem = est.Z_95_BILATERAL * erro_padrao

    return {
        "valor": kappa,
        "ic95": (max(-1.0, kappa - margem), min(1.0, kappa + margem)),
    }


def classificar_kappa(kappa: float | None) -> str:
    """Interpretação usual da força de concordância (escala de Landis & Koch)."""
    if kappa is None:
        return "não calculável"
    if kappa < 0:
        return "pior que o acaso (κ < 0)"
    if kappa <= 0.20:
        return "leve (0,00–0,20)"
    if kappa <= 0.40:
        return "razoável (0,21–0,40)"
    if kappa <= 0.60:
        return "moderada (0,41–0,60)"
    if kappa <= 0.80:
        return "substancial (0,61–0,80)"
    return "quase perfeita (0,81–1,00)"
