"""Tela de configurações — os cadastros que sustentam toda validação.

Mesma gramática visual do quadro e da biblioteca: cartão, selo, estado. Não é
preferência estética. O laboratório que aprendeu a ler um card de validação lê
um card de equipamento sem reaprender nada, e um cadastro vencido salta aos
olhos no mesmo lugar em que salta uma pendência de ficha.

A edição continua no painel administrativo. Esta tela é o mapa: mostra o que
existe, o que está vencendo e o que falta preencher.
"""

from django.contrib.auth.decorators import login_required
from django.shortcuts import render
from django.utils import timezone

from catalogo.models import Calibrador, Controle, Mensurando, Reagente, SistemaAnalitico

from .models import Assinatura, Usuario

# Um insumo que vence dentro deste prazo aparece marcado: dá tempo de pedir
# outro lote antes de a validação parar por falta de reagente válido.
DIAS_DE_ALERTA = 60


def _laboratorio_do(request):
    return getattr(request.user, "laboratorio", None)


def _situacao_do_insumo(insumo, hoje):
    """Vencido, vencendo ou válido — sempre com a palavra, nunca só a cor."""
    dias = (insumo.validade - hoje).days
    if dias < 0:
        return {"chave": "REPROVADO", "texto": "vencido", "dias": dias}
    if dias <= DIAS_DE_ALERTA:
        return {"chave": "INDETERMINADO", "texto": f"vence em {dias} d", "dias": dias}
    return {"chave": "APROVADO", "texto": "válido", "dias": dias}


def _insumos_do_sistema(sistema, hoje):
    """Reagentes, calibradores e controles de um sistema, com a situação de cada."""
    itens = []
    for rotulo, consulta in (
        ("Reagente", sistema.reagentes.all()),
        ("Calibrador", sistema.calibradores.all()),
        ("Controle", sistema.controles.all()),
    ):
        for insumo in consulta:
            itens.append(
                {
                    "tipo": rotulo,
                    "insumo": insumo,
                    "situacao": _situacao_do_insumo(insumo, hoje),
                    "analito": getattr(insumo, "mensurando", None),
                }
            )
    return sorted(itens, key=lambda item: item["situacao"]["dias"])


@login_required
def configuracoes(request):
    laboratorio = _laboratorio_do(request)
    hoje = timezone.localdate()

    if laboratorio is None:
        return render(
            request,
            "contas/configuracoes.html",
            {"secao": "configuracoes", "laboratorio": None},
        )

    sistemas = []
    for sistema in SistemaAnalitico.objects.filter(laboratorio=laboratorio).prefetch_related(
        "reagentes", "calibradores", "controles__mensurando"
    ):
        insumos = _insumos_do_sistema(sistema, hoje)
        sistemas.append(
            {
                "sistema": sistema,
                "insumos": insumos,
                "vencidos": sum(1 for i in insumos if i["situacao"]["chave"] == "REPROVADO"),
                "vencendo": sum(1 for i in insumos if i["situacao"]["chave"] == "INDETERMINADO"),
                "estudos": sistema.estudos_como_teste.count(),
            }
        )

    analitos = []
    for mensurando in Mensurando.objects.filter(laboratorio=laboratorio):
        analitos.append(
            {
                "mensurando": mensurando,
                "sigla": mensurando.nome[:3].upper(),
                "tem_intervalo": mensurando.tem_intervalo_referencia(),
            }
        )

    return render(
        request,
        "contas/configuracoes.html",
        {
            "secao": "configuracoes",
            "laboratorio": laboratorio,
            "assinaturas": Assinatura.objects.filter(laboratorio=laboratorio),
            "modulos_ativos": laboratorio.modulos_ativos(),
            "equipe": Usuario.objects.filter(laboratorio=laboratorio).order_by("funcao", "username"),
            "sistemas": sistemas,
            "analitos": analitos,
            "totais": {
                "reagentes": Reagente.objects.filter(sistema__laboratorio=laboratorio).count(),
                "calibradores": Calibrador.objects.filter(sistema__laboratorio=laboratorio).count(),
                "controles": Controle.objects.filter(sistema__laboratorio=laboratorio).count(),
            },
        },
    )
