"""Painel administrativo de laboratórios, usuários e módulos contratados.

É por aqui que a operação da plataforma cadastra um cliente novo e libera os
módulos que ele contratou, sem depender de alteração no código.
"""

from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from .models import Assinatura, Laboratorio, RegistroAuditoria, Usuario


class AssinaturaInline(admin.TabularInline):
    model = Assinatura
    extra = 1
    fields = ["modulo", "inicio", "fim", "observacao"]


@admin.register(Laboratorio)
class LaboratorioAdmin(admin.ModelAdmin):
    list_display = ["__str__", "cnpj", "cidade", "uf", "modulos_contratados", "ativo"]
    list_filter = ["ativo", "uf"]
    search_fields = ["razao_social", "nome_fantasia", "cnpj"]
    inlines = [AssinaturaInline]

    @admin.display(description="módulos vigentes")
    def modulos_contratados(self, obj):
        vigentes = sorted(obj.modulos_ativos())
        return ", ".join(vigentes) if vigentes else "— nenhum —"


@admin.register(Usuario)
class UsuarioAdmin(UserAdmin):
    list_display = ["username", "get_full_name", "laboratorio", "funcao", "is_active"]
    list_filter = ["funcao", "is_active", "is_staff", "laboratorio"]
    search_fields = ["username", "first_name", "last_name", "email"]

    fieldsets = UserAdmin.fieldsets + (
        (
            "Vínculo e função",
            {"fields": ("laboratorio", "funcao", "conselho_profissional")},
        ),
    )
    add_fieldsets = UserAdmin.add_fieldsets + (
        (
            "Vínculo e função",
            {"fields": ("laboratorio", "funcao", "conselho_profissional")},
        ),
    )


@admin.register(Assinatura)
class AssinaturaAdmin(admin.ModelAdmin):
    list_display = ["laboratorio", "modulo", "inicio", "fim", "esta_vigente"]
    list_filter = ["modulo"]
    search_fields = ["laboratorio__razao_social", "laboratorio__nome_fantasia"]

    @admin.display(description="vigente", boolean=True)
    def esta_vigente(self, obj):
        return obj.vigente()


@admin.register(RegistroAuditoria)
class RegistroAuditoriaAdmin(admin.ModelAdmin):
    """Somente leitura: trilha de auditoria não se edita nem se apaga."""

    list_display = ["momento", "laboratorio", "usuario", "acao", "objeto"]
    list_filter = ["acao", "laboratorio"]
    search_fields = ["objeto", "acao"]
    date_hierarchy = "momento"

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
