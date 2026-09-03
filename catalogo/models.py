"""Rastreabilidade: o que foi medido, em que equipamento, com quais insumos.

Estes modelos reproduzem o cabeçalho da planilha de validação. São eles que
transformam um cálculo estatístico em registro auditável: sem lote e validade de
reagente, calibrador e controle, um resultado de validação não pode ser
reproduzido nem defendido numa auditoria.

Todo cadastro é preenchido ANTES de qualquer dado bruto ser digitado — a
rastreabilidade é pré-requisito do estudo, não anexo dele.
"""

from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone

from contas.models import Laboratorio
from motor.veredito import FATOR_ERRO_TOTAL


class Mensurando(models.Model):
    """A grandeza medida: analito, unidade e material biológico."""

    laboratorio = models.ForeignKey(
        Laboratorio, verbose_name="laboratório", on_delete=models.CASCADE, related_name="mensurandos"
    )
    nome = models.CharField("nome", max_length=100, help_text="Ex.: FT4, Glicose, TSH")
    unidade_medida = models.CharField("unidade de medida", max_length=30, help_text="Ex.: ng/dL, mg/dL")
    material_biologico = models.CharField("material biológico", max_length=60, help_text="Ex.: soro, plasma, sangue total")
    referencia_inferior = models.DecimalField(
        "intervalo de referência — limite inferior",
        max_digits=14,
        decimal_places=4,
        null=True,
        blank=True,
        help_text="Necessário para calcular a concordância clínica entre os métodos.",
    )
    referencia_superior = models.DecimalField(
        "intervalo de referência — limite superior",
        max_digits=14,
        decimal_places=4,
        null=True,
        blank=True,
    )

    class Meta:
        verbose_name = "mensurando"
        verbose_name_plural = "mensurandos"
        ordering = ["nome"]
        constraints = [
            models.UniqueConstraint(
                fields=["laboratorio", "nome", "material_biologico"],
                name="mensurando_unico_por_laboratorio",
            )
        ]

    def __str__(self):
        return f"{self.nome} ({self.unidade_medida}) — {self.material_biologico}"

    def clean(self):
        inferior, superior = self.referencia_inferior, self.referencia_superior
        if inferior is not None and superior is not None and inferior >= superior:
            raise ValidationError(
                {"referencia_superior": "O limite superior do intervalo de referência deve ser maior que o inferior."}
            )

    def tem_intervalo_referencia(self) -> bool:
        """Sem os dois limites não há como avaliar concordância clínica."""
        return self.referencia_inferior is not None and self.referencia_superior is not None


class SistemaAnalitico(models.Model):
    """Equipamento + metodologia. Um estudo de comparabilidade envolve dois.

    ``papel`` distingue o Sistema Analítico em Teste (S.A.t, o método novo) do
    Sistema Analítico de Comparação (S.A.c, o método em uso). A convenção é
    usada pelo motor de cálculo: bias positivo significa que o método novo lê
    acima do antigo.
    """

    TESTE = "teste"
    COMPARACAO = "comparacao"

    PAPEIS = [
        (TESTE, "Sistema Analítico em Teste (S.A.t) — método novo"),
        (COMPARACAO, "Sistema Analítico de Comparação (S.A.c) — método em uso"),
    ]

    laboratorio = models.ForeignKey(
        Laboratorio, verbose_name="laboratório", on_delete=models.CASCADE, related_name="sistemas"
    )
    papel = models.CharField("papel no estudo", max_length=12, choices=PAPEIS)
    equipamento = models.CharField("equipamento", max_length=120, help_text="Ex.: Atellica")
    numero_serie = models.CharField("número de série", max_length=60, help_text="Ex.: IH00715")
    metodologia = models.CharField("metodologia", max_length=120, help_text="Ex.: Quimioluminescência")
    intervalo_analitico_minimo = models.DecimalField(
        "intervalo analítico — mínimo", max_digits=14, decimal_places=4, null=True, blank=True
    )
    intervalo_analitico_maximo = models.DecimalField(
        "intervalo analítico — máximo", max_digits=14, decimal_places=4, null=True, blank=True
    )
    ativo = models.BooleanField("ativo", default=True)

    class Meta:
        verbose_name = "sistema analítico"
        verbose_name_plural = "sistemas analíticos"
        ordering = ["equipamento", "numero_serie"]

    def __str__(self):
        return f"{self.equipamento} — nº {self.numero_serie} ({self.metodologia})"

    def clean(self):
        minimo = self.intervalo_analitico_minimo
        maximo = self.intervalo_analitico_maximo
        if minimo is not None and maximo is not None and minimo >= maximo:
            raise ValidationError(
                {"intervalo_analitico_maximo": "O máximo do intervalo analítico deve ser maior que o mínimo."}
            )


