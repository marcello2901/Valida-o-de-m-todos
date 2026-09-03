"""Telas dos estudos de validação."""

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from . import servicos
from .models import Estudo


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
