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

    # --- Intervalos de referência de cada metodologia -----------------------
    #
    # Ficam no estudo, e não no mensurando, porque são propriedade da
    # metodologia: ao trocar de método o laboratório costuma trocar também o
    # intervalo que imprime no laudo. A concordância clínica classifica cada
    # lado contra o seu próprio intervalo — é a diferença que de fato chega ao
    # paciente, não a diferença analítica bruta.
    #
    # Em branco, valem os do mensurando: quem manteve o intervalo antigo não
    # precisa redigitá-lo em toda validação.

    referencia_comparacao_inferior = models.DecimalField(
        "referência do método de comparação — inferior", max_digits=14, decimal_places=4,
        null=True, blank=True,
    )
    referencia_comparacao_superior = models.DecimalField(
        "referência do método de comparação — superior", max_digits=14, decimal_places=4,
        null=True, blank=True,
    )
    referencia_teste_inferior = models.DecimalField(
        "referência do método em teste — inferior", max_digits=14, decimal_places=4,
        null=True, blank=True,
    )
    referencia_teste_superior = models.DecimalField(
        "referência do método em teste — superior", max_digits=14, decimal_places=4,
        null=True, blank=True,
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

    def intervalo_de_comparacao(self):
        """Intervalo do método antigo: o do estudo, ou o do mensurando."""
        if self.referencia_comparacao_inferior is not None or self.referencia_comparacao_superior is not None:
            return self.referencia_comparacao_inferior, self.referencia_comparacao_superior
        return self.mensurando.referencia_inferior, self.mensurando.referencia_superior

    def intervalo_de_teste(self):
        """Intervalo do método novo.

        Devolve ``(None, None)`` quando o estudo não declara um próprio — o que
        significa "o mesmo do método antigo", e não "sem intervalo".
        """
        return self.referencia_teste_inferior, self.referencia_teste_superior

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

    def tela_da_proxima_acao(self) -> str:
        """Qual grade abrir ao clicar no card: réplicas ou amostras pareadas.

        O card do quadro promete uma ação ("Faltam 30 amostras"); mandar o
        usuário para a tela de réplicas depois disso é uma promessa quebrada.
        """
        andamento = self.progresso()
        falta_precisao = andamento["precisao_total"] and not andamento["precisao_feita"] >= andamento["precisao_total"]
        if falta_precisao or not andamento["comparacao_total"]:
            return "replicas_estudo"
        return "amostras_estudo"

    def proxima_acao(self) -> str:
        """A frase que o card do quadro mostra no lugar de um formulário."""
        if self.situacao == self.LIBERADO:
            return "Liberado pelo responsável técnico"
        if self.situacao == self.CANCELADO:
            return "Estudo cancelado"
        if self.situacao == self.CONCLUIDO:
            # Duas etapas diferentes depois do cálculo, e o card precisa dizer
            # qual delas está travando: primeiro alguém decide o veredito,
            # depois o responsável assina. "Aguarda liberação" num estudo sem
            # veredito manda o responsável para um botão que vai recusá-lo.
            veredito = getattr(self, "veredito", None)
            if veredito is not None and not veredito.decidido():
                return "Decidir o veredito"
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
    # --- Alvo do bias analítico ---------------------------------------------
    #
    # A exatidão do estudo de precisão sai da comparação entre a média global das
    # réplicas e a média do mesmo lote de controle no grupo de pares. Sem esse
    # alvo informado o sistema não avalia exatidão: um alvo inventado produziria
    # um bias inventado, e é exatamente esse tipo de número que não pode existir
    # num relatório de validação.
    #
    # Os dois campos abaixo pertencem à tela de lançamento de réplicas, não ao
    # cadastro do estudo: quem os preenche é quem tem o boletim do programa
    # interlaboratorial na mão, no momento em que digita as réplicas daquele
    # lote. Estavam no cadastro e simplesmente não eram preenchidos.

    media_interlaboratorial = models.DecimalField(
        "média do estudo interlaboratorial", max_digits=14, decimal_places=4,
        null=True, blank=True,
        help_text=(
            "Média do mesmo lote de controle no grupo de pares. É o alvo do bias. "
            "Em branco, a exatidão deste nível não é avaliada."
        ),
    )
    # Texto livre e não lista fechada: cada laboratório nomeia o seu programa de
    # um jeito ("Controllab EQ-Bioquímica", "Unity Bio-Rad", "fleet Abbott",
    # o número do ciclo). Uma lista de quatro opções obrigava a marcar "outro" e
    # perdia justamente o nome que identifica o boletim numa auditoria.
    provedor_interlaboratorial = models.CharField(
        "programa interlaboratorial", max_length=80, blank=True,
        help_text="Nome do programa de onde veio a média — vai para o relatório.",
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

    def alvo_do_bias(self):
        """A média interlaboratorial como ``float``, ou ``None`` se não informada."""
        return float(self.media_interlaboratorial) if self.media_interlaboratorial is not None else None

    def origem_do_alvo(self) -> str:
        """Frase que o relatório imprime ao lado do bias."""
        if self.media_interlaboratorial is None:
            return ""
        return self.provedor_interlaboratorial.strip() or "programa interlaboratorial"


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
        # Sem unicidade da identificação de propósito. Duas amostras do mesmo
        # código de barras acontecem na rotina — a mesma amostra corrida duas
        # vezes, um código reaproveitado entre dias — e recusar o lançamento
        # obrigaria o laboratório a inventar um identificador falso, que é pior
        # para a rastreabilidade do que o código repetido.
        ordering = ["identificacao"]

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
    """Retrato congelado dos números de um estudo, e a decisão tomada sobre eles.

    Guarda o resultado completo do motor em ``detalhamento``. É esse retrato que
    o relatório imprime — nunca um recálculo feito na hora da impressão, que
    poderia divergir do que foi assinado.

    **O veredito é humano.** O motor calcula cada indicador e diz se ele ficou
    dentro ou fora do limite; quem decide se o método está aprovado é o
    responsável, à luz da análise crítica. Um CV 0,1 ponto acima do limite num
    nível pode ser aceitável com justificativa, e um estudo com todos os números
    dentro pode ser reprovado por um motivo que nenhuma conta enxerga. Enquanto
    ninguém decidir, o campo fica ``PENDENTE`` — e não em cima de um palpite do
    programa, que numa auditoria seria indefensável.
    """

    PENDENTE = "PENDENTE"
    APROVADO = "APROVADO"
    REPROVADO = "REPROVADO"
    # Mantido só para ler retratos e registros gravados antes de o veredito
    # passar a ser decidido por pessoa. Não é oferecido como escolha.
    INDETERMINADO = "INDETERMINADO"

    RESULTADOS = [
        (PENDENTE, "Aguardando a decisão do responsável"),
        (APROVADO, "Estudo aprovado"),
        (REPROVADO, "Estudo reprovado"),
    ]

    estudo = models.OneToOneField(
        Estudo, verbose_name="estudo", on_delete=models.CASCADE, related_name="veredito"
    )
    resultado = models.CharField(
        "veredito do responsável", max_length=15, choices=RESULTADOS, default=PENDENTE,
        help_text="Decidido por pessoa na tela do estudo, não pelo cálculo.",
    )
    detalhamento = models.JSONField("detalhamento do cálculo", default=dict)
    # Metadado de auditoria: diz qual motor produziu o retrato guardado ao lado.
    # Não aparece na tela nem no relatório — serve para rastrear um recálculo
    # divergente depois de uma atualização do sistema.
    versao_motor = models.CharField("versão do motor de cálculo", max_length=20, default=VERSAO_MOTOR)

    # --- Conclusão do responsável -------------------------------------------
    #
    # O que os números não dizem. Um estudo reprovado num nível pode ter
    # explicação — lote de controle no fim da validade, recalibração no meio da
    # série — e um estudo aprovado pode ter ressalva. Sem este campo essa
    # informação vive num e-mail que não acompanha o relatório.
    #
    # Editável depois do congelamento de propósito: a análise crítica amadurece
    # enquanto o veredito, que é o retrato dos números, não muda. Cada edição vai
    # para a trilha de auditoria, então o histórico não se perde.
    analise_critica = models.TextField(
        "conclusão / análise crítica", blank=True,
        help_text="Observações, nuances e explicações que acompanham o relatório.",
    )
    analise_atualizada_em = models.DateTimeField(
        "análise atualizada em", null=True, blank=True
    )

    calculado_em = models.DateTimeField("calculado em", auto_now_add=True)
    # Quem decidiu o veredito e quando. Sem isso o documento afirma "aprovado"
    # sem dizer quem afirmou — e a decisão pode ser anterior à assinatura, ou de
    # outra pessoa, então não dá para reaproveitar ``liberado_por``.
    decidido_por = models.ForeignKey(
        settings.AUTH_USER_MODEL, verbose_name="veredito decidido por", on_delete=models.PROTECT,
        null=True, blank=True, related_name="vereditos_decididos"
    )
    decidido_em = models.DateTimeField("veredito decidido em", null=True, blank=True)
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

    def decidido(self) -> bool:
        """Diz se alguém já se pronunciou sobre este estudo."""
        return self.resultado in {self.APROVADO, self.REPROVADO}

    def leitura_do_motor(self) -> str:
        """O que o cálculo apontou, lido do retrato congelado.

        É evidência, não veredito: entra na tela ao lado das caixas de decisão
        para que o responsável veja o que os limites disseram antes de decidir.
        """
        return (self.detalhamento.get("veredito") or {}).get("status", "")

    def decisao_contraria_ao_calculo(self) -> bool:
        """Diz se a pessoa decidiu ao contrário do que os limites apontaram.

        Não é erro — é exatamente a liberdade que o veredito manual existe para
        dar. Mas é o caso em que a análise crítica deixa de ser opcional, e a
        tela precisa poder cobrá-la.
        """
        leitura = self.leitura_do_motor()
        if not self.decidido() or leitura not in {self.APROVADO, self.REPROVADO}:
            return False
        return self.resultado != leitura

    def analise_editada_apos_liberacao(self) -> bool:
        """Diz se a conclusão mudou depois de o relatório ser assinado.

        Não impede a edição — a análise crítica é justamente o que o responsável
        continua amadurecendo — mas um leitor precisa saber que o texto que está
        vendo não é o mesmo que estava lá no dia da assinatura.
        """
        if self.liberado_em is None or self.analise_atualizada_em is None:
            return False
        return self.analise_atualizada_em > self.liberado_em

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
