"""Estudos de validação: dados brutos e vereditos.

Separação deliberada entre dado bruto e resultado calculado:

- Réplicas e amostras são **dados brutos** — o que o equipamento produziu.
- O veredito é um **retrato congelado**, gravado no momento em que o estudo é
  concluído, junto da versão do motor de cálculo que o produziu.

O motivo é reprodutibilidade. Se em 2028 o motor mudar uma fórmula, um relatório
emitido em 2026 tem de continuar mostrando exatamente o que mostrou na época —
caso contrário o laboratório não consegue defender numa auditoria o número que
assinou.
"""

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models
from django.utils import timezone

from catalogo.models import Controle, EspecificacaoQualidade, Mensurando, SistemaAnalitico
from contas.models import Assinatura, Laboratorio
from motor import precisao

# Versão do motor de cálculo gravada junto de cada veredito.
VERSAO_MOTOR = "1.0.0"


class Estudo(models.Model):
    """Um estudo de validação de um mensurando num sistema analítico."""

    QUANTITATIVO = "quantitativo"
    QUALITATIVO = "qualitativo"

    TIPOS = [
        (QUANTITATIVO, "Quantitativo — resultado numérico"),
        (QUALITATIVO, "Qualitativo — reagente / não reagente"),
    ]

    RASCUNHO = "rascunho"
    CONCLUIDO = "concluido"
    LIBERADO = "liberado"
    CANCELADO = "cancelado"

    SITUACOES = [
        (RASCUNHO, "Rascunho — dados em digitação"),
        (CONCLUIDO, "Concluído — cálculo executado"),
        (LIBERADO, "Liberado — assinado pelo responsável técnico"),
        (CANCELADO, "Cancelado"),
    ]

    laboratorio = models.ForeignKey(
        Laboratorio, verbose_name="laboratório", on_delete=models.PROTECT, related_name="estudos"
    )
    identificacao = models.CharField("identificação", max_length=150, help_text="Ex.: Validação FT4 — Atellica — 2026")
    tipo = models.CharField("tipo de método", max_length=15, choices=TIPOS, default=QUANTITATIVO)
    modulo = models.CharField("módulo utilizado", max_length=20, choices=Assinatura.MODULOS)

    mensurando = models.ForeignKey(
        Mensurando, verbose_name="mensurando", on_delete=models.PROTECT, related_name="estudos"
    )
    sistema_teste = models.ForeignKey(
        SistemaAnalitico, verbose_name="sistema em teste (S.A.t)", on_delete=models.PROTECT,
        related_name="estudos_como_teste"
    )
    sistema_comparacao = models.ForeignKey(
        SistemaAnalitico, verbose_name="sistema de comparação (S.A.c)", on_delete=models.PROTECT,
        related_name="estudos_como_comparacao", null=True, blank=True,
        help_text="Obrigatório quando o módulo inclui comparabilidade."
    )
    especificacao = models.ForeignKey(
        EspecificacaoQualidade, verbose_name="especificação da qualidade", on_delete=models.PROTECT,
        related_name="estudos"
    )

    desenho_precisao = models.CharField(
        "desenho do estudo de precisão",
        max_length=25,
        choices=precisao.DESENHOS,
        default=precisao.DESENHO_MULTIPLAS_CORRIDAS,
        help_text=(
            "Múltiplas corridas mede repetibilidade E precisão intermediária. "
            "Corrida única mede apenas repetibilidade, e o Erro Total calculado a "
            "partir dela subestima o erro da rotina."
        ),
    )

    data_inicio = models.DateField("data de início", default=timezone.localdate)
    data_conclusao = models.DateField("data de conclusão", null=True, blank=True)
    situacao = models.CharField("situação", max_length=12, choices=SITUACOES, default=RASCUNHO)
    observacoes = models.TextField("observações", blank=True)

    criado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL, verbose_name="criado por", on_delete=models.PROTECT,
        related_name="estudos_criados"
    )
    criado_em = models.DateTimeField("criado em", auto_now_add=True)
    atualizado_em = models.DateTimeField("atualizado em", auto_now=True)

    class Meta:
        verbose_name = "estudo de validação"
        verbose_name_plural = "estudos de validação"
        ordering = ["-data_inicio", "identificacao"]

    def __str__(self):
        return f"{self.identificacao} ({self.get_situacao_display()})"

    def clean(self):
        exige_comparacao = self.modulo in (Assinatura.COMPARABILIDADE, Assinatura.COMPLETO)
        if exige_comparacao and self.sistema_comparacao_id is None:
            raise ValidationError(
                {"sistema_comparacao": "O módulo escolhido avalia comparabilidade e exige um sistema de comparação."}
            )
        if self.sistema_comparacao_id and self.sistema_comparacao_id == self.sistema_teste_id:
            raise ValidationError(
                {"sistema_comparacao": "O sistema de comparação precisa ser diferente do sistema em teste."}
            )

    def avalia_precisao(self) -> bool:
        return self.modulo in (Assinatura.PRECISAO, Assinatura.COMPLETO)

    def avalia_comparabilidade(self) -> bool:
        return self.modulo in (Assinatura.COMPARABILIDADE, Assinatura.COMPLETO)

    def minimo_replicas_por_nivel(self) -> int:
        """Quantas réplicas o desenho escolhido exige em cada nível de controle."""
        if self.desenho_precisao == precisao.DESENHO_CORRIDA_UNICA:
            return precisao.MINIMO_REPLICAS_CORRIDA_UNICA
        return precisao.MINIMO_CORRIDAS * precisao.MINIMO_REPLICAS_POR_CORRIDA

    _MODULO_CURTO = {
        Assinatura.PRECISAO: "Precisão",
        Assinatura.COMPARABILIDADE: "Comparabilidade",
        Assinatura.COMPLETO: "Completo",
    }

    def modulo_curto(self) -> str:
        """Nome do módulo em uma palavra, para etiquetas e cabeçalhos."""
        return self._MODULO_CURTO.get(self.modulo, self.modulo)

    def desenho_curto(self) -> str:
        """Desenho do estudo em forma de etiqueta."""
        if self.desenho_precisao == precisao.DESENHO_CORRIDA_UNICA:
            return f"Corrida única · {precisao.MINIMO_REPLICAS_CORRIDA_UNICA} réplicas"
        return f"{precisao.MINIMO_CORRIDAS} × {precisao.MINIMO_REPLICAS_POR_CORRIDA}"

    def editavel(self) -> bool:
        """Estudo liberado é registro de qualidade: não se edita, cancela-se."""
        return self.situacao == self.RASCUNHO

    # --- Progresso, para o quadro e para o cabeçalho do estudo ---------------
    #
    # O quadro não mostra formulário: mostra o quanto falta e qual é a próxima
    # ação. Estes métodos são a fonte desses dois números.

    def replicas_esperadas(self) -> int:
        return self.niveis.count() * self.minimo_replicas_por_nivel()

    def replicas_lancadas(self) -> int:
        return Replica.objects.filter(nivel__estudo=self, excluida=False).count()

    def amostras_lancadas(self) -> int:
        return self.amostras_comparacao.filter(excluida=False).count()

    def progresso(self) -> dict:
        """Quanto de cada estudo já foi digitado, em número e em percentual."""
        from motor.comparabilidade import MINIMO_AMOSTRAS_EP09

        precisao_feita = self.replicas_lancadas() if self.avalia_precisao() else 0
        precisao_total = self.replicas_esperadas() if self.avalia_precisao() else 0
        comparacao_feita = self.amostras_lancadas() if self.avalia_comparabilidade() else 0
        comparacao_total = MINIMO_AMOSTRAS_EP09 if self.avalia_comparabilidade() else 0

        def percentual(feito, total):
            return min(100, round(feito / total * 100)) if total else 0

        return {
            "precisao_feita": precisao_feita,
            "precisao_total": precisao_total,
            "precisao_pct": percentual(precisao_feita, precisao_total),
            "comparacao_feita": comparacao_feita,
            "comparacao_total": comparacao_total,
            "comparacao_pct": percentual(comparacao_feita, comparacao_total),
            "precisao_faltam": max(0, precisao_total - precisao_feita),
            "comparacao_faltam": max(0, comparacao_total - comparacao_feita),
            "completo": (
                (not precisao_total or precisao_feita >= precisao_total)
                and (not comparacao_total or comparacao_feita >= comparacao_total)
                and (precisao_total or comparacao_total)
            ),
            "iniciado": bool(precisao_feita or comparacao_feita),
        }

    def proxima_acao(self) -> str:
        """A frase que o card do quadro mostra no lugar de um formulário."""
        if self.situacao == self.LIBERADO:
            return "Liberado pelo responsável técnico"
        if self.situacao == self.CANCELADO:
            return "Estudo cancelado"
        if self.situacao == self.CONCLUIDO:
            return "Aguarda liberação técnica"

        if not self.niveis.exists() and not self.amostras_comparacao.exists():
            return "Sem dados lançados"

        andamento = self.progresso()
        if andamento["completo"]:
            return "Calcular agora"

        if andamento["precisao_total"] and andamento["precisao_feita"] < andamento["precisao_total"]:
            for nivel in self.niveis.all():
                feitas = nivel.replicas.filter(excluida=False).count()
                if feitas < self.minimo_replicas_por_nivel():
                    return f"Nível {nivel.numero}, réplica {feitas + 1}"

        faltam = andamento["comparacao_total"] - andamento["comparacao_feita"]
        if faltam > 0:
            return f"Faltam {faltam} amostras"
        return "Continuar de onde parou"

    COLUNA_RASCUNHO = "rascunho"
    COLUNA_COLETANDO = "coletando"
    COLUNA_PRONTO = "pronto"
    COLUNA_CALCULADO = "calculado"
    COLUNA_LIBERADO = "liberado"

    def coluna_quadro(self) -> str:
        """Em qual coluna do quadro este estudo aparece."""
        if self.situacao == self.LIBERADO:
            return self.COLUNA_LIBERADO
        if self.situacao == self.CONCLUIDO:
            return self.COLUNA_CALCULADO
        if self.situacao == self.CANCELADO:
            return ""

        andamento = self.progresso()
        if andamento["completo"]:
            return self.COLUNA_PRONTO
        if andamento["iniciado"]:
            return self.COLUNA_COLETANDO
        return self.COLUNA_RASCUNHO


