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
    # Ordem de cadastro, não alfabética: é a ordem em que a grade mostra e em
    # que o laboratório digitou. Com códigos repetidos a ordem alfabética é
    # indefinida entre iguais, e as linhas trocavam de lugar entre telas.
    amostras = estudo.amostras_comparacao.filter(excluida=False).order_by("pk")
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
        "regressao": comp.regressao_linear(x, y),
        "bland_altman": comp.bland_altman(x, y),
        "lin": conc.lin(x, y),
        "razao_das_medias": conc.razao_das_medias(x, y),
        "analitica": conc.concordancia_analitica(x, y, especificacao.erro_total, nomes),
    }

    # A razão das médias só significa alguma coisa ao lado do limite com que
    # ela se compara — e a comparação precisa concluir. Um percentual acima do
    # limite impresso sem dizer "reprovado" ao lado deixa o leitor concluir
    # sozinho, e num registro de qualidade isso é pior do que não mostrar.
    limite_bias = especificacao.bias.aplicar(None) if especificacao.bias else None
    resultado["bias_maximo_pct"] = limite_bias["limite_pct"] if limite_bias else None
    resultado["bias_referencia"] = especificacao.bias.referencia_pct if especificacao.bias else ""
    resultado["razao_avaliacao"] = ver.avaliar_bias(
        resultado["razao_das_medias"]["desvio_pct"], especificacao.bias, None
    )

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

        # Concentração usada para resolver limite percentual contra absoluto.
        # É a média medida: era o que o programa já usava quase sempre, porque a
        # concentração declarada quase nunca era preenchida — e quando era, punha
        # o número da bula a decidir um limite sobre medições que são outras.
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
        # Cada indicador nomeado, em vez de a tela varrer a lista dentro de uma
        # célula de tabela. Varrendo, a linha perdia duas colunas quando o
        # indicador não existia — a tabela saía torta e ninguém via o limite.
        item["indicador_imprecisao"] = _indicador(avaliacao, "imprecisão")
        item["indicador_bias"] = _indicador(avaliacao, "bias")

    return {
        "estudo": estudo,
        "tipo": estudo.QUANTITATIVO,
        "modulo_efetivo": modulo,
        "especificacao": especificacao,
        "pendencias_especificacao": especificacao.pendencias(),
        "precisao": precisao_por_nivel,
        "comparabilidade": comparabilidade,
        "veredito": veredito,
        "reagentes": reagentes_do_estudo(estudo),
        "graficos": _graficos(estudo, precisao_por_nivel, comparabilidade),
        "avisos": _avisos(estudo, precisao_por_nivel, comparabilidade),
    }


def _indicador(avaliacao, nome: str) -> dict | None:
    """Um indicador da avaliação de um nível, pelo nome, ou ``None``."""
    for indicador in (avaliacao or {}).get("indicadores", []):
        if indicador.get("indicador") == nome:
            return indicador
    return None


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


def reagentes_do_estudo(estudo) -> dict:
    """O reagente de cada sistema para o analito deste estudo.

    O intervalo analítico saiu do equipamento e foi para o kit, que é de quem
    ele sempre foi: um analisador roda dezenas de ensaios, cada um com a sua
    faixa de medição na bula. É por isso que o relatório precisa dizer qual lote
    de reagente mediu, e não apenas em qual máquina.
    """
    from catalogo.models import Reagente

    def primeiro(sistema):
        if sistema is None:
            return None
        return Reagente.do_estudo(sistema, estudo.mensurando).order_by("-validade").first()

    return {
        "teste": primeiro(estudo.sistema_teste),
        "comparacao": primeiro(estudo.sistema_comparacao),
    }


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
        if chave not in ("estudo", "graficos", "especificacao", "precisao", "reagentes")
    }
    congelado["estudo"] = estudo.identificacao
    congelado["especificacao"] = _especificacao_legivel(especificacao)
    congelado["reagentes"] = _reagentes_legiveis(resultado.get("reagentes") or {})
    congelado["precisao"] = [
        {**bloco, "nivel": str(bloco["nivel"])} for bloco in resultado.get("precisao", [])
    ]
    return congelado