class InsumoRastreavel(models.Model):
    """Base dos insumos com lote e validade.

    A validade é verificada contra a data do estudo, não contra a data de hoje:
    o que importa numa auditoria é se o insumo estava válido quando a medição
    foi feita.
    """

    nome = models.CharField("nome", max_length=150)
    lote = models.CharField("lote", max_length=60)
    validade = models.DateField("validade")

    class Meta:
        abstract = True
        ordering = ["nome", "-validade"]

    def __str__(self):
        return f"{self.nome} — lote {self.lote} (val. {self.validade:%d/%m/%Y})"

    def vencido_em(self, data=None) -> bool:
        return self.validade < (data or timezone.localdate())


class Reagente(InsumoRastreavel):
    sistema = models.ForeignKey(
        SistemaAnalitico, verbose_name="sistema analítico", on_delete=models.CASCADE, related_name="reagentes"
    )

    class Meta(InsumoRastreavel.Meta):
        verbose_name = "reagente"
        verbose_name_plural = "reagentes"


class Calibrador(InsumoRastreavel):
    sistema = models.ForeignKey(
        SistemaAnalitico, verbose_name="sistema analítico", on_delete=models.CASCADE, related_name="calibradores"
    )

    class Meta(InsumoRastreavel.Meta):
        verbose_name = "calibrador"
        verbose_name_plural = "calibradores"


class Controle(InsumoRastreavel):
    """Material de controle usado no estudo de precisão, identificado por nível."""

    sistema = models.ForeignKey(
        SistemaAnalitico, verbose_name="sistema analítico", on_delete=models.CASCADE, related_name="controles"
    )
    nivel = models.PositiveSmallIntegerField("nível", help_text="1, 2, 3… conforme a concentração do material")
    valor_alvo = models.DecimalField(
        "valor alvo", max_digits=14, decimal_places=4, null=True, blank=True,
        help_text="Valor declarado pelo fabricante, quando houver."
    )

    class Meta(InsumoRastreavel.Meta):
        verbose_name = "material de controle"
        verbose_name_plural = "materiais de controle"
        ordering = ["nivel", "nome"]

    def __str__(self):
        return f"Nível {self.nivel} — {self.nome} — lote {self.lote}"


