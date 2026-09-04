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

from decimal import Decimal, InvalidOperation

from django.db import models, transaction
from django.utils import timezone

from motor import comparabilidade as comp
from motor import concordancia as conc
from motor import especificacoes as espec
from motor import graficos as graf
from motor import precisao as prec
from motor import qualitativo as qual
from motor import veredito as ver

from contas.models import Assinatura, RegistroAuditoria

from .models import Veredito


def _decimal_para_float(valor) -> float | None:
    if valor is None:
        return None
    return float(valor) if isinstance(valor, (Decimal, int, float)) else None


def montar_especificacao(especificacao) -> espec.EspecificacaoQualidade:
    """Converte a especificação guardada no banco para o objeto do motor."""
    return especificacao.para_o_motor()


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

    comparacao_inferior, comparacao_superior = estudo.intervalo_de_comparacao()
    teste_inferior, teste_superior = estudo.intervalo_de_teste()
    resultado["clinica"] = conc.concordancia_clinica(
        x,
        y,
        _decimal_para_float(comparacao_inferior),
        _decimal_para_float(comparacao_superior),
        nomes,
        limite_inferior_teste=_decimal_para_float(teste_inferior),
        limite_superior_teste=_decimal_para_float(teste_superior),
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
        estatistica = prec.avaliar_precisao(
            agrupadas, estudo.desenho_precisao, nivel.alvo_do_bias()
        )

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
                "origem_do_alvo": nivel.origem_do_alvo(),
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
        bias, origem = _bias_do_nivel(item, inclinacao, intercepto)
        item["bias"] = bias
        item["origem_do_bias"] = origem
        entradas.append(
            {
                "nivel": item["numero"],
                "concentracao": item["concentracao"],
                "cv_pct": item["estatistica"]["cv_aplicavel"],
                "bias_pct": bias["relativo_pct"] if bias["avaliavel"] else None,
            }
        )

    veredito = ver.avaliar_estudo(modulo, especificacao, entradas)

    # Cola o veredito de cada nível ao seu bloco de precisão, para a tela não
    # precisar cruzar duas listas por índice.
    por_numero = {a["nivel"]: a for a in veredito["niveis"]}
    for item in precisao_por_nivel:
        avaliacao = por_numero.get(item["numero"])
        item["avaliacao"] = avaliacao
        item["medidor_pct"] = _proporcao_do_limite(item["estatistica"]["cv_aplicavel"], avaliacao)

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


# Nomes das duas origens possíveis do bias, para a tela e o relatório dizerem
# contra o que a exatidão foi medida.
BIAS_INTERLABORATORIAL = "interlaboratorial"
BIAS_REGRESSAO = "regressao"
BIAS_AUSENTE = ""


def _bias_do_nivel(item, inclinacao, intercepto):
    """De onde sai o bias de um nível de controle, nesta ordem de preferência.

    1. **Média do estudo interlaboratorial**, quando informada. É a comparação
       direta entre a média das réplicas e a média do mesmo lote no grupo de
       pares, e é o que o laboratório reconhece como exatidão do controle.
    2. **Reta de regressão da comparabilidade**, na concentração do nível.
       Só entra quando o alvo interlaboratorial não foi informado — sem essa
       reserva, um estudo de comparabilidade puro (que não tem réplicas de
       controle, nem alvo) ficaria sem exatidão nenhuma e o módulo não avaliaria
       coisa alguma.
    3. Nenhuma das duas: a exatidão não é avaliada e o nível sai INDETERMINADO.

    A origem escolhida acompanha o resultado, porque as duas respondem perguntas
    diferentes — o alvo do grupo de pares mede o controle, a reta mede a
    concordância com o método antigo — e um relatório que não diz qual usou não
    pode ser conferido.
    """
    do_alvo = item["estatistica"].get("bias") or {}
    if do_alvo.get("avaliavel"):
        return do_alvo, BIAS_INTERLABORATORIAL

    pela_reta = comp.bias_no_nivel(inclinacao, intercepto, item["concentracao"] or 0)
    if pela_reta.get("bias_pct") is not None:
        return (
            {
                "avaliavel": True,
                "media_obtida": pela_reta.get("valor_estimado"),
                "media_alvo": pela_reta.get("nivel"),
                "absoluto": pela_reta.get("bias"),
                "relativo_pct": pela_reta.get("bias_pct"),
                "motivo": None,
            },
            BIAS_REGRESSAO,
        )

    return do_alvo, BIAS_AUSENTE


def retrato(estudo) -> dict:
    """Versão do cálculo que pode ser congelada em JSON dentro do veredito.

    Tira do resultado o que não é dado: a instância do estudo, os SVG dos
    gráficos (que o relatório redesenha a partir dos mesmos números) e a
    especificação, guardada aqui em forma legível para o auditor que abrir o
    retrato daqui a cinco anos e precisar saber contra qual limite se decidiu.

    O retrato é o que o relatório imprime. Recalcular na hora de imprimir
    poderia devolver outro número — a ficha do analito pode ter mudado depois
    da assinatura — e ninguém assinou esse outro número.
    """
    resultado = calcular(estudo)
    especificacao = resultado["especificacao"]

    congelado = {
        chave: valor
        for chave, valor in resultado.items()
        if chave not in ("estudo", "graficos", "especificacao", "precisao")
    }
    congelado["estudo"] = estudo.identificacao
    congelado["especificacao"] = _especificacao_legivel(especificacao)
    congelado["precisao"] = [
        {**bloco, "nivel": str(bloco["nivel"])} for bloco in resultado.get("precisao", [])
    ]
    return congelado


def _especificacao_legivel(especificacao) -> dict:
    """Os limites vigentes no momento do cálculo, com as respectivas fontes."""

    def limite(item):
        if item is None:
            return None
        return {
            "valor_pct": item.valor_pct,
            "referencia": item.referencia_pct,
            "valor_absoluto": item.valor_absoluto,
            "limiar_absoluto": item.limiar_absoluto,
            "referencia_absoluto": item.referencia_absoluto,
        }

    return {
        "erro_total": limite(especificacao.erro_total),
        "bias": limite(especificacao.bias),
        "imprecisao_por_nivel": {
            str(nivel): limite(item) for nivel, item in especificacao.imprecisao_por_nivel.items()
        },
        "nivel_significancia": especificacao.nivel_significancia,
    }


def _limite_de_imprecisao(avaliacao) -> float | None:
    """O limite de CV aplicado a este nível, lido da avaliação já resolvida."""
    if not avaliacao:
        return None
    for indicador in avaliacao["indicadores"]:
        if indicador["indicador"] == "imprecisão":
            return indicador["limite_pct"]
    return None


def _proporcao_do_limite(cv_pct, avaliacao) -> int:
    """Quanto do limite de imprecisão o CV observado ocupa, em percentual.

    Serve à barra do painel lateral. Passa de 100 quando o CV estoura o limite —
    a barra satura, mas o número ao lado continua dizendo a verdade.
    """
    if cv_pct is None or not avaliacao:
        return 0
    for indicador in avaliacao["indicadores"]:
        if indicador["indicador"] == "imprecisão" and indicador["limite_pct"]:
            return min(100, round(cv_pct / indicador["limite_pct"] * 100))
    return 0


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

        # A reta desenhada é a de mínimos quadrados, com a de identidade ao
        # lado: é a comparação que o olho faz. Deming e Passing-Bablok ficam na
        # tabela — mais adequadas por admitirem erro nos dois eixos, e por isso
        # é contra elas que o bias por nível é estimado, não contra esta.
        regressao = comparabilidade["regressao"]
        saida["regressao"] = graf.grafico_regressao(
            x, y, regressao["inclinacao"], regressao["intercepto"], fora, nomes, unidade,
            titulo="Comparação de métodos — regressão linear simples",
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
                    desvio_padrao=estatistica.get("desvio_padrao"),
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

        # O CV avaliado é a dispersão dentro da corrida. Quando ele cabe no
        # limite e a precisão intermediária não cabe, o método passa no papel e
        # falha na rotina — o relatório precisa dizer isso.
        alerta = prec.alerta_precisao_intermediaria(
            item["estatistica"], _limite_de_imprecisao(item.get("avaliacao"))
        )
        if alerta:
            avisos.append(f"Nível {item['numero']}: {alerta}")

        if item.get("origem_do_bias") == BIAS_REGRESSAO:
            avisos.append(
                f"Nível {item['numero']}: a média do estudo interlaboratorial não foi "
                "informada. O bias deste nível foi estimado pela reta de regressão da "
                "comparabilidade, que mede concordância com o método antigo — não "
                "exatidão contra o grupo de pares."
            )
        elif item.get("origem_do_bias") == BIAS_AUSENTE:
            avisos.append(
                f"Nível {item['numero']}: exatidão não avaliada — a média do estudo "
                "interlaboratorial (e-Lab, Unity, fleet) não foi informada."
            )

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


# --- Ações que mudam o estado do estudo -------------------------------------
#
# Duas ações separadas de propósito, porque são dois atos distintos: calcular é
# técnico e reversível; liberar é a assinatura do responsável técnico e vira
# registro de qualidade do laboratório. Juntar as duas num botão só faria a
# assinatura acontecer por descuido.


class AcaoRecusada(Exception):
    """A ação não pode ser executada no estado atual do estudo."""


def concluir(estudo, usuario):
    """Congela o cálculo do estudo num veredito.

    A partir daqui a tela e o relatório passam a mostrar este retrato, não um
    recálculo. É o que garante que o número assinado hoje continue sendo o
    número impresso daqui a cinco anos, mesmo que a ficha do analito mude ou que
    o motor de cálculo evolua.

    Recalcular continua permitido enquanto ninguém assinou: o laboratório
    corrige uma réplica digitada errada e calcula de novo. Depois da liberação,
    não — aí o caminho é cancelar e abrir outro estudo.
    """
    if estudo.situacao == estudo.LIBERADO:
        raise AcaoRecusada(
            "Este estudo já foi liberado pelo responsável técnico. Um relatório "
            "assinado não é recalculado — cancele o estudo e abra outro."
        )
    if estudo.situacao == estudo.CANCELADO:
        raise AcaoRecusada("Estudo cancelado não produz veredito.")

    andamento = estudo.progresso()
    if not andamento["iniciado"]:
        raise AcaoRecusada(
            "Não há dados lançados neste estudo. Lance as réplicas de controle "
            "ou as amostras pareadas antes de calcular."
        )

    resultado = retrato(estudo)
    anterior = getattr(estudo, "veredito", None)

    with transaction.atomic():
        if anterior is not None:
            anterior.delete()
        veredito = Veredito.objects.create(
            estudo=estudo,
            resultado=resultado["veredito"]["status"],
            detalhamento=resultado,
        )
        estudo.situacao = estudo.CONCLUIDO
        estudo.data_conclusao = timezone.localdate()
        estudo.save(update_fields=["situacao", "data_conclusao"])

        RegistroAuditoria.objects.create(
            laboratorio=estudo.laboratorio,
            usuario=usuario if usuario.is_authenticated else None,
            acao="recalculou o estudo" if anterior else "calculou o estudo",
            objeto=estudo.identificacao,
            detalhe={
                "resultado": veredito.resultado,
                "versao_motor": veredito.versao_motor,
                "resultado_anterior": anterior.resultado if anterior else None,
                "replicas": andamento["precisao_feita"],
                "amostras": andamento["comparacao_feita"],
                "avisos": resultado.get("avisos", []),
            },
        )

    return veredito


def liberar(estudo, usuario):
    """Assina o veredito congelado, transformando-o em registro de qualidade.

    Reprovado e indeterminado também se assinam: um estudo que falhou é um
    resultado, e escondê-lo seria pior do que registrá-lo. O que a assinatura
    afirma é que aquele cálculo, com aqueles dados, foi conferido — não que o
    método passou.
    """
    if not usuario.pode_assinar_relatorio():
        raise AcaoRecusada(
            "Só o responsável técnico assina um relatório de validação."
        )
    if estudo.situacao == estudo.LIBERADO:
        raise AcaoRecusada("Este estudo já foi liberado.")

    veredito = getattr(estudo, "veredito", None)
    if veredito is None:
        raise AcaoRecusada("Calcule o estudo antes de liberar o relatório.")

    with transaction.atomic():
        veredito.liberado_por = usuario
        veredito.liberado_em = timezone.now()
        veredito.save(update_fields=["liberado_por", "liberado_em"])

        estudo.situacao = estudo.LIBERADO
        estudo.save(update_fields=["situacao"])

        RegistroAuditoria.objects.create(
            laboratorio=estudo.laboratorio,
            usuario=usuario,
            acao="liberou o relatório",
            objeto=estudo.identificacao,
            detalhe={
                "resultado": veredito.resultado,
                "versao_motor": veredito.versao_motor,
                "calculado_em": veredito.calculado_em.isoformat(),
            },
        )

    return veredito


# --- Grade de lançamento de réplicas ----------------------------------------
#
# A digitação é o maior atrito do estudo de precisão: são dezenas de números,
# nível por nível. A grade existe para que isso aconteça numa tela só, com as
# colunas lado a lado, em vez de um formulário por réplica no painel
# administrativo.

REPLICAS_POR_COLUNA = 30


def _posicao_para_corrida(posicao: int, desenho: str) -> tuple[int, int]:
    """Converte a linha da grade em (corrida, sequência).

    No desenho de múltiplas corridas cada bloco de 5 linhas é uma corrida — é o
    desenho de referência do EP15, e é assim que o laboratório pipeta. Em corrida
    única todas as linhas pertencem à corrida 1.
    """
    if desenho == prec.DESENHO_CORRIDA_UNICA:
        return 1, posicao
    tamanho = prec.MINIMO_REPLICAS_POR_CORRIDA
    return (posicao - 1) // tamanho + 1, (posicao - 1) % tamanho + 1


def montar_grade(estudo) -> list[dict]:
    """Uma coluna por nível de controle, cada uma com 30 linhas de réplica.

    Réplicas excluídas com justificativa aparecem travadas: elas são registro do
    que foi descartado e por quê, e a grade não pode apagá-las por descuido.
    """
    colunas = []
    for nivel in estudo.niveis.select_related("controle").order_by("numero"):
        existentes = {
            (r.corrida, r.sequencia): r for r in nivel.replicas.all()
        }
        linhas = []
        for posicao in range(1, REPLICAS_POR_COLUNA + 1):
            corrida, sequencia = _posicao_para_corrida(posicao, estudo.desenho_precisao)
            replica = existentes.get((corrida, sequencia))
            linhas.append(
                {
                    "posicao": posicao,
                    "corrida": corrida,
                    "sequencia": sequencia,
                    "abre_corrida": sequencia == 1,
                    "campo": f"nivel_{nivel.pk}_{posicao}",
                    "valor": replica.valor if replica else None,
                    "travada": bool(replica and replica.excluida),
                    "justificativa": replica.justificativa_exclusao if replica else "",
                }
            )
        colunas.append({"nivel": nivel, "linhas": linhas})
    return colunas


def salvar_grade(estudo, dados) -> dict:
    """Grava a grade inteira de uma vez.

    Campo em branco apaga a réplica daquela posição; campo preenchido cria ou
    atualiza. Valores ilegíveis não são descartados em silêncio — voltam na
    lista de erros com a posição, para o usuário ver onde errou a digitação.

    Campo **ausente** é diferente de campo em branco, e a distinção não é
    detalhe: um envio parcial — formulário truncado, requisição malformada —
    não pode significar "apague tudo o que não veio". Só a posição que chegou no
    envio é considerada.
    """
    from .models import Replica

    erros: list[str] = []
    gravadas = 0
    apagadas = 0

    with transaction.atomic():
        for nivel in estudo.niveis.all():
            for posicao in range(1, REPLICAS_POR_COLUNA + 1):
                corrida, sequencia = _posicao_para_corrida(posicao, estudo.desenho_precisao)
                existente = nivel.replicas.filter(corrida=corrida, sequencia=sequencia).first()

                if existente and existente.excluida:
                    continue  # Registro de descarte: a grade não mexe.

                campo = f"nivel_{nivel.pk}_{posicao}"
                if campo not in dados:
                    continue

                bruto = (dados.get(campo) or "").strip()

                if not bruto:
                    if existente:
                        existente.delete()
                        apagadas += 1
                    continue

                try:
                    valor = Decimal(bruto.replace(",", "."))
                except (InvalidOperation, ValueError):
                    erros.append(
                        f"Nível {nivel.numero}, réplica {posicao}: "
                        f"“{bruto}” não é um número."
                    )
                    continue

                if existente:
                    if existente.valor != valor:
                        existente.valor = valor
                        existente.save(update_fields=["valor"])
                        gravadas += 1
                else:
                    Replica.objects.create(
                        nivel=nivel, corrida=corrida, sequencia=sequencia, valor=valor
                    )
                    gravadas += 1

        if erros:
            transaction.set_rollback(True)

    return {"gravadas": gravadas, "apagadas": apagadas, "erros": erros}


def acrescentar_nivel(estudo, controle_id: str, media_alvo: str = "") -> str:
    """Cria a próxima coluna da grade a partir de um material de controle.

    Devolve mensagem de erro, ou string vazia em caso de sucesso.
    """
    from catalogo.models import Controle

    from .models import NivelEstudo

    controle = Controle.do_estudo(estudo.sistema_teste, estudo.mensurando).filter(
        pk=controle_id
    ).first()
    if controle is None:
        return (
            "Material de controle não encontrado para este sistema analítico e "
            "este analito."
        )
    if estudo.niveis.filter(controle=controle).exists():
        return "Esse material de controle já é uma coluna deste estudo."

    proximo = (estudo.niveis.aggregate(models.Max("numero"))["numero__max"] or 0) + 1

    alvo = None
    if media_alvo.strip():
        try:
            alvo = Decimal(media_alvo.strip().replace(",", "."))
        except (InvalidOperation, ValueError):
            return f"“{media_alvo}” não é um número válido para a média interlaboratorial."

    NivelEstudo.objects.create(
        estudo=estudo,
        numero=proximo,
        controle=controle,
        concentracao_declarada=controle.valor_alvo,
        media_interlaboratorial=alvo,
    )
    return ""


# --- Grade de lançamento de amostras pareadas -------------------------------
#
# Mesma ideia da grade de réplicas, com três campos por linha em vez de um. Já
# nasce com o mínimo do EP09 — 40 amostras — para o laboratório saber de saída
# quanto o procedimento pede, em vez de descobrir no fim que faltou.

AMOSTRAS_POR_PISTA = 20
PASSO_DE_LINHAS = 10
MINIMO_AMOSTRAS_GRADE = comp.MINIMO_AMOSTRAS_EP09


def _identificacao_sugerida(posicao: int) -> str:
    return f"AM-{posicao:03d}"


def montar_grade_amostras(estudo, linhas_pedidas: int = 0) -> dict:
    """Linhas de amostra pareada, repartidas em pistas de 20.

    As amostras já lançadas ocupam as primeiras posições, na ordem em que estão
    cadastradas; o resto vem em branco. O número de linhas nunca encolhe abaixo
    do que já foi digitado — apagar dado por causa de um número na barra de
    endereço seria inaceitável.
    """
    existentes = list(estudo.amostras_comparacao.order_by("identificacao"))
    total = max(comp.MINIMO_AMOSTRAS_EP09, len(existentes), linhas_pedidas)

    linhas = []
    for posicao in range(1, total + 1):
        amostra = existentes[posicao - 1] if posicao <= len(existentes) else None
        linhas.append(
            {
                "posicao": posicao,
                "amostra": amostra,
                "identificacao": amostra.identificacao if amostra else "",
                "sugestao": _identificacao_sugerida(posicao),
                "comparacao": amostra.valor_comparacao if amostra else None,
                "teste": amostra.valor_teste if amostra else None,
                "travada": bool(amostra and amostra.excluida),
                "justificativa": amostra.justificativa_exclusao if amostra else "",
            }
        )

    pistas = [
        linhas[inicio : inicio + AMOSTRAS_POR_PISTA]
        for inicio in range(0, len(linhas), AMOSTRAS_POR_PISTA)
    ]
    return {"total": total, "pistas": pistas, "minimo": comp.MINIMO_AMOSTRAS_EP09}


def _numero(bruto: str):
    """Converte texto digitado em Decimal, aceitando vírgula decimal."""
    return Decimal(bruto.replace(",", "."))


def salvar_grade_amostras(estudo, dados, total: int) -> dict:
    """Grava a grade de amostras pareadas de uma vez.

    Regras que valem a pena estar explícitas:

    - Linha com os dois valores em branco apaga a amostra daquela posição.
    - Linha com **um** valor só é erro, não meia amostra: um par incompleto não
      entra em regressão nenhuma, e gravá-lo silenciosamente deixaria o estudo
      com uma amostra que não conta e ninguém sabe por quê.
    - Identificação em branco recebe a sugerida (AM-007). Ninguém deveria ter de
      digitar quarenta identificadores sequenciais à mão.
    - Identificação repetida é recusada antes de o banco reclamar, com a
      mensagem dizendo quais linhas colidem.
    """
    from .models import AmostraComparacao

    erros: list[str] = []
    a_gravar: list[dict] = []
    a_apagar: list = []
    vistos: dict[str, int] = {}

    existentes = list(estudo.amostras_comparacao.order_by("identificacao"))

    for posicao in range(1, total + 1):
        amostra = existentes[posicao - 1] if posicao <= len(existentes) else None
        if amostra and amostra.excluida:
            continue  # Registro de descarte: a grade não mexe.

        campo_comp = f"amostra_{posicao}_comparacao"
        campo_teste = f"amostra_{posicao}_teste"
        if campo_comp not in dados and campo_teste not in dados:
            continue  # Envio parcial: o que não veio não é "apague".

        bruto_comp = (dados.get(campo_comp) or "").strip()
        bruto_teste = (dados.get(campo_teste) or "").strip()
        identificacao = (dados.get(f"amostra_{posicao}_id") or "").strip()

        if not bruto_comp and not bruto_teste:
            if amostra:
                a_apagar.append(amostra)
            continue

        if not bruto_comp or not bruto_teste:
            erros.append(
                f"Linha {posicao}: a amostra precisa do resultado nos dois sistemas."
            )
            continue

        try:
            valor_comp = _numero(bruto_comp)
            valor_teste = _numero(bruto_teste)
        except (InvalidOperation, ValueError):
            erros.append(f"Linha {posicao}: valor não numérico.")
            continue

        identificacao = identificacao or _identificacao_sugerida(posicao)
        if identificacao in vistos:
            erros.append(
                f"Linha {posicao}: identificação “{identificacao}” repete a da "
                f"linha {vistos[identificacao]}."
            )
            continue
        vistos[identificacao] = posicao

        a_gravar.append(
            {
                "amostra": amostra,
                "identificacao": identificacao,
                "comparacao": valor_comp,
                "teste": valor_teste,
            }
        )

    if erros:
        return {"gravadas": 0, "apagadas": 0, "erros": erros}

    gravadas = 0
    with transaction.atomic():
        for amostra in a_apagar:
            amostra.delete()

        for item in a_gravar:
            amostra = item["amostra"]
            if amostra is None:
                AmostraComparacao.objects.create(
                    estudo=estudo,
                    identificacao=item["identificacao"],
                    valor_comparacao=item["comparacao"],
                    valor_teste=item["teste"],
                )
                gravadas += 1
                continue

            mudou = (
                amostra.identificacao != item["identificacao"]
                or amostra.valor_comparacao != item["comparacao"]
                or amostra.valor_teste != item["teste"]
            )
            if mudou:
                amostra.identificacao = item["identificacao"]
                amostra.valor_comparacao = item["comparacao"]
                amostra.valor_teste = item["teste"]
                amostra.save(
                    update_fields=["identificacao", "valor_comparacao", "valor_teste"]
                )
                gravadas += 1

    return {"gravadas": gravadas, "apagadas": len(a_apagar), "erros": []}