def _reagentes_legiveis(reagentes: dict) -> dict:
    """Lote e faixa de medição de cada kit, em texto.

    O objeto do banco não cabe em JSON, e guardá-lo por referência não serviria:
    o retrato precisa dizer qual lote mediu, mesmo que o cadastro mude depois.
    """
    def descrever(reagente):
        if reagente is None:
            return None
        return {
            "nome": reagente.nome,
            "lote": reagente.lote,
            "validade": reagente.validade.isoformat(),
            "intervalo_analitico": reagente.intervalo_escrito(),
        }

    return {papel: descrever(reagente) for papel, reagente in reagentes.items()}


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
        # lado: é a comparação que o olho faz. A regressão de Deming fica na
        # tabela — mais adequada por admitir erro nos dois eixos, e por isso é
        # contra ela que o bias por nível é estimado, não contra esta.
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

    # A conclusão do responsável atravessa o recálculo. Recalcular substitui o
    # retrato dos números; a leitura que alguém escreveu sobre o estudo não é um
    # número, e perdê-la por causa de uma réplica corrigida seria absurdo.
    analise = anterior.analise_critica if anterior else ""
    analise_em = anterior.analise_atualizada_em if anterior else None

    # A decisão, ao contrário do texto, NÃO atravessa. Ela foi tomada sobre os
    # números antigos; recalcular troca os números. Manter o "aprovado" em cima
    # de outra conta seria assinar o que ninguém leu — o veredito volta a
    # pendente e é decidido de novo.
    with transaction.atomic():
        if anterior is not None:
            anterior.delete()
        veredito = Veredito.objects.create(
            estudo=estudo,
            resultado=Veredito.PENDENTE,
            detalhamento=resultado,
            analise_critica=analise,
            analise_atualizada_em=analise_em,
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
                "leitura_do_motor": veredito.leitura_do_motor(),
                "versao_motor": veredito.versao_motor,
                "veredito_anterior": anterior.resultado if anterior else None,
                "replicas": andamento["precisao_feita"],
                "amostras": andamento["comparacao_feita"],
                "avisos": resultado.get("avisos", []),
            },
        )

    return veredito


def registrar_analise_critica(estudo, usuario, texto: str) -> str:
    """Grava a conclusão do responsável e deixa a edição na trilha.

    Continua editável depois do congelamento, e mesmo depois da liberação: os
    números do veredito são o retrato e não mudam; a leitura que o responsável
    faz deles amadurece. O que não pode é a mudança acontecer sem registro, e é
    por isso que cada edição guarda quem, quando e o tamanho do texto anterior.
    """
    veredito = getattr(estudo, "veredito", None)
    if veredito is None:
        raise AcaoRecusada(
            "A análise crítica acompanha um cálculo congelado. Calcule o estudo primeiro."
        )

    texto = (texto or "").strip()
    anterior = veredito.analise_critica
    if texto == anterior:
        return "sem_mudanca"

    with transaction.atomic():
        veredito.analise_critica = texto
        veredito.analise_atualizada_em = timezone.now()
        veredito.save(update_fields=["analise_critica", "analise_atualizada_em"])

        RegistroAuditoria.objects.create(
            laboratorio=estudo.laboratorio,
            usuario=usuario if usuario.is_authenticated else None,
            acao="editou a análise crítica" if anterior else "escreveu a análise crítica",
            objeto=estudo.identificacao,
            detalhe={
                "caracteres_antes": len(anterior),
                "caracteres_depois": len(texto),
                "apos_liberacao": veredito.liberado_em is not None,
            },
        )

    return "editada" if anterior else "escrita"


