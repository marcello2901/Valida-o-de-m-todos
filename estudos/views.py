"""Telas dos estudos de validação."""

from decimal import Decimal, InvalidOperation

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from catalogo.models import Controle

from . import servicos
from .models import Estudo, Veredito


def _laboratorio_do(request):
    """O laboratório cujos dados este usuário pode ver.

    ``None`` para a equipe interna, que enxerga tudo para dar suporte.
    """
    return None if request.user.is_staff else getattr(request.user, "laboratorio_id", None)


@login_required
def quadro(request):
    """Quadro de validações — uma coluna por etapa, um card por estudo.

    O card não é um formulário resumido: é o estado e a próxima ação. Quem abre
    o quadro precisa enxergar em dois segundos o que está travado e o que
    depende de um único gesto para andar.
    """
    estudos = (
        Estudo.objects.select_related("mensurando", "sistema_teste", "sistema_comparacao", "veredito")
        .prefetch_related("niveis")
        .exclude(situacao=Estudo.CANCELADO)
    )

    laboratorio = _laboratorio_do(request)
    if laboratorio is not None:
        estudos = estudos.filter(laboratorio_id=laboratorio)
    elif not request.user.is_staff:
        estudos = estudos.none()

    colunas = [
        {"chave": Estudo.COLUNA_RASCUNHO, "nome": "Rascunho", "cor": "var(--borda)", "cards": []},
        {"chave": Estudo.COLUNA_COLETANDO, "nome": "Coletando dados", "cor": "var(--acento)", "cards": []},
        {"chave": Estudo.COLUNA_PRONTO, "nome": "Pronto para calcular", "cor": "var(--atencao)", "cards": []},
        {"chave": Estudo.COLUNA_CALCULADO, "nome": "Calculado", "cor": "var(--tinta-2)", "cards": []},
        {"chave": Estudo.COLUNA_LIBERADO, "nome": "Liberado", "cor": "var(--aprovado)", "cards": []},
    ]
    por_chave = {coluna["chave"]: coluna for coluna in colunas}

    for estudo in estudos:
        destino = por_chave.get(estudo.coluna_quadro())
        if destino is None:
            continue
        veredito = getattr(estudo, "veredito", None)
        destino["cards"].append(
            {
                "estudo": estudo,
                "progresso": estudo.progresso(),
                "proxima_acao": estudo.proxima_acao(),
                "destino": estudo.tela_da_proxima_acao(),
                "veredito": veredito,
                "erro_total": veredito.maior_erro_total() if veredito else None,
            }
        )

    return render(request, "estudos/quadro.html", {"secao": "quadro", "colunas": colunas})


def _estudo_do_usuario(request, estudo_id: int) -> Estudo:
    """Busca o estudo garantindo o isolamento entre laboratórios.

    Devolve 404 — não 403 — para quem tenta um estudo alheio: dizer "existe, mas
    você não pode" já entrega que o estudo existe.
    """
    estudo = get_object_or_404(
        Estudo.objects.select_related(
            "laboratorio",
            "mensurando",
            "sistema_teste",
            "sistema_comparacao",
            "especificacao",
            "criado_por",
        ),
        pk=estudo_id,
    )
    if not request.user.is_staff:
        if estudo.laboratorio_id != getattr(request.user, "laboratorio_id", None):
            raise Http404("Estudo não encontrado.")
    return estudo


@login_required
@require_POST
def concluir(request, estudo_id: int):
    """Congela o cálculo do estudo. Só por POST: muda o estado do registro."""
    estudo = _estudo_do_usuario(request, estudo_id)
    try:
        veredito = servicos.concluir(estudo, request.user)
    except servicos.AcaoRecusada as recusa:
        messages.error(request, str(recusa))
    else:
        # A ação congela os números; ela não aprova nem reprova nada. Anunciar
        # "Cálculo congelado: APROVADO" era o programa dando o veredito na voz
        # de uma confirmação de operação.
        messages.success(
            request,
            "Cálculo congelado. A partir de agora o relatório imprime este retrato — "
            "falta marcar o veredito, abaixo da análise crítica.",
        )
        if veredito.leitura_do_motor() == Veredito.REPROVADO:
            messages.warning(
                request,
                "Atenção: pelo menos um indicador ficou fora do limite especificado. "
                "A decisão sobre o estudo continua sendo sua.",
            )
    return redirect("resultado_estudo", estudo_id=estudo.pk)


