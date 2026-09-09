"""Filtros de número para as telas e o relatório.

Um relatório de validação é lido por quem confere conta. Sinal trocado, sinal
ausente e dois traços diferentes na mesma linha são o tipo de detalhe que faz
alguém desconfiar do documento inteiro — então o sinal é explícito e o traço é
sempre o mesmo.
"""

from decimal import Decimal, InvalidOperation

from django import template
from django.utils.formats import number_format

# O Django procura este nome exato ao carregar a biblioteca de filtros.
register = template.Library()

# O sinal de menos tipográfico (U+2212), e não o hífen do teclado. É o mesmo
# usado nas contas escritas ao lado ("0,6010 − 0,6100"), e misturar os dois na
# mesma linha fica visivelmente torto.
MENOS = "−"


@register.filter
def sinalizado(valor, casas=2):
    """Número com o sinal sempre à mostra: ``+1,48`` ou ``−1,48``.

    O bias sem sinal não diz o que importa — se o método lê acima ou abaixo do
    grupo de pares. Zero sai sem sinal, porque ``+0,00`` afirma um sentido que
    o número não tem.
    """
    try:
        numero = Decimal(str(valor))
    except (InvalidOperation, TypeError, ValueError):
        return "—"

    casas = int(casas)
    arredondado = numero.quantize(Decimal(1).scaleb(-casas))
    texto = number_format(abs(arredondado), decimal_pos=casas, use_l10n=True)

    if arredondado > 0:
        return f"+{texto}"
    if arredondado < 0:
        return f"{MENOS}{texto}"
    return texto


@register.filter
def com_menos(valor, casas=4):
    """Número comum, mas com o menos tipográfico no lugar do hífen."""
    try:
        numero = Decimal(str(valor))
    except (InvalidOperation, TypeError, ValueError):
        return "—"

    casas = int(casas)
    arredondado = numero.quantize(Decimal(1).scaleb(-casas))
    texto = number_format(abs(arredondado), decimal_pos=casas, use_l10n=True)
    return f"{MENOS}{texto}" if arredondado < 0 else texto