def registrar_veredito(estudo, usuario, escolha: str) -> str:
    """Grava a decisão do responsável sobre o estudo: aprovado ou reprovado.

    Quem decide é pessoa. O motor mede cada indicador contra o seu limite e diz
    o que ficou dentro e o que ficou fora; transformar isso automaticamente num
    "método aprovado" é atribuir ao programa um julgamento que é do laboratório.
    Um CV meio ponto acima do limite num nível pode ser aceitável com
    justificativa registrada; um estudo com todos os números dentro pode ser
    reprovado por um motivo que nenhuma conta enxerga.

    A decisão é rastreada como qualquer outra: quem, quando, o que o cálculo
    apontava na hora e se a pessoa decidiu ao contrário dele.
    """
    veredito = getattr(estudo, "veredito", None)
    if veredito is None:
        raise AcaoRecusada(
            "O veredito é decidido sobre um cálculo congelado. Calcule o estudo primeiro."
        )
    if estudo.situacao == estudo.LIBERADO:
        raise AcaoRecusada(
            "Este relatório já foi assinado. O veredito de um documento liberado "
            "não se troca — cancele o estudo e abra outro."
        )
    if escolha not in {Veredito.APROVADO, Veredito.REPROVADO}:
        raise AcaoRecusada("Marque uma das duas caixas: estudo aprovado ou estudo reprovado.")

    if veredito.resultado == escolha:
        return "sem_mudanca"

    anterior = veredito.resultado
    with transaction.atomic():
        veredito.resultado = escolha
        veredito.decidido_por = usuario if usuario.is_authenticated else None
        veredito.decidido_em = timezone.now()
        veredito.save(update_fields=["resultado", "decidido_por", "decidido_em"])

        RegistroAuditoria.objects.create(
            laboratorio=estudo.laboratorio,
            usuario=usuario if usuario.is_authenticated else None,
            acao="decidiu o veredito" if anterior == Veredito.PENDENTE else "mudou o veredito",
            objeto=estudo.identificacao,
            detalhe={
                "veredito": escolha,
                "veredito_anterior": anterior,
                "leitura_do_motor": veredito.leitura_do_motor(),
                "contraria_o_calculo": veredito.decisao_contraria_ao_calculo(),
                "tem_analise_critica": bool(veredito.analise_critica.strip()),
            },
        )

    return "decidido" if anterior == Veredito.PENDENTE else "alterado"


