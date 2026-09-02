"""Painel administrativo dos estudos de validação.

Regra aplicada aqui: estudo liberado é registro de qualidade assinado. O painel
impede a edição de dados brutos depois da liberação — corrigir um estudo
liberado significa cancelá-lo e abrir outro, deixando o histórico visível.
"""

from django.contrib import admin

from .models import (
    AmostraComparacao,
    AmostraQualitativa,
    Estudo,
    NivelEstudo,
    Replica,
    Veredito,
)


class NivelEstudoInline(admin.TabularInline):
    model = NivelEstudo
    extra = 1
    fields = ["numero", "controle", "concentracao_declarada"]


class AmostraComparacaoInline(admin.TabularInline):
    model = AmostraComparacao
    extra = 0
    fields = ["identificacao", "valor_comparacao", "valor_teste", "excluida", "justificativa_exclusao"]


class AmostraQualitativaInline(admin.TabularInline):
    model = AmostraQualitativa
    extra = 0
    fields = ["identificacao", "resultado_referencia", "resultado_teste"]


@admin.register(Estudo)
class EstudoAdmin(admin.ModelAdmin):
    list_display = ["identificacao", "mensurando", "tipo", "modulo", "desenho_precisao", "situacao", "data_inicio"]
    list_filter = ["situacao", "tipo", "modulo", "desenho_precisao", "laboratorio"]
    search_fields = ["identificacao", "mensurando__nome"]
    date_hierarchy = "data_inicio"
    inlines = [NivelEstudoInline, AmostraComparacaoInline, AmostraQualitativaInline]

    fieldsets = [
        ("Identificação", {"fields": ["laboratorio", "identificacao", "tipo", "modulo", "situacao"]}),
        (
            "Desenho do estudo de precisão",
            {
                "fields": ["desenho_precisao"],
                "description": (
                    "Corrida única mede apenas repetibilidade: a variação entre dias fica "
                    "invisível e o Erro Total sai otimista. Múltiplas corridas medem a "
                    "precisão intermediária, que é o desempenho real na rotina."
                ),
            },
        ),
        (
            "Rastreabilidade",
            {
                "fields": ["mensurando", "sistema_teste", "sistema_comparacao", "especificacao"],
                "description": (
                    "O sistema de comparação é obrigatório nos módulos que avaliam comparabilidade."
                ),
            },
        ),
        ("Período", {"fields": ["data_inicio", "data_conclusao"]}),
        ("Registro", {"fields": ["criado_por", "observacoes"]}),
    ]

    def get_readonly_fields(self, request, obj=None):
        """Estudo liberado não se edita — cancela-se e refaz-se."""
        if obj and obj.situacao == Estudo.LIBERADO:
            return [campo.name for campo in obj._meta.fields]
        return ["criado_em", "atualizado_em"]


class ReplicaInline(admin.TabularInline):
    model = Replica
    extra = 0
    fields = ["corrida", "sequencia", "valor", "excluida", "justificativa_exclusao"]


@admin.register(NivelEstudo)
class NivelEstudoAdmin(admin.ModelAdmin):
    list_display = ["estudo", "numero", "controle", "concentracao_declarada", "total_replicas"]
    list_filter = ["estudo__laboratorio", "numero"]
    inlines = [ReplicaInline]

    @admin.display(description="réplicas válidas")
    def total_replicas(self, obj):
        return obj.replicas.filter(excluida=False).count()


@admin.register(Veredito)
class VereditoAdmin(admin.ModelAdmin):
    """Somente leitura: o veredito é o retrato congelado do cálculo.

    Editá-lo à mão descolaria o relatório assinado dos dados que o originaram —
    exatamente o que a rastreabilidade existe para impedir.
    """

    list_display = ["estudo", "resultado", "versao_motor", "calculado_em", "liberado_por", "liberado_em"]
    list_filter = ["resultado", "versao_motor"]
    search_fields = ["estudo__identificacao"]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False
