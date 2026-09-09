"""Grau de concordância entre o método de comparação e o método em teste.

Três perguntas diferentes, três medidas diferentes:

1. **Concordância de Lin** — os pontos caem sobre a reta de identidade?
   Combina, num único coeficiente, o quanto os métodos se correlacionam
   (precisão) e o quanto a reta deles se afasta da diagonal perfeita (acurácia).
   Responde o que o coeficiente de correlação r não responde.

2. **Concordância analítica** — quantas amostras ficaram dentro do Erro Total
   permitido? É a leitura direta da especificação de qualidade, amostra a
   amostra, em vez de só olhar a média.

3. **Concordância clínica** — quantas amostras seriam interpretadas do mesmo
   jeito pelo médico? Uma diferença de 0,2 ng/dL pode ser irrelevante no meio da
   faixa e decisiva sobre o limite do intervalo de referência. É a única das três
   que fala a língua de quem lê o laudo.

Um método pode passar na primeira e falhar na terceira — e é a terceira que
gera retrabalho clínico.
"""

from __future__ import annotations

import math
from typing import Sequence

from . import especificacoes as espec
from . import estatistica as est

ABAIXO = "abaixo do intervalo"
DENTRO = "dentro do intervalo"
ACIMA = "acima do intervalo"


def lin(comparacao: Sequence[float], teste: Sequence[float]) -> dict:
    """Coeficiente de correlação de concordância de Lin (ρc).

    ρc = 2·s_xy / (s_x² + s_y² + (x̄ − ȳ)²)

    Decompõe-se em dois fatores, e a decomposição é o mais útil do resultado:

    - **ρ (precisão)**: o quanto os pontos formam uma reta.
    - **Cb (acurácia)**: o quanto essa reta coincide com a diagonal y = x.

    ρc = ρ × Cb. Quando ρ está alto e Cb baixo, os métodos concordam em
    tendência mas discordam em valor — exatamente o erro que o coeficiente de
    correlação sozinho esconde.

    Momentos calculados com denominador n, conforme a formulação original de Lin.
    """
    pares = est.parear(comparacao, teste)
    n = len(pares)

    if n < 2:
        return _lin_vazio(n, "são necessárias ao menos 2 amostras pareadas")

    media_x = sum(x for x, _ in pares) / n
    media_y = sum(y for _, y in pares) / n

    var_x = sum((x - media_x) ** 2 for x, _ in pares) / n
    var_y = sum((y - media_y) ** 2 for _, y in pares) / n
    cov_xy = sum((x - media_x) * (y - media_y) for x, y in pares) / n

    denominador = var_x + var_y + (media_x - media_y) ** 2
    if denominador == 0:
        return _lin_vazio(n, "todas as amostras têm o mesmo valor nos dois métodos")

    ccc = 2 * cov_xy / denominador

    if var_x == 0 or var_y == 0:
        precisao = None
        acuracia = None
    else:
        precisao = cov_xy / math.sqrt(var_x * var_y)
        acuracia = ccc / precisao if precisao not in (0, None) else None

    return {
        "n": n,
        "ccc": ccc,
        "componente_precisao": precisao,
        "componente_acuracia": acuracia,
        "classificacao": classificar_ccc(ccc),
        "observacao": None,
    }


def _lin_vazio(n: int, motivo: str) -> dict:
    return {
        "n": n,
        "ccc": None,
        "componente_precisao": None,
        "componente_acuracia": None,
        "classificacao": classificar_ccc(None),
        "observacao": motivo,
    }


def classificar_ccc(ccc: float | None) -> str:
    """Faixas de interpretação usuais para o coeficiente de Lin (McBride)."""
    if ccc is None:
        return "não calculável"
    if ccc < 0.90:
        return "fraca (ρc < 0,90)"
    if ccc < 0.95:
        return "moderada (0,90 ≤ ρc < 0,95)"
    if ccc < 0.99:
        return "substancial (0,95 ≤ ρc < 0,99)"
    return "quase perfeita (ρc ≥ 0,99)"


