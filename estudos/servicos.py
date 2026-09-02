"""Ponte entre os dados guardados e o motor de cálculo.

Este módulo faz uma coisa só: traduzir. Lê um estudo do banco, converte para o
formato que o motor entende, roda o cálculo e devolve o resultado pronto para a
tela e para o relatório.

Nenhuma estatística acontece aqui — ela toda vive em ``motor/``, que não sabe o
que é Django nem banco de dados. Essa separação é o que permite auditar o
cálculo isoladamente: se alguém questionar um número do relatório, a resposta
está num módulo testável de Python puro, não espalhada por telas.
"""

from __future__ import annotations

from decimal import Decimal

from motor import comparabilidade as comp
from motor import concordancia as conc
from motor import especificacoes as espec
from motor import graficos as graf
from motor import precisao as prec
from motor import qualitativo as qual
from motor import veredito as ver

from contas.models import Assinatura


def _decimal_para_float(valor) -> float | None:
    if valor is None:
        return None
    return float(valor) if isinstance(valor, (Decimal, int, float)) else None


def montar_especificacao(especificacao) -> espec.EspecificacaoQualidade:
    """Converte a especificação guardada no banco para o objeto do motor."""
    return espec.EspecificacaoQualidade(
        erro_total=espec.LimiteQualidade(
            valor_pct=_decimal_para_float(especificacao.erro_total_maximo_pct),
            referencia_pct=especificacao.erro_total_referencia,
            limiar_absoluto=_decimal_para_float(especificacao.erro_total_limiar_absoluto),
            valor_absoluto=_decimal_para_float(especificacao.erro_total_maximo_absoluto),
            referencia_absoluto=especificacao.erro_total_referencia_absoluto,
        ),
        bias=espec.LimiteQualidade(
            valor_pct=_decimal_para_float(especificacao.bias_maximo_pct),
            referencia_pct=especificacao.bias_referencia,
            limiar_absoluto=_decimal_para_float(especificacao.bias_limiar_absoluto),
            valor_absoluto=_decimal_para_float(especificacao.bias_maximo_absoluto),
            referencia_absoluto=especificacao.bias_referencia_absoluto,
        ),
        imprecisao_por_nivel={
            limite.nivel: espec.LimiteQualidade(
                valor_pct=_decimal_para_float(limite.maximo_pct),
                referencia_pct=limite.referencia,
            )
            for limite in especificacao.limites_imprecisao.all()
        },
        nivel_significancia=_decimal_para_float(especificacao.nivel_significancia) or 0.05,
    )


def _pares_de_comparacao(estudo):
    """Amostras pareadas não excluídas, na ordem de cadastro."""
    amostras = estudo.amostras_comparacao.filter(excluida=False).order_by("identificacao")
    return (
        [float(a.valor_comparacao) for a in amostras],
        [float(a.valor_teste) for a in amostras],
        [a.identificacao for a in amostras],
    )


def calcular_comparabilidade(estudo, especificacao) -> dict:
    """Todas as medidas do estudo de comparabilidade."""
    x, y, nomes = _pares_de_comparacao(estudo)

    if not x:
        return {
            "tem_dados": False,
            "n": 0,
            "motivo": "nenhuma amostra pareada cadastrada",
        }

    deming = comp.deming(x, y)
    resultado = {
        "tem_dados": True,
        "n": len(x),
        "motivo": None,
        "identificacoes": nomes,
        "valores_comparacao": x,
        "valores_teste": y,
        "deming": deming,
        "passing_bablok": comp.passing_bablok(x, y),
        "regressao": comp.regressao_linear(x, y),
        "bland_altman": comp.bland_altman(x, y),
        "lin": conc.lin(x, y),
        "erro_sistematico": conc.erro_sistematico_medio(x, y),
        "analitica": conc.concordancia_analitica(x, y, especificacao.erro_total, nomes),
    }

    mensurando = estudo.mensurando
    resultado["clinica"] = conc.concordancia_clinica(
        x,
        y,
        _decimal_para_float(mensurando.referencia_inferior),
        _decimal_para_float(mensurando.referencia_superior),
        nomes,
    )

    # Marca quais amostras ficaram fora do erro total, para os gráficos.
    fora = {d["identificacao"] for d in resultado["analitica"]["discordantes"]}
    resultado["fora_do_limite"] = [nome in fora for nome in nomes]

    return resultado


