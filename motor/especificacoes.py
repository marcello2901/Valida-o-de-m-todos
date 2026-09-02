"""Especificação da Qualidade Analítica (EQA) — os limites de aceitação.

Traduz para código a seção de EQA da planilha de validação: erro total máximo,
erro sistemático (bias) máximo e imprecisão máxima por nível, cada um em versão
percentual e absoluta, e cada um acompanhado da **referência cientificamente
válida** que o justifica.

A referência não é enfeite documental. Um limite de aceitação sem origem
declarada ("por que 12%?") não sustenta auditoria nem acreditação. Por isso o
campo é obrigatório junto do valor: quem definir um limite aqui é obrigado a
dizer de onde ele veio — provedor de ensaio de proficiência, variação biológica,
estado da arte ou requisito regulatório.

A regra do limite absoluto existe porque, em concentrações baixas, um limite
percentual vira exigência impossível: 12% de um resultado próximo de zero é uma
janela menor que a própria resolução do equipamento. Abaixo de um limiar
definido pelo laboratório, o critério passa a ser uma quantidade fixa na unidade
de medida.
"""

from __future__ import annotations

from dataclasses import dataclass, field

PERCENTUAL = "percentual"
ABSOLUTO = "absoluto"


@dataclass
class LimiteQualidade:
    """Um limite de aceitação, na forma percentual e opcionalmente absoluta.

    ``limiar_absoluto`` e ``valor_absoluto`` implementam a regra da planilha:
    "para resultados ≤ limiar, utilizar ± valor (unidade de medida)".
    """

    valor_pct: float | None = None
    referencia_pct: str = ""
    limiar_absoluto: float | None = None
    valor_absoluto: float | None = None
    referencia_absoluto: str = ""

    def aplicar(self, concentracao: float | None) -> dict:
        """Resolve qual critério vale nesta concentração e devolve o limite efetivo.

        Retorna sempre o limite nas duas escalas quando a conversão é possível,
        além de qual regra foi aplicada e a referência correspondente — o
        relatório precisa dessas três informações juntas para ser auditável.
        """
        usa_absoluto = (
            concentracao is not None
            and self.limiar_absoluto is not None
            and self.valor_absoluto is not None
            and concentracao <= self.limiar_absoluto
        )

        if usa_absoluto:
            limite_abs = self.valor_absoluto
            limite_pct = (
                (limite_abs / concentracao) * 100
                if concentracao not in (None, 0)
                else None
            )
            return {
                "tipo": ABSOLUTO,
                "limite_absoluto": limite_abs,
                "limite_pct": limite_pct,
                "referencia": self.referencia_absoluto,
                "definido": limite_abs is not None,
            }

        limite_abs = (
            (self.valor_pct / 100) * concentracao
            if self.valor_pct is not None and concentracao is not None
            else None
        )
        return {
            "tipo": PERCENTUAL,
            "limite_absoluto": limite_abs,
            "limite_pct": self.valor_pct,
            "referencia": self.referencia_pct,
            "definido": self.valor_pct is not None,
        }


@dataclass
class EspecificacaoQualidade:
    """Conjunto completo de limites de aceitação de um mensurando.

    ``imprecisao_por_nivel`` mapeia o número do nível de controle (1, 2, 3…)
    para o limite de imprecisão daquele nível — níveis diferentes de controle
    podem ter exigências diferentes.
    """

    erro_total: LimiteQualidade = field(default_factory=LimiteQualidade)
    bias: LimiteQualidade = field(default_factory=LimiteQualidade)
    imprecisao_por_nivel: dict[int, LimiteQualidade] = field(default_factory=dict)
    nivel_significancia: float = 0.05

    def imprecisao_do_nivel(self, nivel: int) -> LimiteQualidade:
        """Limite de imprecisão do nível pedido; vazio se o nível não foi especificado."""
        return self.imprecisao_por_nivel.get(nivel, LimiteQualidade())

    def pendencias(self) -> list[str]:
        """Lista o que falta preencher para a especificação sustentar um veredito.

        Chamada antes de qualquer avaliação: é preferível recusar o cálculo a
        emitir um resultado apoiado em limite sem origem declarada.
        """
        faltas = []

        if self.erro_total.valor_pct is None and self.erro_total.valor_absoluto is None:
            faltas.append("erro total máximo não definido")
        elif (
            self.erro_total.valor_pct is not None
            and not self.erro_total.referencia_pct.strip()
        ):
            faltas.append("erro total máximo percentual sem referência científica")

        if self.bias.valor_pct is None and self.bias.valor_absoluto is None:
            faltas.append("bias máximo não definido")
        elif self.bias.valor_pct is not None and not self.bias.referencia_pct.strip():
            faltas.append("bias máximo percentual sem referência científica")

        if not self.imprecisao_por_nivel:
            faltas.append("imprecisão máxima não definida para nenhum nível")
        else:
            for nivel, limite in sorted(self.imprecisao_por_nivel.items()):
                if limite.valor_pct is not None and not limite.referencia_pct.strip():
                    faltas.append(
                        f"imprecisão do nível {nivel} sem referência científica"
                    )

        return faltas