class NivelEstudo(models.Model):
    """Um nível de material de controle dentro do estudo de precisão."""

    estudo = models.ForeignKey(
        Estudo, verbose_name="estudo", on_delete=models.CASCADE, related_name="niveis"
    )
    numero = models.PositiveSmallIntegerField("nível", help_text="Corresponde ao nível do limite de imprecisão")
    controle = models.ForeignKey(
        Controle, verbose_name="material de controle", on_delete=models.PROTECT, related_name="niveis_estudo"
    )
    concentracao_declarada = models.DecimalField(
        "concentração declarada", max_digits=14, decimal_places=4, null=True, blank=True,
        help_text="Usada para decidir entre o limite percentual e o absoluto."
    )

    class Meta:
        verbose_name = "nível do estudo"
        verbose_name_plural = "níveis do estudo"
        ordering = ["numero"]
        constraints = [
            models.UniqueConstraint(fields=["estudo", "numero"], name="nivel_unico_por_estudo")
        ]

    def __str__(self):
        return f"Nível {self.numero} — {self.controle.nome}"


class Replica(models.Model):
    """Uma medição do material de controle.

    ``corrida`` identifica o dia ou a rodada analítica. É o que permite separar
    repetibilidade (dentro da corrida) de precisão intermediária (entre
    corridas) — sem ela, só existe o número menor, que subestima o erro real.
    """

    nivel = models.ForeignKey(
        NivelEstudo, verbose_name="nível", on_delete=models.CASCADE, related_name="replicas"
    )
    corrida = models.PositiveSmallIntegerField("corrida / dia", validators=[MinValueValidator(1)])
    sequencia = models.PositiveSmallIntegerField("réplica na corrida", validators=[MinValueValidator(1)])
    valor = models.DecimalField("valor medido", max_digits=14, decimal_places=4)
    excluida = models.BooleanField(
        "excluída do cálculo", default=False,
        help_text="Exclusão exige justificativa registrada — a réplica não é apagada."
    )
    justificativa_exclusao = models.CharField("justificativa da exclusão", max_length=300, blank=True)

    class Meta:
        verbose_name = "réplica"
        verbose_name_plural = "réplicas"
        ordering = ["corrida", "sequencia"]
        constraints = [
            models.UniqueConstraint(
                fields=["nivel", "corrida", "sequencia"], name="replica_unica_por_corrida"
            )
        ]

    def __str__(self):
        return f"Corrida {self.corrida} / réplica {self.sequencia}: {self.valor}"

    def clean(self):
        if self.excluida and not self.justificativa_exclusao.strip():
            raise ValidationError(
                {"justificativa_exclusao": "Descartar uma medição exige justificativa registrada."}
            )