def calcular_precisao(estudo) -> list[dict]:
    """Estatística de precisão de cada nível de controle do estudo."""
    resultados = []

    for nivel in estudo.niveis.all().select_related("controle"):
        corridas: dict[int, list[float]] = {}
        for replica in nivel.replicas.filter(excluida=False).order_by("corrida", "sequencia"):
            corridas.setdefault(replica.corrida, []).append(float(replica.valor))

        agrupadas = [corridas[chave] for chave in sorted(corridas)]
        estatistica = prec.avaliar_precisao(agrupadas, estudo.desenho_precisao)

        # Concentração usada para resolver limite percentual contra absoluto:
        # a declarada pelo fabricante quando houver, senão a média medida.
        concentracao = _decimal_para_float(nivel.concentracao_declarada)
        if concentracao is None:
            concentracao = estatistica["media"]

        resultados.append(
            {
                "nivel": nivel,
                "numero": nivel.numero,
                "concentracao": concentracao,
                "estatistica": estatistica,
                "valores_em_ordem": [valor for corrida in agrupadas for valor in corrida],
            }
        )

    return resultados


def calcular_qualitativo(estudo) -> dict:
    """Desempenho do método qualitativo contra o resultado de referência."""
    amostras = estudo.amostras_qualitativas.all().order_by("identificacao")

    if not amostras:
        return {"tem_dados": False, "motivo": "nenhuma amostra qualitativa cadastrada"}

    tabela = qual.tabela_contingencia(
        [a.resultado_referencia for a in amostras],
        [a.resultado_teste for a in amostras],
    )
    return {
        "tem_dados": True,
        "motivo": None,
        "tabela": tabela,
        "desempenho": qual.desempenho(tabela),
    }


def calcular(estudo) -> dict:
    """Executa o estudo inteiro e devolve tudo que a tela e o relatório precisam.

    O módulo efetivamente usado é o menor entre o que o estudo declara e o que o
    laboratório tem contratado hoje. Um estudo criado sob o pacote completo não
    volta a calcular Erro Total se a assinatura caducou — o que o cliente vê
    corresponde ao que ele paga, sempre.
    """
    especificacao = montar_especificacao(estudo.especificacao)
    modulo = _modulo_efetivo(estudo)

    if estudo.tipo == estudo.QUALITATIVO:
        return {
            "estudo": estudo,
            "tipo": estudo.QUALITATIVO,
            "modulo_efetivo": modulo,
            "qualitativo": calcular_qualitativo(estudo),
            "especificacao": especificacao,
            "pendencias_especificacao": especificacao.pendencias(),
        }

    precisao_por_nivel = calcular_precisao(estudo)
    comparabilidade = calcular_comparabilidade(estudo, especificacao)

    inclinacao = comparabilidade.get("deming", {}).get("inclinacao") if comparabilidade["tem_dados"] else None
    intercepto = comparabilidade.get("deming", {}).get("intercepto") if comparabilidade["tem_dados"] else None

    entradas = []
    for item in precisao_por_nivel:
        bias = comp.bias_no_nivel(inclinacao, intercepto, item["concentracao"] or 0)
        item["bias"] = bias
        entradas.append(
            {
                "nivel": item["numero"],
                "concentracao": item["concentracao"],
                "cv_pct": item["estatistica"]["cv_aplicavel"],
                "bias_pct": bias["bias_pct"],
            }
        )

    veredito = ver.avaliar_estudo(modulo, especificacao, entradas)

    # Cola o veredito de cada nível ao seu bloco de precisão, para a tela não
    # precisar cruzar duas listas por índice.
    por_numero = {a["nivel"]: a for a in veredito["niveis"]}
    for item in precisao_por_nivel:
        item["avaliacao"] = por_numero.get(item["numero"])

    return {
        "estudo": estudo,
        "tipo": estudo.QUANTITATIVO,
        "modulo_efetivo": modulo,
        "especificacao": especificacao,
        "pendencias_especificacao": especificacao.pendencias(),
        "precisao": precisao_por_nivel,
        "comparabilidade": comparabilidade,
        "veredito": veredito,
        "graficos": _graficos(estudo, precisao_por_nivel, comparabilidade),
        "avisos": _avisos(estudo, precisao_por_nivel, comparabilidade),
    }


