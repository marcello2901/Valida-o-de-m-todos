"""Telas do catálogo — as fichas de analito que alimentam toda validação."""

from django.contrib.auth.decorators import login_required
from django.db.models import Count
from django.shortcuts import render

from .models import EspecificacaoQualidade


@login_required
def biblioteca(request):
    """Grade das fichas de analito.

    Cada ficha é a fonte dos limites: definida uma vez, herdada por toda
    validação criada depois. A grade existe para responder de relance quais
    analitos já estão prontos para uso e quais ainda têm pendência — porque uma
    ficha incompleta só aparece como problema no fim do estudo, tarde demais.
    """
    fichas = (
        EspecificacaoQualidade.objects.select_related("mensurando")
        .prefetch_related("limites_imprecisao")
        .annotate(total_estudos=Count("estudos"))
    )

    if not request.user.is_staff:
        fichas = fichas.filter(laboratorio_id=getattr(request.user, "laboratorio_id", None))

    cartoes = []
    contagem_por_fonte = {}
    pendentes = 0

    for ficha in fichas:
        limites = list(ficha.limites_imprecisao.all())
        imprecisao = limites[0].maximo_pct if limites else None
        pendencias = ficha.pendencias_da_ficha()

        if pendencias:
            pendentes += 1
        else:
            rotulo = ficha.get_fonte_display()
            contagem_por_fonte[rotulo] = contagem_por_fonte.get(rotulo, 0) + 1

        cartoes.append(
            {
                "ficha": ficha,
                "sigla": ficha.mensurando.nome[:3].upper(),
                "imprecisao": imprecisao,
                "pendencias": pendencias,
                "erro_total_implicito": ficha.erro_total_implicito(),
                "excede": ficha.sub_limites_excedem_o_erro_total(),
            }
        )

    return render(
        request,
        "catalogo/biblioteca.html",
        {
            "secao": "analitos",
            "cartoes": cartoes,
            "total": len(cartoes),
            "por_fonte": sorted(contagem_por_fonte.items()),
            "pendentes": pendentes,
        },
    )
