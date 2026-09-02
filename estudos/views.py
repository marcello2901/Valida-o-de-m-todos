"""Telas de resultado dos estudos de validação."""

from django.contrib.auth.decorators import login_required
from django.http import Http404
from django.shortcuts import get_object_or_404, render

from . import servicos
from .models import Estudo


@login_required
def resultado(request, estudo_id: int):
    """Mostra o cálculo completo de um estudo.

    Isolamento entre clientes: um usuário só enxerga estudos do próprio
    laboratório. A equipe interna da plataforma (``is_staff``) enxerga todos,
    para poder dar suporte. Sem essa checagem, trocar o número na barra de
    endereço daria acesso aos dados de outro laboratório.
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

    return render(request, "estudos/resultado.html", servicos.calcular(estudo))