def _modulo_efetivo(estudo) -> str:
    """O menor entre o módulo declarado no estudo e o contratado hoje."""
    laboratorio = estudo.laboratorio
    if laboratorio.pode_usar(estudo.modulo):
        return estudo.modulo

    ativos = laboratorio.modulos_ativos()
    if Assinatura.COMPLETO in ativos:
        return Assinatura.COMPLETO
    for modulo in (Assinatura.PRECISAO, Assinatura.COMPARABILIDADE):
        if modulo in ativos:
            return modulo
    return ""


def _graficos(estudo, precisao_por_nivel, comparabilidade) -> dict:
    unidade = estudo.mensurando.unidade_medida
    saida = {"regressao": None, "bland_altman": None, "levey_jennings": []}

    if comparabilidade["tem_dados"]:
        x = comparabilidade["valores_comparacao"]
        y = comparabilidade["valores_teste"]
        nomes = comparabilidade["identificacoes"]
        fora = comparabilidade["fora_do_limite"]
        deming = comparabilidade["deming"]
        bland = comparabilidade["bland_altman"]

        saida["regressao"] = graf.grafico_regressao(
            x, y, deming["inclinacao"], deming["intercepto"], fora, nomes, unidade,
            titulo="Comparação de métodos — regressão de Deming",
        )
        saida["bland_altman"] = graf.grafico_bland_altman(
            x, y, bland["vies"], bland["limite_inferior"], bland["limite_superior"],
            fora, nomes, unidade,
        )

    for item in precisao_por_nivel:
        estatistica = item["estatistica"]
        saida["levey_jennings"].append(
            {
                "numero": item["numero"],
                "svg": graf.grafico_levey_jennings(
                    item["valores_em_ordem"],
                    media=estatistica["media"],
                    desvio_padrao=estatistica.get("desvio_padrao_intermediaria")
                    or estatistica.get("desvio_padrao_repetibilidade"),
                    unidade=unidade,
                    titulo=f"Precisão — nível {item['numero']} — carta de Levey-Jennings",
                ),
            }
        )

    return saida


def _avisos(estudo, precisao_por_nivel, comparabilidade) -> list[str]:
    """Ressalvas que precisam aparecer no relatório, não apenas nos bastidores."""
    avisos: list[str] = []

    for item in precisao_por_nivel:
        for aviso in item["estatistica"]["avisos"]:
            texto = f"Nível {item['numero']}: {aviso}"
            if texto not in avisos:
                avisos.append(texto)

    if comparabilidade["tem_dados"]:
        deming = comparabilidade["deming"]
        if not deming["atende_minimo_ep09"]:
            avisos.append(
                f"O estudo de comparabilidade tem {comparabilidade['n']} amostras. "
                f"O procedimento de referência (CLSI EP09) pede pelo menos "
                f"{comp.MINIMO_AMOSTRAS_EP09}, distribuídas ao longo da faixa analítica."
            )
        regressao = comparabilidade["regressao"]
        if regressao["amplitude_adequada"] is False:
            avisos.append(
                "O coeficiente de correlação ficou abaixo de 0,975: as concentrações "
                "estudadas cobrem uma faixa estreita demais para a regressão ser conclusiva."
            )
        if comparabilidade["clinica"]["observacao"]:
            avisos.append(
                f"Concordância clínica não avaliada — {comparabilidade['clinica']['observacao']}."
            )

    for nivel in estudo.niveis.all():
        if nivel.replicas.filter(excluida=True).exists():
            quantidade = nivel.replicas.filter(excluida=True).count()
            avisos.append(
                f"Nível {nivel.numero}: {quantidade} réplica(s) excluída(s) do cálculo, "
                "com justificativa registrada."
            )

    return avisos