@login_required
@require_POST
def analise_critica(request, estudo_id: int):
    """Grava a conclusão do responsável e o veredito que ele marcou.

    Os dois vão no mesmo envio de propósito: o veredito é a conclusão da análise
    crítica, e separá-los em dois botões deixaria o texto salvo com a caixa
    desmarcada — que é exatamente o estado que trava a liberação depois.
    """
    estudo = _estudo_do_usuario(request, estudo_id)
    recados = []

    try:
        efeito = servicos.registrar_analise_critica(
            estudo, request.user, request.POST.get("analise_critica", "")
        )
    except servicos.AcaoRecusada as recusa:
        messages.error(request, str(recusa))
        return redirect("resultado_estudo", estudo_id=estudo.pk)

    if efeito != "sem_mudanca":
        recados.append(f"análise crítica {efeito}")

    escolha = (request.POST.get("veredito") or "").strip()
    if escolha:
        try:
            decisao = servicos.registrar_veredito(estudo, request.user, escolha)
        except servicos.AcaoRecusada as recusa:
            messages.error(request, str(recusa))
            return redirect("resultado_estudo", estudo_id=estudo.pk)
        if decisao != "sem_mudanca":
            veredito = estudo.veredito
            recados.append(f"veredito {decisao}: {veredito.get_resultado_display().lower()}")
            # Decidir contra o que os limites apontaram é legítimo — é para isso
            # que o veredito é humano. Sem justificativa escrita, porém, o
            # relatório sai afirmando o contrário dos próprios números e sem
            # dizer por quê, e é isso que uma auditoria pergunta primeiro.
            if veredito.decisao_contraria_ao_calculo() and not veredito.analise_critica.strip():
                messages.warning(
                    request,
                    "O veredito marcado é o oposto do que os limites apontaram e não há "
                    "análise crítica escrita. Registre o motivo antes de liberar o relatório.",
                )

    if recados:
        messages.success(request, f"Salvo: {' · '.join(recados)}. Tudo na trilha de auditoria.")
    else:
        messages.info(request, "Nada mudou.")
    return redirect("resultado_estudo", estudo_id=estudo.pk)


@login_required
@require_POST
def liberar(request, estudo_id: int):
    """Assina o veredito congelado. Só o responsável técnico."""
    estudo = _estudo_do_usuario(request, estudo_id)
    try:
        servicos.liberar(estudo, request.user)
    except servicos.AcaoRecusada as recusa:
        messages.error(request, str(recusa))
    else:
        messages.success(request, "Relatório liberado e registrado na trilha de auditoria.")
    return redirect("resultado_estudo", estudo_id=estudo.pk)


@login_required
def relatorio(request, estudo_id: int):
    """Relatório de validação, formatado para papel.

    Sai em PDF pela caixa de impressão do navegador — não há biblioteca de PDF
    no servidor, e não precisa haver: o navegador já sabe paginar HTML, e o
    resultado é o mesmo arquivo em qualquer máquina, sem dependência de sistema
    que possa quebrar numa atualização da hospedagem.

    Exige um cálculo congelado. Um relatório de validação sem veredito assinado
    é um rascunho, e imprimir rascunho com cara de documento é como um número
    errado entra numa pasta de qualidade.
    """
    estudo = _estudo_do_usuario(request, estudo_id)

    veredito = getattr(estudo, "veredito", None)
    if veredito is None:
        messages.error(
            request,
            "O relatório sai de um cálculo congelado. Use “Calcular e congelar” antes de imprimir.",
        )
        return redirect("resultado_estudo", estudo_id=estudo.pk)

    contexto = servicos.calcular(estudo)
    contexto["secao"] = "quadro"
    contexto["congelado"] = veredito
    contexto["emitido_em"] = timezone.now()
    contexto["emitido_por"] = request.user
    # Mesma checagem da tela de trabalho: se a ficha do analito mudou depois do
    # congelamento, o relatório diz isso em vez de imprimir números que não
    # batem com o veredito impresso ao lado.
    contexto["divergencia"] = _ficha_mudou(veredito, contexto.get("veredito"))
    return render(request, "estudos/relatorio.html", contexto)