class AmostraComparacao(models.Model):
    """Amostra de paciente medida nos dois sistemas (estudo quantitativo)."""

    estudo = models.ForeignKey(
        Estudo, verbose_name="estudo", on_delete=models.CASCADE, related_name="amostras_comparacao"
    )
    identificacao = models.CharField("identificação da amostra", max_length=60)
    valor_comparacao = models.DecimalField("resultado no sistema de comparação", max_digits=14, decimal_places=4)
    valor_teste = models.DecimalField("resultado no sistema em teste", max_digits=14, decimal_places=4)
    excluida = models.BooleanField("excluída do cálculo", default=False)
    justificativa_exclusao = models.CharField("justificativa da exclusão", max_length=300, blank=True)

    class Meta:
        verbose_name = "amostra de comparação"
        verbose_name_plural = "amostras de comparação"
        ordering = ["identificacao"]
        constraints = [
            models.UniqueConstraint(
                fields=["estudo", "identificacao"], name="amostra_comparacao_unica_por_estudo"
            )
        ]

    def __str__(self):
        return f"{self.identificacao}: {self.valor_comparacao} → {self.valor_teste}"


class AmostraQualitativa(models.Model):
    """Amostra avaliada por método qualitativo, contra um resultado de referência."""

    estudo = models.ForeignKey(
        Estudo, verbose_name="estudo", on_delete=models.CASCADE, related_name="amostras_qualitativas"
    )
    identificacao = models.CharField("identificação da amostra", max_length=60)
    resultado_referencia = models.BooleanField("referência é reagente")
    resultado_teste = models.BooleanField("método em teste é reagente")

    class Meta:
        verbose_name = "amostra qualitativa"
        verbose_name_plural = "amostras qualitativas"
        ordering = ["identificacao"]
        constraints = [
            models.UniqueConstraint(
                fields=["estudo", "identificacao"], name="amostra_qualitativa_unica_por_estudo"
            )
        ]

    def __str__(self):
        marca = lambda v: "reagente" if v else "não reagente"  # noqa: E731
        return f"{self.identificacao}: ref. {marca(self.resultado_referencia)} / teste {marca(self.resultado_teste)}"


