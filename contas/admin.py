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


# O que cada mecanismo de acesso realmente controla. Fica aqui, no formulário,
# porque é onde a pessoa está quando toma a decisão errada — pôr no manual não
# resolve. São dois sistemas paralelos e independentes, e confundi-los custa uma
# tarde: um grupo do Django com todas as permissões marcadas não abre nada para
# quem não é membro da equipe, e a função do laboratório não depende de grupo
# nenhum.
EXPLICACAO_ACESSO = (
    "<strong>Estes campos valem só para este painel de cadastros.</strong> "
    "As telas do programa (quadro, validações, relatórios) são governadas pela "
    "<em>função</em>, no bloco abaixo — não por grupo nem por permissão.<br><br>"
    "Para alguém entrar neste painel, <strong>“membro da equipe” precisa estar "
    "marcado</strong>. Sem essa caixa, nem grupo nem permissão individual abrem "
    "coisa alguma: a pessoa recebe a tela de login de volta. Com ela marcada, "
    "grupos e permissões individuais somam — o que vier de qualquer um dos dois "
    "é concedido."
)

EXPLICACAO_FUNCAO = (
    "<strong>É isto que o programa usa.</strong> O responsável técnico é o único "
    "que assina e libera relatório; analista e gestor lançam dados e calculam. "
    "Vale imediatamente, sem depender de grupo nem de permissão."
)


@admin.register(Usuario)
class UsuarioAdmin(UserAdmin):
    list_display = [
        "username", "get_full_name", "laboratorio", "funcao", "acessa_cadastros", "is_active"
    ]
    list_filter = ["funcao", "is_active", "is_staff", "laboratorio"]
    search_fields = ["username", "first_name", "last_name", "email"]

    fieldsets = (
        (None, {"fields": ("username", "password")}),
        ("Informações pessoais", {"fields": ("first_name", "last_name", "email")}),
        (
            "Vínculo e função no laboratório",
            {
                "description": EXPLICACAO_FUNCAO,
                "fields": ("laboratorio", "funcao", "conselho_profissional"),
            },
        ),
        (
            "Acesso a este painel de cadastros",
            {
                "description": EXPLICACAO_ACESSO,
                "fields": (
                    "is_active", "is_staff", "is_superuser", "groups", "user_permissions",
                ),
            },
        ),
        ("Datas", {"fields": ("last_login", "date_joined"), "classes": ("collapse",)}),
    )
    add_fieldsets = UserAdmin.add_fieldsets + (
        (
            "Vínculo e função",
            {
                "description": EXPLICACAO_FUNCAO,
                "fields": ("laboratorio", "funcao", "conselho_profissional"),
            },
        ),
    )

    @admin.display(description="acessa cadastros", boolean=True)
    def acessa_cadastros(self, obj):
        """A caixa que de fato decide se a pessoa entra neste painel.

        Na lista, e não só no formulário: é a resposta para "dei todas as
        permissões e mesmo assim ele não entra" sem precisar abrir usuário
        por usuário.
        """
        return obj.is_staff


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