@login_required
def replicas(request, estudo_id: int):
    """Grade de lançamento: uma coluna por nível, 30 linhas de réplica cada.

    Substitui o vaivém do painel administrativo, onde cada réplica era um
    formulário. Aqui o laboratório digita a corrida inteira olhando os três
    níveis lado a lado, como na bancada.
    """
    estudo = _estudo_do_usuario(request, estudo_id)

    if estudo.situacao == Estudo.LIBERADO:
        messages.error(request, "Estudo liberado não aceita alteração de dado bruto.")
        return redirect("resultado_estudo", estudo_id=estudo.pk)

    if request.method == "POST":
        if request.POST.get("acao") == "adicionar_nivel":
            erro = servicos.acrescentar_nivel(
                estudo,
                request.POST.get("controle", ""),
                request.POST.get("media_interlaboratorial", ""),
            )
            if erro:
                messages.error(request, erro)
            else:
                messages.success(request, "Nível acrescentado à grade.")
        else:
            _salvar_medias_alvo(request, estudo)
            resumo = servicos.salvar_grade(estudo, request.POST)
            if resumo["erros"]:
                _relatar_pendencias(request, resumo, "réplica")
            else:
                messages.success(
                    request,
                    f"{resumo['gravadas']} réplica(s) gravada(s)"
                    + (f", {resumo['apagadas']} apagada(s)." if resumo["apagadas"] else "."),
                )
                # Gravou: mostra o efeito. Quem vai lançar mais volta pelo
                # atalho da tela de resultado, que agora tem rótulo.
                return redirect("resultado_estudo", estudo_id=estudo.pk)
        return redirect("replicas_estudo", estudo_id=estudo.pk)

    return render(
        request,
        "estudos/replicas.html",
        {
            "secao": "quadro",
            "estudo": estudo,
            "colunas": servicos.montar_grade(estudo),
            "andamento": estudo.progresso(),
            "controles_disponiveis": _controles_livres(estudo),
        },
    )


@login_required
def amostras(request, estudo_id: int):
    """Grade de amostras pareadas: 40 linhas já abertas, ampliáveis.

    Quarenta é o mínimo do CLSI EP09. Abrir a tela já com esse número diz ao
    laboratório quanto o procedimento pede antes de ele começar, em vez de
    deixá-lo descobrir no fim do estudo que faltou amostra.
    """
    estudo = _estudo_do_usuario(request, estudo_id)

    if estudo.situacao == Estudo.LIBERADO:
        messages.error(request, "Estudo liberado não aceita alteração de dado bruto.")
        return redirect("resultado_estudo", estudo_id=estudo.pk)

    if request.method == "POST":
        total = _inteiro(request.POST.get("total"), servicos.MINIMO_AMOSTRAS_GRADE)
        if request.POST.get("acao") == "adicionar_linhas":
            destino = f"{reverse('amostras_estudo', args=[estudo.pk])}?linhas={total + servicos.PASSO_DE_LINHAS}"
            return redirect(destino)

        resumo = servicos.salvar_grade_amostras(estudo, request.POST, total)
        if resumo["erros"]:
            _relatar_pendencias(request, resumo, "amostra")
        else:
            messages.success(
                request,
                f"{resumo['gravadas']} amostra(s) gravada(s)"
                + (f", {resumo['apagadas']} apagada(s)." if resumo["apagadas"] else "."),
            )
            return redirect("resultado_estudo", estudo_id=estudo.pk)
        return redirect("amostras_estudo", estudo_id=estudo.pk)

    grade = servicos.montar_grade_amostras(estudo, _inteiro(request.GET.get("linhas"), 0))
    return render(
        request,
        "estudos/amostras.html",
        {
            "secao": "quadro",
            "estudo": estudo,
            "grade": grade,
            "andamento": estudo.progresso(),
            "passo": servicos.PASSO_DE_LINHAS,
        },
    )