class Veredito(models.Model):
    """Retrato congelado do resultado de um estudo, no momento da conclusão.

    Guarda o resultado completo do motor em ``detalhamento``, junto da versão do
    motor. É esse retrato que o relatório imprime — nunca um recálculo feito na
    hora da impressão, que poderia divergir do que foi assinado.
    """

    APROVADO = "APROVADO"
    REPROVADO = "REPROVADO"
    INDETERMINADO = "INDETERMINADO"

    RESULTADOS = [
        (APROVADO, "Aprovado — dentro de todos os limites especificados"),
        (REPROVADO, "Reprovado — ao menos um indicador fora do limite"),
        (INDETERMINADO, "Indeterminado — dados insuficientes para decidir"),
    ]

    estudo = models.OneToOneField(
        Estudo, verbose_name="estudo", on_delete=models.CASCADE, related_name="veredito"
    )
    resultado = models.CharField("resultado", max_length=15, choices=RESULTADOS)
    detalhamento = models.JSONField("detalhamento do cálculo", default=dict)
    versao_motor = models.CharField("versão do motor de cálculo", max_length=20, default=VERSAO_MOTOR)

    calculado_em = models.DateTimeField("calculado em", auto_now_add=True)
    liberado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL, verbose_name="liberado por", on_delete=models.PROTECT,
        null=True, blank=True, related_name="vereditos_liberados"
    )
    liberado_em = models.DateTimeField("liberado em", null=True, blank=True)

    class Meta:
        verbose_name = "veredito"
        verbose_name_plural = "vereditos"
        ordering = ["-calculado_em"]

    def __str__(self):
        return f"{self.estudo.identificacao}: {self.get_resultado_display()}"

    def liberado(self) -> bool:
        return self.liberado_em is not None

    def maior_erro_total(self):
        """Maior erro total observado entre os níveis, lido do retrato congelado.

        Lê o snapshot, nunca recalcula: um número mostrado ao lado de um veredito
        assinado tem de ser o número que foi assinado. Devolve ``None`` quando o
        retrato não traz o indicador — é o caso do módulo de precisão ou de
        comparabilidade isolados, que por construção não computam erro total.
        Quem exibe deve omitir o campo nesse caso, e não desenhar um traço: um
        traço ao lado de "Aprovado" faz o leitor achar que o dado se perdeu.
        """
        observados = [
            indicador.get("observado_pct")
            for nivel in self.detalhamento.get("precisao", [])
            for indicador in nivel.get("avaliacao", {}).get("indicadores", [])
            if indicador.get("indicador") == "erro total" and indicador.get("observado_pct") is not None
        ]
        return max(observados) if observados else None