def razao_das_medias(comparacao: Sequence[float], teste: Sequence[float]) -> dict:
    """Razão entre a média do método em teste e a do método de comparação.

    É o erro sistemático do conjunto, resumido num número só, e é ele que se
    compara com o bias máximo do analito. ``desvio_pct`` é o que entra nessa
    comparação: a razão traduzida em quanto o método novo lê acima ou abaixo do
    antigo, em percentual.

        razão 1,0668  →  desvio +6,68%  →  compara com bias máximo 6,00%

    A razão bruta também vai no resultado, porque é o número que o laboratório
    reconhece do relatório do fabricante. Mas ela não se compara com nada: 1,0668
    ao lado de um limite de 6% não quer dizer coisa alguma.

    Há uma leitura alternativa — a média das diferenças percentuais amostra a
    amostra — que dá peso igual a cada concentração e costuma sair maior quando
    o viés é proporcional. Ela segue calculada em ``media_das_diferencas_pct``,
    porque a divergência entre as duas é informação, não ruído: quando elas se
    afastam muito, o erro depende da concentração e a razão sozinha esconde isso.
    """
    pares = est.parear(comparacao, teste)
    n = len(pares)

    if n == 0:
        return {
            "n": 0,
            "media_comparacao": None,
            "media_teste": None,
            "razao": None,
            "desvio_pct": None,
            "media_das_diferencas_pct": None,
            "diferenca_media": None,
            "desvio_padrao": None,
        }

    media_comparacao = sum(x for x, _ in pares) / n
    media_teste = sum(y for _, y in pares) / n
    diferencas = [y - x for x, y in pares]

    razao = media_teste / media_comparacao if media_comparacao != 0 else None
    desvio_pct = (razao - 1) * 100 if razao is not None else None

    percentuais = [((y - x) / x) * 100 for x, y in pares if x != 0]

    return {
        "n": n,
        "media_comparacao": media_comparacao,
        "media_teste": media_teste,
        "razao": razao,
        "desvio_pct": desvio_pct,
        "media_das_diferencas_pct": (sum(percentuais) / len(percentuais)) if percentuais else None,
        "diferenca_media": sum(diferencas) / n,
        "desvio_padrao": est.desvio_padrao(diferencas),
    }

def concordancia_analitica(
    comparacao: Sequence[float],
    teste: Sequence[float],
    limite: espec.LimiteQualidade,
    identificacoes: Sequence[str] | None = None,
) -> dict:
    """Percentual de amostras cuja diferença ficou dentro do Erro Total permitido.

    Avalia amostra a amostra, não a média. Um método pode ter erro sistemático
    médio de 1% e ainda assim ter 20% das amostras fora do limite, por dispersão
    — e é essa a informação que a média esconde.

    O limite é resolvido na concentração de cada amostra, o que faz valer
    automaticamente a regra do critério absoluto em concentrações baixas.
    """
    pares = est.parear(comparacao, teste)
    n = len(pares)
    nomes = list(identificacoes) if identificacoes else []

    dentro = 0
    discordantes = []
    nao_avaliadas = 0

    for indice, (x, y) in enumerate(pares):
        if x == 0:
            nao_avaliadas += 1
            continue

        resolvido = limite.aplicar(x)
        if not resolvido["definido"] or resolvido["limite_pct"] is None:
            nao_avaliadas += 1
            continue

        erro_pct = ((y - x) / x) * 100
        if abs(erro_pct) <= resolvido["limite_pct"]:
            dentro += 1
        else:
            discordantes.append(
                {
                    "identificacao": nomes[indice] if indice < len(nomes) else f"amostra {indice + 1}",
                    "valor_comparacao": x,
                    "valor_teste": y,
                    "erro_pct": erro_pct,
                    "limite_pct": resolvido["limite_pct"],
                    "tipo_limite": resolvido["tipo"],
                }
            )

    avaliadas = n - nao_avaliadas

    return {
        "n": n,
        "avaliadas": avaliadas,
        "nao_avaliadas": nao_avaliadas,
        "dentro_do_limite": dentro,
        "fora_do_limite": len(discordantes),
        "concordancia_pct": (dentro / avaliadas * 100) if avaliadas else None,
        "discordantes": discordantes,
    }


def classificar_no_intervalo(
    valor: float | None, inferior: float | None, superior: float | None
) -> str | None:
    """Situa um resultado em relação ao intervalo de referência."""
    if valor is None or inferior is None or superior is None:
        return None
    if valor < inferior:
        return ABAIXO
    if valor > superior:
        return ACIMA
    return DENTRO