@login_required
def qualitativas(request, estudo_id: int):
    """Grade de amostras qualitativas: reagente / não reagente nos dois métodos.

    Existe pelo mesmo motivo das outras duas — e por um pior: até agora o
    módulo qualitativo só podia ser preenchido uma amostra por vez pelo painel
    administrativo, e as amostras lançadas nem eram contadas pelo programa.
    """
    estudo = _estudo_do_usuario(request, estudo_id)

    if estudo.tipo != Estudo.QUALITATIVO:
        messages.error(
            request,
            "Este estudo é quantitativo. As amostras pareadas são lançadas na grade de amostras.",
        )
        return redirect("resultado_estudo", estudo_id=estudo.pk)

    if estudo.situacao == Estudo.LIBERADO:
        messages.error(request, "Estudo liberado não aceita alteração de dado bruto.")
        return redirect("resultado_estudo", estudo_id=estudo.pk)

    if request.method == "POST":
        total = _inteiro(request.POST.get("total"), servicos.MINIMO_AMOSTRAS_QUALITATIVAS)
        if request.POST.get("acao") == "adicionar_linhas":
            destino = f"{reverse('qualitativas_estudo', args=[estudo.pk])}?linhas={total + servicos.PASSO_DE_LINHAS}"
            return redirect(destino)

        resumo = servicos.salvar_grade_qualitativa(estudo, request.POST, total)
        if resumo["erros"]:
            _relatar_pendencias(request, resumo, "amostra")
        else:
            messages.success(
                request,
                f"{resumo['gravadas']} amostra(s) gravada(s)"
                + (f", {resumo['apagadas']} apagada(s)." if resumo["apagadas"] else "."),
            )
            return redirect("resultado_estudo", estudo_id=estudo.pk)
        return redirect("qualitativas_estudo", estudo_id=estudo.pk)

    grade = servicos.montar_grade_qualitativa(estudo, _inteiro(request.GET.get("linhas"), 0))
    return render(
        request,
        "estudos/qualitativas.html",
        {
            "secao": "quadro",
            "estudo": estudo,
            "grade": grade,
            "andamento": estudo.progresso(),
            "passo": servicos.PASSO_DE_LINHAS,
        },
    )


def _relatar_pendencias(request, resumo, unidade: str):
    """Diz o que entrou e o que ficou de fora, sem desfazer o que entrou.

    Antes o programa descartava o lote inteiro por causa de uma linha e
    recarregava a página, com o que o usuário havia digitado indo junto. Agora o
    que estava certo fica gravado e a mensagem lista o que precisa de correção —
    o trabalho não se perde, e o que ficou de fora está nomeado, não implícito.
    """
    quantidade = len(resumo["erros"])
    for erro in resumo["erros"][:5]:
        messages.warning(request, erro)
    if quantidade > 5:
        messages.warning(request, f"…e mais {quantidade - 5} linha(s) com o mesmo tipo de problema.")

    messages.warning(
        request,
        f"{resumo['gravadas']} {unidade}(s) gravada(s). "
        f"{quantidade} linha(s) não pôde(puderam) ser processada(s) e continuam "
        "em branco — corrija e envie de novo.",
    )


