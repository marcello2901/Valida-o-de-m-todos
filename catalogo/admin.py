"""Painel administrativo da rastreabilidade e das especificações de qualidade."""

from django.contrib import admin

from .models import (
    Calibrador,
    Controle,
    EspecificacaoQualidade,
    LimiteImprecisao,
    Mensurando,
    Reagente,
    SistemaAnalitico,
)


@admin.register(Mensurando)
class MensurandoAdmin(admin.ModelAdmin):
    """O analito: o que se mede, em que unidade, em que material.

    O intervalo de referência saiu daqui: ele é da metodologia, e cada estudo já
    declara o do método de comparação e o do método em teste. Um valor único no
    analito servia de reserva para os dois lados — e classificar os resultados
    dos dois métodos pela mesma faixa esconde exatamente o desacordo que a
    concordância clínica existe para medir.
    """

    list_display = ["nome", "unidade_medida", "material_biologico", "validacoes", "laboratorio"]
    list_filter = ["laboratorio", "material_biologico"]
    search_fields = ["nome"]

    fieldsets = [
        (
            "Identificação",
            {
                "fields": ["laboratorio", "nome", "unidade_medida", "material_biologico"],
                "description": (
                    "O intervalo de referência é informado em cada validação, um para o "
                    "método de comparação e outro para o método em teste."
                ),
            },
        ),
    ]

    @admin.display(description="validações")
    def validacoes(self, obj):
        return obj.estudos.count()


class ReagenteInline(admin.TabularInline):
    model = Reagente
    extra = 1
    fields = [
        "nome", "mensurando", "lote", "validade",
        "intervalo_analitico_minimo", "intervalo_analitico_maximo",
    ]


class CalibradorInline(admin.TabularInline):
    model = Calibrador
    extra = 1
    fields = ["nome", "lote", "validade"]


class ControleInline(admin.TabularInline):
    model = Controle
    extra = 1
    fields = ["nivel", "nome", "lote", "validade", "valor_alvo"]


@admin.register(SistemaAnalitico)
class SistemaAnaliticoAdmin(admin.ModelAdmin):
    list_display = ["equipamento", "numero_serie", "metodologia", "papel", "laboratorio", "ativo"]
    list_filter = ["papel", "ativo", "laboratorio"]
    search_fields = ["equipamento", "numero_serie", "metodologia"]
    inlines = [ReagenteInline, CalibradorInline, ControleInline]

    fieldsets = [
        ("Identificação", {"fields": ["laboratorio", "papel", "ativo"]}),
        ("Equipamento", {"fields": ["equipamento", "numero_serie", "metodologia"]}),
    ]


class LimiteImprecisaoInline(admin.TabularInline):
    model = LimiteImprecisao
    extra = 3
    fields = ["nivel", "maximo_pct", "referencia"]


@admin.register(EspecificacaoQualidade)
class EspecificacaoQualidadeAdmin(admin.ModelAdmin):
    list_display = ["nome", "mensurando", "erro_total_maximo_pct", "bias_maximo_pct", "vigente_desde"]
    list_filter = ["laboratorio", "mensurando"]
    search_fields = ["nome", "mensurando__nome"]
    inlines = [LimiteImprecisaoInline]

    fieldsets = [
        ("Identificação", {"fields": ["laboratorio", "mensurando", "nome", "vigente_desde"]}),
        (
            "Erro Total Máximo",
            {
                "fields": [
                    "erro_total_maximo_pct",
                    "erro_total_referencia",
                    "erro_total_limiar_absoluto",
                    "erro_total_maximo_absoluto",
                    "erro_total_referencia_absoluto",
                ],
                "description": (
                    "A referência científica é obrigatória para o estudo poder ser aprovado. "
                    "Os campos absolutos valem apenas para resultados abaixo do limiar informado."
                ),
            },
        ),
        (
            "Erro Sistemático (Bias) Máximo",
            {
                "fields": [
                    "bias_maximo_pct",
                    "bias_referencia",
                    "bias_limiar_absoluto",
                    "bias_maximo_absoluto",
                    "bias_referencia_absoluto",
                ]
            },
        ),
        ("Estatística", {"fields": ["nivel_significancia"]}),
    ]


@admin.register(Controle)
class ControleAdmin(admin.ModelAdmin):
    list_display = ["nome", "nivel", "lote", "validade", "sistema"]
    list_filter = ["nivel", "sistema__laboratorio"]
    search_fields = ["nome", "lote"]