def concordancia_clinica(
    comparacao: Sequence[float],
    teste: Sequence[float],
    limite_inferior: float | None,
    limite_superior: float | None,
    identificacoes: Sequence[str] | None = None,
    limite_inferior_teste: float | None = None,
    limite_superior_teste: float | None = None,
) -> dict:
    """Percentual de amostras que os dois métodos classificam do mesmo jeito.

    Classifica cada resultado como abaixo, dentro ou acima do intervalo de
    referência **do seu próprio método** e compara as classificações. É a tradução
    da diferença analítica para a consequência clínica: uma discordância aqui
    significa um paciente que seria considerado normal por um método e alterado
    pelo outro.

    Cada método tem o seu intervalo por uma razão prática: quando o laboratório
    troca de metodologia ele costuma trocar também o intervalo de referência que
    imprime no laudo. Avaliar os dois contra um intervalo só mediria uma
    discordância que na prática não chega ao paciente — ou esconderia uma que
    chega. ``limite_*_teste`` em branco significa "o mesmo intervalo dos dois
    lados", que é o caso de quem manteve o intervalo antigo.

    ``reclassificacoes`` lista cada discordância com as duas classificações, para
    o relatório mostrar em qual direção o método novo erra — se ele cria falsos
    alterados ou deixa de sinalizar alterações reais.
    """
    # Ou o método em teste tem intervalo próprio inteiro, ou usa o da
    # comparação. Preencher metade a partir de cada método classificaria contra
    # um intervalo que não existe em lugar nenhum — e sem ninguém perceber.
    metade_do_teste = (limite_inferior_teste is None) != (limite_superior_teste is None)
    if metade_do_teste:
        return {
            "n": 0,
            "avaliadas": 0,
            "concordantes": 0,
            "discordantes": 0,
            "concordancia_pct": None,
            "reclassificacoes": [],
            "intervalos_diferentes": False,
            "observacao": (
                "intervalo de referência do método em teste informado pela metade: "
                "informe os dois limites ou nenhum"
            ),
        }

    if limite_inferior_teste is None:
        limite_inferior_teste = limite_inferior
    if limite_superior_teste is None:
        limite_superior_teste = limite_superior

    faltando = (
        limite_inferior is None
        or limite_superior is None
        or limite_inferior_teste is None
        or limite_superior_teste is None
    )
    if faltando:
        return {
            "n": 0,
            "avaliadas": 0,
            "concordantes": 0,
            "discordantes": 0,
            "concordancia_pct": None,
            "reclassificacoes": [],
            "intervalos_diferentes": False,
            "observacao": "intervalo de referência não informado para um dos métodos",
        }

    invertido = (
        limite_inferior > limite_superior or limite_inferior_teste > limite_superior_teste
    )
    if invertido:
        return {
            "n": 0,
            "avaliadas": 0,
            "concordantes": 0,
            "discordantes": 0,
            "concordancia_pct": None,
            "reclassificacoes": [],
            "intervalos_diferentes": False,
            "observacao": "intervalo de referência inválido: o limite inferior é maior que o superior",
        }

    pares = est.parear(comparacao, teste)
    nomes = list(identificacoes) if identificacoes else []

    concordantes = 0
    reclassificacoes = []

    for indice, (x, y) in enumerate(pares):
        classe_comparacao = classificar_no_intervalo(x, limite_inferior, limite_superior)
        classe_teste = classificar_no_intervalo(y, limite_inferior_teste, limite_superior_teste)

        if classe_comparacao == classe_teste:
            concordantes += 1
        else:
            reclassificacoes.append(
                {
                    "identificacao": nomes[indice] if indice < len(nomes) else f"amostra {indice + 1}",
                    "valor_comparacao": x,
                    "valor_teste": y,
                    "classificacao_comparacao": classe_comparacao,
                    "classificacao_teste": classe_teste,
                }
            )

    n = len(pares)

    return {
        "n": n,
        "avaliadas": n,
        "concordantes": concordantes,
        "discordantes": len(reclassificacoes),
        "concordancia_pct": (concordantes / n * 100) if n else None,
        "reclassificacoes": reclassificacoes,
        "intervalos_diferentes": (
            limite_inferior != limite_inferior_teste
            or limite_superior != limite_superior_teste
        ),
        "intervalo_comparacao": (limite_inferior, limite_superior),
        "intervalo_teste": (limite_inferior_teste, limite_superior_teste),
        "observacao": None,
    }
