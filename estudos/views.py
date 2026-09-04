"""Telas dos estudos de validação."""

from decimal import Decimal, InvalidOperation

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from catalogo.models import Controle

from . import servicos
from .models import Estudo, NivelEstudo


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
        # O tom acompanha o resultado, não o sucesso da operação. Congelar um
        # REPROVADO em faixa verde de "tudo certo" é sinal trocado: a ação deu
        # certo, o método é que não passou.
        recado = (
            f"Cálculo congelado: {veredito.get_resultado_display()}. "
            "A partir de agora o relatório imprime este retrato."
        )
        if veredito.resultado == veredito.APROVADO:
            messages.success(request, recado)
        elif veredito.resultado == veredito.INDETERMINADO:
            messages.warning(request, recado)
        else:
            messages.info(request, recado)
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
                for erro in resumo["erros"][:5]:
                    messages.error(request, erro)
                messages.error(
                    request, "Nada foi gravado: corrija os valores acima e envie de novo."
                )
            else:
                messages.success(
                    request,
                    f"{resumo['gravadas']} réplica(s) gravada(s)"
                    + (f", {resumo['apagadas']} apagada(s)." if resumo["apagadas"] else "."),
                )
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
            "provedores": NivelEstudo.PROVEDORES,
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
            for erro in resumo["erros"][:5]:
                messages.error(request, erro)
            messages.error(
                request, "Nada foi gravado: corrija as linhas acima e envie de novo."
            )
        else:
            messages.success(
                request,
                f"{resumo['gravadas']} amostra(s) gravada(s)"
                + (f", {resumo['apagadas']} apagada(s)." if resumo["apagadas"] else "."),
            )
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
        provedor = (request.POST.get(f"provedor_{nivel.pk}") or "").strip()
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
    congelado = getattr(estudo, "veredito", None)
    contexto["divergencia"] = bool(
        congelado
        and contexto.get("veredito")
        and congelado.resultado != contexto["veredito"]["status"]
    )
    return render(request, "estudos/resultado.html", contexto)
