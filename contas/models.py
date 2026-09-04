"""Laboratórios (clientes), usuários e módulos contratados.

Cada laboratório é um inquilino isolado: vê apenas os próprios dados. O
isolamento é feito pelo campo ``laboratorio`` presente em tudo que é dado de
cliente, e reforçado nas consultas da aplicação — nunca confiado ao acaso.
"""

from django.conf import settings
from django.contrib.auth.models import AbstractUser
from django.db import models
from django.utils import timezone


class Laboratorio(models.Model):
    """Cliente contratante. É a unidade de isolamento de dados do sistema."""

    razao_social = models.CharField("razão social", max_length=200)
    nome_fantasia = models.CharField("nome fantasia", max_length=200, blank=True)
    cnpj = models.CharField("CNPJ", max_length=18, unique=True)
    cidade = models.CharField("cidade", max_length=100, blank=True)
    uf = models.CharField("UF", max_length=2, blank=True)
    responsavel_tecnico = models.CharField("responsável técnico", max_length=200, blank=True)
    ativo = models.BooleanField("ativo", default=True)
    criado_em = models.DateTimeField("criado em", auto_now_add=True)

    class Meta:
        verbose_name = "laboratório"
        verbose_name_plural = "laboratórios"
        ordering = ["razao_social"]

    def __str__(self):
        return self.nome_fantasia or self.razao_social

    def modulos_ativos(self) -> set[str]:
        """Módulos que o laboratório pode usar hoje."""
        return {
            assinatura.modulo
            for assinatura in self.assinaturas.all()
            if assinatura.vigente()
        }

    def pode_usar(self, modulo: str) -> bool:
        """Diz se um módulo está liberado, considerando que o pacote completo cobre os isolados."""
        ativos = self.modulos_ativos()
        if Assinatura.COMPLETO in ativos:
            return True
        return modulo in ativos


class Usuario(AbstractUser):
    """Usuário do sistema, sempre vinculado a um laboratório.

    A única exceção é a equipe interna (``is_staff``), que administra a
    plataforma e não pertence a nenhum cliente.
    """

    ANALISTA = "analista"
    RESPONSAVEL = "responsavel"
    GESTOR = "gestor"

    FUNCOES = [
        (ANALISTA, "Analista — insere dados e executa estudos"),
        (RESPONSAVEL, "Responsável técnico — assina e libera relatórios"),
        (GESTOR, "Gestor — administra usuários do laboratório"),
    ]

    laboratorio = models.ForeignKey(
        Laboratorio,
        verbose_name="laboratório",
        on_delete=models.PROTECT,
        related_name="usuarios",
        null=True,
        blank=True,
        help_text="Vazio apenas para a equipe interna da plataforma.",
    )
    funcao = models.CharField("função", max_length=20, choices=FUNCOES, default=ANALISTA)
    conselho_profissional = models.CharField(
        "registro no conselho",
        max_length=50,
        blank=True,
        help_text="CRF, CRM, CRBM — aparece na assinatura do relatório.",
    )

    class Meta:
        verbose_name = "usuário"
        verbose_name_plural = "usuários"

    def __str__(self):
        nome = self.get_full_name() or self.username
        return f"{nome} ({self.laboratorio})" if self.laboratorio else nome

    _FUNCAO_CURTA = {ANALISTA: "Analista", RESPONSAVEL: "Responsável técnico", GESTOR: "Gestor"}

    def funcao_curta(self) -> str:
        """Só o nome da função. O rótulo longo explica o que ela faz."""
        return self._FUNCAO_CURTA.get(self.funcao, self.funcao)

    def pode_assinar_relatorio(self) -> bool:
        """Só o responsável técnico libera um relatório de validação."""
        return self.funcao == self.RESPONSAVEL


class Assinatura(models.Model):
    """Módulo contratado por um laboratório, com vigência.

    Os três módulos vendidos. O pacote completo não é apenas a soma dos outros
    dois: é o único que permite calcular Erro Total e métrica Sigma, porque
    esses indicadores exigem imprecisão e bias medidos no mesmo estudo.
    """

    PRECISAO = "precisao"
    COMPARABILIDADE = "comparabilidade"
    COMPLETO = "completo"

    MODULOS = [
        (PRECISAO, "Precisão — réplicas de material de controle"),
        (COMPARABILIDADE, "Comparabilidade — método antigo contra método novo"),
        (COMPLETO, "Precisão + Comparabilidade — inclui Erro Total e Sigma"),
    ]

    laboratorio = models.ForeignKey(
        Laboratorio,
        verbose_name="laboratório",
        on_delete=models.CASCADE,
        related_name="assinaturas",
    )
    modulo = models.CharField("módulo", max_length=20, choices=MODULOS)
    inicio = models.DateField("início da vigência", default=timezone.localdate)
    fim = models.DateField(
        "fim da vigência",
        null=True,
        blank=True,
        help_text="Vazio significa sem prazo de término.",
    )
    observacao = models.CharField("observação", max_length=200, blank=True)
    criado_em = models.DateTimeField("criado em", auto_now_add=True)

    class Meta:
        verbose_name = "assinatura"
        verbose_name_plural = "assinaturas"
        ordering = ["laboratorio", "modulo"]

    def __str__(self):
        return f"{self.laboratorio} — {self.get_modulo_display()}"

    _MODULO_CURTO = {
        "precisao": "Precisão",
        "comparabilidade": "Comparabilidade",
        "completo": "Precisão + Comparabilidade",
    }

    def modulo_curto(self) -> str:
        """Rótulo de cartão. O longo explica o módulo; este só o nomeia."""
        return self._MODULO_CURTO.get(self.modulo, self.modulo)

    def vigente(self, em=None) -> bool:
        hoje = em or timezone.localdate()
        if self.inicio > hoje:
            return False
        return self.fim is None or self.fim >= hoje


class RegistroAuditoria(models.Model):
    """Trilha de auditoria dos atos que alteram um estudo ou um relatório.

    Existe porque um relatório de validação vira registro de qualidade do
    laboratório: numa auditoria é preciso demonstrar quem fez o quê e quando.
    Registros são apenas inseridos — nunca editados nem apagados pela aplicação.
    """

    laboratorio = models.ForeignKey(
        Laboratorio,
        verbose_name="laboratório",
        on_delete=models.PROTECT,
        related_name="auditoria",
    )
    usuario = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="usuário",
        on_delete=models.PROTECT,
        null=True,
        related_name="acoes",
    )
    momento = models.DateTimeField("momento", auto_now_add=True, db_index=True)
    acao = models.CharField("ação", max_length=100)
    objeto = models.CharField("objeto", max_length=200)
    detalhe = models.JSONField("detalhe", default=dict, blank=True)

    class Meta:
        verbose_name = "registro de auditoria"
        verbose_name_plural = "registros de auditoria"
        ordering = ["-momento"]

    def __str__(self):
        return f"{self.momento:%d/%m/%Y %H:%M} — {self.acao} — {self.objeto}"