def liberar(estudo, usuario):
    """Assina o veredito decidido, transformando-o em registro de qualidade.

    Reprovado também se assina: um estudo que falhou é um resultado, e
    escondê-lo seria pior do que registrá-lo. O que a assinatura afirma é que
    aquele cálculo, com aqueles dados, foi conferido — não que o método passou.
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
    # Sem esta trava o relatório assinado sairia com "aguardando a decisão do
    # responsável" no lugar do veredito — assinado e sem dizer o quê.
    if not veredito.decidido():
        raise AcaoRecusada(
            "Marque o veredito antes de liberar: o relatório precisa dizer se o "
            "estudo foi aprovado ou reprovado. As caixas ficam abaixo da análise "
            "crítica, na tela do estudo."
        )

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
                "veredito": veredito.resultado,
                "decidido_por": getattr(veredito.decidido_por, "username", None),
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

    Uma réplica ilegível não derruba as outras: as válidas entram e a lista de
    erros diz quais ficaram de fora. Descartar as 74 réplicas boas por causa da
    75ª é perder o trabalho de cinco dias por um dígito.
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
                    valor = converter_numero(bruto)
                except NumeroAmbiguo as ambiguo:
                    erros.append(f"Nível {nivel.numero}, réplica {posicao}: {ambiguo}")
                    continue
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
            alvo = converter_numero(media_alvo)
        except (InvalidOperation, ValueError):
            return f"“{media_alvo}” não é um número válido para a média interlaboratorial."

    NivelEstudo.objects.create(
        estudo=estudo,
        numero=proximo,
        controle=controle,
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
    existentes = list(estudo.amostras_comparacao.order_by("pk"))
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


class NumeroAmbiguo(ValueError):
    """O texto pode ser lido de dois jeitos, com mil vezes de diferença."""


def converter_numero(bruto: str) -> Decimal:
    """Lê um número como um laboratório brasileiro o escreve.

    O Excel em português copia mil e duzentos e trinta e quatro vírgula cinco
    seis como ``1.234,56``. Trocar só a vírgula por ponto produzia ``1.234.56``,
    que o Decimal recusa — ou seja, glicose, CK e ferritina, que passam de mil
    na rotina, simplesmente não entravam.

    Quando há os dois separadores, o último é o decimal e o outro é o de milhar.
    Vírgula sozinha é sempre decimal. Ponto sozinho com exatamente três casas
    depois é **ambíguo** — ``1.500`` tanto pode ser 1,5 quanto 1500 — e aí a
    função recusa em vez de escolher. Escolher errado aqui não dá um número
    estranho: dá um número mil vezes maior num relatório assinado.
    """
    texto = bruto.strip().replace(" ", "").replace("\u00a0", "")
    tem_ponto = "." in texto
    tem_virgula = "," in texto

    if tem_ponto and tem_virgula:
        if texto.rfind(",") > texto.rfind("."):
            texto = texto.replace(".", "").replace(",", ".")
        else:
            texto = texto.replace(",", "")
    elif tem_virgula:
        texto = texto.replace(",", ".")
    elif tem_ponto:
        # Só é ambíguo o que caberia como grupo de milhar: 1 a 3 dígitos antes
        # do ponto, sem zero à esquerda. "0.930" não tem leitura dupla — nenhum
        # separador de milhar vem depois de um zero — e "1234.567" também não,
        # porque o milhar sairia como "1.234.567".
        inteiro, _, fracao = texto.rpartition(".")
        cabeca = inteiro.lstrip("+-")
        parece_milhar = (
            len(fracao) == 3
            and cabeca.isdigit()
            and 1 <= len(cabeca) <= 3
            and not cabeca.startswith("0")
        )
        if parece_milhar:
            raise NumeroAmbiguo(
                f"“{bruto.strip()}” pode ser {inteiro},{fracao} ou {inteiro}{fracao}. "
                "Use vírgula para o decimal, ou tire o separador de milhar."
            )

    return Decimal(texto)


def _numero(bruto: str) -> Decimal:
    return converter_numero(bruto)


def salvar_grade_amostras(estudo, dados, total: int) -> dict:
    """Grava a grade de amostras pareadas de uma vez.

    Regras que valem a pena estar explícitas:

    - Linha com os dois valores em branco apaga a amostra daquela posição.
    - Linha com **um** valor só é erro, não meia amostra: um par incompleto não
      entra em regressão nenhuma, e gravá-lo silenciosamente deixaria o estudo
      com uma amostra que não conta e ninguém sabe por quê.
    - Identificação em branco recebe a sugerida (AM-007). Ninguém deveria ter de
      digitar quarenta identificadores sequenciais à mão.
    - Identificação repetida é aceita. Acontece na rotina — a mesma amostra
      corrida duas vezes, um código reaproveitado — e obrigar o laboratório a
      inventar um identificador falso seria pior para a rastreabilidade.

    Linha com problema não derruba as outras. As válidas são gravadas e as
    demais voltam descritas, uma a uma, para correção. A regra anterior era
    tudo-ou-nada: um dígito errado na linha 7 descartava as 40 linhas coladas, e
    como a página recarregava do banco, o que estava digitado sumia junto.
    """
    from .models import AmostraComparacao

    erros: list[str] = []
    a_gravar: list[dict] = []
    a_apagar: list = []

    existentes = list(estudo.amostras_comparacao.order_by("pk"))

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
            valor_comp = converter_numero(bruto_comp)
            valor_teste = converter_numero(bruto_teste)
        except NumeroAmbiguo as ambiguo:
            erros.append(f"Linha {posicao}: {ambiguo}")
            continue
        except (InvalidOperation, ValueError):
            erros.append(f"Linha {posicao}: valor não numérico.")
            continue

        identificacao = identificacao or _identificacao_sugerida(posicao)

        a_gravar.append(
            {
                "amostra": amostra,
                "identificacao": identificacao,
                "comparacao": valor_comp,
                "teste": valor_teste,
            }
        )

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

    return {"gravadas": gravadas, "apagadas": len(a_apagar), "erros": erros}
