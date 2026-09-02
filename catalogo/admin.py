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
    list_display = ["nome", "unidade_medida", "material_biologico", "intervalo_referencia", "laboratorio"]
    list_filter = ["laboratorio", "material_biologico"]
    search_fields = ["nome"]

    fieldsets = [
        ("Identificação", {"fields": ["laboratorio", "nome", "unidade_medida", "material_biologico"]}),
        (
            "Intervalo de referência",
            {
                "fields": ["referencia_inferior", "referencia_superior"],
                "description": (
                    "Necessário para a concordância clínica: é o que permite dizer se os "
                    "dois métodos classificariam a amostra da mesma forma no laudo."
                ),
            },
        ),
    ]

    @admin.display(description="intervalo de referência")
    def intervalo_referencia(self, obj):
        if not obj.tem_intervalo_referencia():
            return "— não informado —"
        return f"{obj.referencia_inferior} a {obj.referencia_superior} {obj.unidade_medida}"


class ReagenteInline(admin.TabularInline):
    model = Reagente
    extra = 1
    fields = ["nome", "lote", "validade"]


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
        (
            "Intervalo analítico",
            {
                "fields": ["intervalo_analitico_minimo", "intervalo_analitico_maximo"],
                "description": "Faixa em que o sistema produz resultado confiável.",
            },
        ),
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