class EspecificacaoQualidade(models.Model):
    """Especificação da Qualidade Analítica (EQA): os limites de aceitação.

    Cada limite carrega obrigatoriamente a referência científica que o
    justifica. Um limite sem origem declarada não sustenta auditoria: a pergunta
    "por que 12%?" precisa de resposta documentada.

    Os campos absolutos implementam a regra "para resultados ≤ X, utilizar ± Y".
    Em concentrações baixas um limite percentual vira exigência impossível — 12%
    de um valor próximo de zero é uma janela menor que a resolução do próprio
    equipamento.
    """

    PROFICIENCIA = "proficiencia"
    VARIACAO_BIOLOGICA = "variacao_biologica"
    ESTADO_DA_ARTE = "estado_da_arte"
    MANUAL = "manual"

    FONTES = [
        (PROFICIENCIA, "Ensaio de proficiência"),
        (VARIACAO_BIOLOGICA, "Variação biológica"),
        (ESTADO_DA_ARTE, "Estado da arte"),
        (MANUAL, "Manual — valores e justificativas digitados"),
    ]

    # Como cada fonte redige a justificativa do erro total. As dos limites
    # derivados nascem desta, prefixadas pela fração.
    _MODELOS_DE_REFERENCIA = {
        PROFICIENCIA: "Limite de aceitabilidade do {descricao}",
        VARIACAO_BIOLOGICA: "Desempenho desejável a partir da variação biológica ({descricao})",
        ESTADO_DA_ARTE: "Estado da arte do método ({descricao})",
    }

    laboratorio = models.ForeignKey(
        Laboratorio, verbose_name="laboratório", on_delete=models.CASCADE, related_name="especificacoes"
    )
    mensurando = models.ForeignKey(
        Mensurando, verbose_name="mensurando", on_delete=models.CASCADE, related_name="especificacoes"
    )
    nome = models.CharField(
        "identificação", max_length=150,
        help_text="Ex.: FT4 — ControlLab 2026"
    )

    fonte = models.CharField(
        "fonte da especificação", max_length=25, choices=FONTES, default=MANUAL,
        help_text="Escolher uma fonte preenche as justificativas a partir do erro total."
    )
    fonte_descricao = models.CharField(
        "quem é a fonte", max_length=150, blank=True,
        help_text="Ex.: provedor de ensaio de proficiência ControlLab"
    )
    bias_derivado = models.BooleanField(
        "bias derivado do erro total", default=True,
        help_text="Metade do erro total. Desligue para digitar um valor próprio."
    )
    imprecisao_derivada = models.BooleanField(
        "imprecisão derivada do erro total", default=True,
        help_text="Um terço do erro total, aplicado a todos os níveis."
    )

    erro_total_maximo_pct = models.DecimalField(
        "erro total máximo (%)", max_digits=6, decimal_places=2, null=True, blank=True
    )
    erro_total_referencia = models.CharField(
        "referência do erro total", max_length=300, blank=True,
        help_text="Ex.: Limite de aceitabilidade do provedor de ensaio de proficiência ControlLab"
    )
    erro_total_limiar_absoluto = models.DecimalField(
        "aplicar limite absoluto para resultados ≤", max_digits=14, decimal_places=4, null=True, blank=True
    )
    erro_total_maximo_absoluto = models.DecimalField(
        "erro total máximo absoluto (±)", max_digits=14, decimal_places=4, null=True, blank=True
    )
    erro_total_referencia_absoluto = models.CharField(
        "referência do erro total absoluto", max_length=300, blank=True
    )

    bias_maximo_pct = models.DecimalField(
        "bias máximo (%)", max_digits=6, decimal_places=2, null=True, blank=True
    )
    bias_referencia = models.CharField(
        "referência do bias", max_length=300, blank=True,
        help_text="Ex.: 50% do limite de aceitabilidade do provedor ControlLab"
    )
    bias_limiar_absoluto = models.DecimalField(
        "aplicar limite absoluto para resultados ≤", max_digits=14, decimal_places=4, null=True, blank=True
    )
    bias_maximo_absoluto = models.DecimalField(
        "bias máximo absoluto (±)", max_digits=14, decimal_places=4, null=True, blank=True
    )
    bias_referencia_absoluto = models.CharField(
        "referência do bias absoluto", max_length=300, blank=True
    )

    nivel_significancia = models.DecimalField(
        "nível de significância (α)", max_digits=4, decimal_places=3, default=0.05
    )
    vigente_desde = models.DateField("vigente desde", default=timezone.localdate)
    criado_em = models.DateTimeField("criado em", auto_now_add=True)

    class Meta:
        verbose_name = "especificação da qualidade analítica"
        verbose_name_plural = "especificações da qualidade analítica"
        ordering = ["mensurando", "-vigente_desde"]

    def __str__(self):
        return f"{self.nome} — {self.mensurando.nome}"

    def referencia_base(self) -> str:
        """Frase que justifica o erro total, montada a partir da fonte escolhida."""
        modelo = self._MODELOS_DE_REFERENCIA.get(self.fonte)
        if not modelo or not self.fonte_descricao.strip():
            return ""
        return modelo.format(descricao=self.fonte_descricao.strip())

    def _fracao_da_referencia(self, fracao: str) -> str:
        base = self.referencia_base()
        if not base:
            return ""
        return f"{fracao} do {base[0].lower()}{base[1:]}"

    def aplicar_fonte(self):
        """Preenche valores e justificativas derivados do erro total.

        É o que transforma "escolhi o provedor" em três limites documentados. Só
        toca o que está marcado como derivado: um valor digitado à mão continua
        sendo do laboratório, e a justificativa do erro total só é reescrita
        quando a fonte sabe redigi-la.
        """
        base = self.referencia_base()
        if base:
            self.erro_total_referencia = base

        if self.erro_total_maximo_pct is None:
            return

        if self.bias_derivado:
            self.bias_maximo_pct = (self.erro_total_maximo_pct / 2).quantize(Decimal("0.01"))
            if base:
                self.bias_referencia = self._fracao_da_referencia("50%")

    def sincronizar_imprecisao(self):
        """Espalha a imprecisão derivada pelos níveis já cadastrados.

        A fração é 1/4, não 1/3, e a razão é aritmética: o erro total é
        ``bias + 1,65 × CV``. Com bias em 1/2 e imprecisão em 1/4 do erro total
        máximo, um método parado nos dois sub-limites chega a 0,91 do teto —
        cabe. Com imprecisão em 1/3 chegaria a 1,05 do teto, ou seja, todo
        método no limite seria automaticamente reprovado no terceiro indicador.
        É a partição desejável de Fraser/Westgard, e é a única das duas frações
        usuais que é coerente com a própria fórmula do erro total.
        """
        if not self.imprecisao_derivada or self.erro_total_maximo_pct is None:
            return
        valor = (self.erro_total_maximo_pct / 4).quantize(Decimal("0.01"))
        referencia = self._fracao_da_referencia("1/4")
        for limite in self.limites_imprecisao.all():
            limite.maximo_pct = valor
            if referencia:
                limite.referencia = referencia
            limite.save(update_fields=["maximo_pct", "referencia"])

    def erro_total_implicito(self):
        """Erro total de um método parado exatamente nos dois sub-limites.

        TE = |bias| + 1,65 × CV. Nos limites derivados (1/2 e 1/4 do erro total)
        esse número fica em 0,91 do teto e o alerta não dispara. Ele existe para
        o caso em que o laboratório digita os próprios limites: uma combinação
        como bias 6% com imprecisão 4% dá 12,6% e reprovaria um método que
        cumpre os dois — contradição que a ficha mostra em vez de esconder.
        """
        if self.bias_maximo_pct is None:
            return None
        imprecisoes = [
            limite.maximo_pct for limite in self.limites_imprecisao.all() if limite.maximo_pct is not None
        ]
        if not imprecisoes:
            return None
        return self.bias_maximo_pct + Decimal(str(FATOR_ERRO_TOTAL)) * max(imprecisoes)

    def sub_limites_excedem_o_erro_total(self) -> bool:
        implicito = self.erro_total_implicito()
        return (
            implicito is not None
            and self.erro_total_maximo_pct is not None
            and implicito > self.erro_total_maximo_pct
        )

    def para_o_motor(self):
        """Converte esta ficha no objeto que o motor de cálculo entende.

        Fica aqui, e não na camada de serviço, para que o catálogo não dependa
        do módulo de estudos — a ficha existe antes de qualquer estudo.
        """
        from motor import especificacoes as espec

        def numero(valor):
            return float(valor) if valor is not None else None

        return espec.EspecificacaoQualidade(
            erro_total=espec.LimiteQualidade(
                valor_pct=numero(self.erro_total_maximo_pct),
                referencia_pct=self.erro_total_referencia,
                limiar_absoluto=numero(self.erro_total_limiar_absoluto),
                valor_absoluto=numero(self.erro_total_maximo_absoluto),
                referencia_absoluto=self.erro_total_referencia_absoluto,
            ),
            bias=espec.LimiteQualidade(
                valor_pct=numero(self.bias_maximo_pct),
                referencia_pct=self.bias_referencia,
                limiar_absoluto=numero(self.bias_limiar_absoluto),
                valor_absoluto=numero(self.bias_maximo_absoluto),
                referencia_absoluto=self.bias_referencia_absoluto,
            ),
            imprecisao_por_nivel={
                limite.nivel: espec.LimiteQualidade(
                    valor_pct=numero(limite.maximo_pct), referencia_pct=limite.referencia
                )
                for limite in self.limites_imprecisao.all()
            },
            nivel_significancia=numero(self.nivel_significancia) or 0.05,
        )

    def pendencias_da_ficha(self) -> list[str]:
        """O que ainda falta para esta ficha sustentar um veredito."""
        return self.para_o_motor().pendencias()

    def save(self, *args, **kwargs):
        self.aplicar_fonte()
        super().save(*args, **kwargs)


class LimiteImprecisao(models.Model):
    """Imprecisão máxima admitida em um nível de controle.

    Fica separada da especificação porque cada nível pode ter exigência
    própria — a planilha de referência traz Nível 1, 2 e 3 independentes.
    """

    especificacao = models.ForeignKey(
        EspecificacaoQualidade, verbose_name="especificação", on_delete=models.CASCADE, related_name="limites_imprecisao"
    )
    nivel = models.PositiveSmallIntegerField("nível")
    maximo_pct = models.DecimalField("imprecisão máxima (%)", max_digits=6, decimal_places=2)
    referencia = models.CharField(
        "referência científica", max_length=300,
        help_text="Ex.: 1/3 do limite de aceitabilidade do provedor ControlLab"
    )

    class Meta:
        verbose_name = "limite de imprecisão"
        verbose_name_plural = "limites de imprecisão"
        ordering = ["nivel"]
        constraints = [
            models.UniqueConstraint(
                fields=["especificacao", "nivel"], name="limite_imprecisao_unico_por_nivel"
            )
        ]

    def __str__(self):
        return f"Nível {self.nivel} — máx. {self.maximo_pct}%"