def _inteiro(bruto, padrao: int) -> int:
    """Lê um inteiro vindo da requisição, sem confiar no que chegou."""
    try:
        valor = int(bruto)
    except (TypeError, ValueError):
        return padrao
    # Teto para uma requisição não pedir cem mil campos e derrubar a tela.
    return max(0, min(valor, 500))


def _salvar_medias_alvo(request, estudo):
    """Grava a média interlaboratorial digitada no cabeçalho de cada coluna.

    Fica junto das réplicas de propósito: é o alvo do bias daquele nível, e
    obrigar o usuário a procurá-lo noutra tela é o tipo de ida e volta que faz a
    exatidão simplesmente não ser preenchida.
    """
    for nivel in estudo.niveis.all():
        bruto = (request.POST.get(f"alvo_{nivel.pk}") or "").strip()
        # Texto livre, então o tamanho do campo é o teto — o navegador respeita
        # o maxlength, uma requisição montada à mão não.
        provedor = (request.POST.get(f"provedor_{nivel.pk}") or "").strip()[:80]
        try:
            alvo = servicos.converter_numero(bruto) if bruto else None
        except (InvalidOperation, ValueError):
            messages.error(
                request,
                f"Nível {nivel.numero}: “{bruto}” não é um número válido "
                "para a média interlaboratorial.",
            )
            continue
        if nivel.media_interlaboratorial != alvo or nivel.provedor_interlaboratorial != provedor:
            nivel.media_interlaboratorial = alvo
            nivel.provedor_interlaboratorial = provedor
            nivel.save(update_fields=["media_interlaboratorial", "provedor_interlaboratorial"])


def _controles_livres(estudo):
    """Materiais de controle elegíveis que ainda não são coluna da grade.

    Elegível é o controle do mesmo sistema **e do mesmo analito**: oferecer o
    controle de HbA1c num estudo de FT4, só porque os dois rodam no mesmo
    equipamento, convida a um erro que depois aparece como bias inexplicável.
    """
    usados = estudo.niveis.values_list("controle_id", flat=True)
    return Controle.do_estudo(estudo.sistema_teste, estudo.mensurando).exclude(pk__in=usados)


@login_required
def resultado(request, estudo_id: int):
    """Cálculo completo de um estudo, em faixas que condensam.

    Isolamento entre clientes: um usuário só enxerga estudos do próprio
    laboratório. A equipe interna da plataforma (``is_staff``) enxerga todos,
    para poder dar suporte. Sem essa checagem, trocar o número na barra de
    endereço daria acesso aos dados de outro laboratório.
    """
    estudo = _estudo_do_usuario(request, estudo_id)

    contexto = servicos.calcular(estudo)
    contexto["secao"] = "quadro"
    contexto["andamento"] = estudo.progresso()
    contexto["proxima_acao"] = estudo.proxima_acao()
    contexto["pode_assinar"] = getattr(request.user, "pode_assinar_relatorio", lambda: False)()

    # Esta tela recalcula ao vivo mesmo depois do congelamento, de propósito: é
    # tela de trabalho. Quem imprime o relatório lê o retrato. Mas se os dois
    # discordarem — porque a ficha do analito mudou depois da assinatura — o
    # laboratório precisa saber, em vez de descobrir numa auditoria.
    #
    # A comparação é entre a leitura do motor guardada no retrato e a leitura do
    # motor de agora. O veredito do responsável não entra: ele pode divergir dos
    # limites de propósito, e isso não é sinal de ficha alterada.
    congelado = getattr(estudo, "veredito", None)
    contexto["congelado"] = congelado
    contexto["divergencia"] = _ficha_mudou(congelado, contexto.get("veredito"))
    return render(request, "estudos/resultado.html", contexto)


def _ficha_mudou(congelado, ao_vivo) -> bool:
    """Diz se o recálculo de agora não bate com a leitura congelada do motor."""
    if congelado is None or not ao_vivo:
        return False
    leitura = congelado.leitura_do_motor()
    return bool(leitura) and leitura != ao_vivo.get("status")
