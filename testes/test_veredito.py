"""Testes do motor de veredito — a parte que decide aprovação e reprovação.

O primeiro teste desta suíte guarda o defeito encontrado na versão original da
ferramenta, em que o bias era um número fixo escrito no código e o sistema
exibia "MÉTODO VALIDADO" a partir dele. É o teste que impede o defeito de
voltar.
"""

import pytest

from motor import especificacoes as espec
from motor import veredito as ver


def especificacao_completa():
    """EQA nos moldes da planilha de referência (FT4, ControlLab)."""
    return espec.EspecificacaoQualidade(
        erro_total=espec.LimiteQualidade(
            valor_pct=12.0,
            referencia_pct="Limite de aceitabilidade do provedor de ensaio de proficiência ControlLab",
        ),
        bias=espec.LimiteQualidade(
            valor_pct=6.0,
            referencia_pct="50% do limite de aceitabilidade do provedor ControlLab",
        ),
        imprecisao_por_nivel={
            1: espec.LimiteQualidade(
                valor_pct=4.0, referencia_pct="1/3 do limite ControlLab"
            ),
            2: espec.LimiteQualidade(
                valor_pct=4.0, referencia_pct="1/3 do limite ControlLab"
            ),
            3: espec.LimiteQualidade(
                valor_pct=4.0, referencia_pct="1/3 do limite ControlLab"
            ),
        },
    )


class TestNaoInventarVeredito:
    def test_sem_bias_nao_existe_aprovacao(self):
        # Defeito original: bias fixo em 1,5 no código produzia veredito de
        # método validado. Sem estudo de comparabilidade, o erro total não é
        # calculável e o sistema tem de dizer isso.
        resultado = ver.avaliar_estudo(
            modulo=ver.MODULO_COMPLETO,
            especificacao=especificacao_completa(),
            niveis=[{"nivel": 1, "concentracao": 1.0, "cv_pct": 2.0, "bias_pct": None}],
        )

        assert resultado["status"] == ver.INDETERMINADO

        erro_total = _indicador(resultado, 1, "erro total")
        assert erro_total["observado_pct"] is None
        assert "bias% do estudo de comparabilidade" in erro_total["faltantes"]

    def test_sem_cv_nao_existe_aprovacao(self):
        resultado = ver.avaliar_estudo(
            modulo=ver.MODULO_COMPLETO,
            especificacao=especificacao_completa(),
            niveis=[{"nivel": 1, "concentracao": 1.0, "cv_pct": None, "bias_pct": 1.0}],
        )

        assert resultado["status"] == ver.INDETERMINADO

    def test_limite_sem_referencia_cientifica_bloqueia_aprovacao(self):
        # Um limite de aceitação sem origem declarada não sustenta auditoria.
        sem_referencia = espec.EspecificacaoQualidade(
            erro_total=espec.LimiteQualidade(valor_pct=12.0, referencia_pct="   "),
            bias=espec.LimiteQualidade(valor_pct=6.0, referencia_pct="ControlLab"),
            imprecisao_por_nivel={
                1: espec.LimiteQualidade(valor_pct=4.0, referencia_pct="ControlLab")
            },
        )

        resultado = ver.avaliar_estudo(
            modulo=ver.MODULO_COMPLETO,
            especificacao=sem_referencia,
            niveis=[{"nivel": 1, "concentracao": 1.0, "cv_pct": 1.0, "bias_pct": 1.0}],
        )

        assert resultado["status"] == ver.INDETERMINADO
        assert resultado["pendencias_especificacao"]

    def test_indicador_nao_avaliado_impede_aprovacao_do_conjunto(self):
        # Nível 4 não tem limite de imprecisão especificado. O conjunto não
        # pode ser aprovado com um indicador em branco.
        resultado = ver.avaliar_estudo(
            modulo=ver.MODULO_COMPLETO,
            especificacao=especificacao_completa(),
            niveis=[{"nivel": 4, "concentracao": 1.0, "cv_pct": 1.0, "bias_pct": 1.0}],
        )

        assert resultado["status"] == ver.INDETERMINADO


class TestModulosContratados:
    def test_precisao_isolada_nao_calcula_erro_total(self):
        # Consequência comercial: o plano de precisão não entrega veredito de
        # validação, porque erro total exige bias.
        resultado = ver.avaliar_estudo(
            modulo=ver.MODULO_PRECISAO,
            especificacao=especificacao_completa(),
            niveis=[{"nivel": 1, "concentracao": 1.0, "cv_pct": 2.0, "bias_pct": 1.0}],
        )

        indicadores = [i["indicador"] for i in resultado["niveis"][0]["indicadores"]]
        assert indicadores == ["imprecisão"]
        assert "erro total" in resultado["niveis"][0]["nao_contratados"]
        assert resultado["niveis"][0]["sigma"] is None

    def test_comparabilidade_isolada_avalia_apenas_bias(self):
        resultado = ver.avaliar_estudo(
            modulo=ver.MODULO_COMPARABILIDADE,
            especificacao=especificacao_completa(),
            niveis=[{"nivel": 1, "concentracao": 1.0, "cv_pct": 2.0, "bias_pct": 1.0}],
        )

        indicadores = [i["indicador"] for i in resultado["niveis"][0]["indicadores"]]
        assert indicadores == ["bias"]

    def test_pacote_completo_avalia_tudo(self):
        resultado = ver.avaliar_estudo(
            modulo=ver.MODULO_COMPLETO,
            especificacao=especificacao_completa(),
            niveis=[{"nivel": 1, "concentracao": 1.0, "cv_pct": 2.0, "bias_pct": 1.0}],
        )

        indicadores = [i["indicador"] for i in resultado["niveis"][0]["indicadores"]]
        assert indicadores == ["imprecisão", "bias", "erro total"]
        assert resultado["niveis"][0]["sigma"] is not None


class TestDecisoes:
    def test_metodo_dentro_de_todos_os_limites_e_aprovado(self):
        # CV 2% (limite 4%) ; bias 1% (limite 6%)
        # Erro total = 1 + 1,65×2 = 4,3% (limite 12%)
        resultado = ver.avaliar_estudo(
            modulo=ver.MODULO_COMPLETO,
            especificacao=especificacao_completa(),
            niveis=[{"nivel": 1, "concentracao": 1.0, "cv_pct": 2.0, "bias_pct": 1.0}],
        )

        assert resultado["status"] == ver.APROVADO
        assert _indicador(resultado, 1, "erro total")["observado_pct"] == pytest.approx(
            4.3
        )

    def test_imprecisao_acima_do_limite_reprova(self):
        # CV 5% contra limite de 4%: reprovado mesmo com erro total dentro.
        resultado = ver.avaliar_estudo(
            modulo=ver.MODULO_COMPLETO,
            especificacao=especificacao_completa(),
            niveis=[{"nivel": 1, "concentracao": 1.0, "cv_pct": 5.0, "bias_pct": 1.0}],
        )

        assert resultado["status"] == ver.REPROVADO
        assert _indicador(resultado, 1, "imprecisão")["status"] == ver.REPROVADO

    def test_bias_negativo_e_avaliado_em_modulo(self):
        # Ler 7% abaixo é tão reprovável quanto ler 7% acima.
        resultado = ver.avaliar_estudo(
            modulo=ver.MODULO_COMPLETO,
            especificacao=especificacao_completa(),
            niveis=[{"nivel": 1, "concentracao": 1.0, "cv_pct": 1.0, "bias_pct": -7.0}],
        )

        assert _indicador(resultado, 1, "bias")["status"] == ver.REPROVADO

    def test_reprovacao_em_um_nivel_reprova_o_estudo(self):
        resultado = ver.avaliar_estudo(
            modulo=ver.MODULO_COMPLETO,
            especificacao=especificacao_completa(),
            niveis=[
                {"nivel": 1, "concentracao": 1.0, "cv_pct": 2.0, "bias_pct": 1.0},
                {"nivel": 2, "concentracao": 5.0, "cv_pct": 9.0, "bias_pct": 1.0},
            ],
        )

        assert resultado["status"] == ver.REPROVADO
        assert resultado["niveis"][0]["status"] == ver.APROVADO
        assert resultado["niveis"][1]["status"] == ver.REPROVADO


class TestErroTotalESigma:
    def test_formula_do_erro_total(self):
        # TE% = |bias%| + 1,65 × CV%
        assert ver.calcular_erro_total(2.0, 3.0) == pytest.approx(2 + 1.65 * 3)
        assert ver.calcular_erro_total(-2.0, 3.0) == pytest.approx(2 + 1.65 * 3)
        assert ver.calcular_erro_total(None, 3.0) is None

    def test_formula_do_sigma(self):
        # σ = (12 − 2) / 2 = 5
        assert ver.calcular_sigma(12.0, 2.0, 2.0) == pytest.approx(5.0)
        assert ver.classificar_sigma(5.0) == "excelente (5 ≤ σ < 6)"

    def test_cv_zero_nao_produz_sigma_infinito(self):
        # Réplicas idênticas quase sempre significam erro de digitação, não
        # método perfeito. Devolver sigma infinito seria premiar o erro.
        assert ver.calcular_sigma(12.0, 1.0, 0.0) is None
        assert ver.classificar_sigma(None) == "não calculável"

    def test_escala_sigma(self):
        assert ver.classificar_sigma(6.5).startswith("classe mundial")
        assert ver.classificar_sigma(4.2).startswith("bom")
        assert ver.classificar_sigma(3.1).startswith("marginal")
        assert ver.classificar_sigma(2.0).startswith("inaceitável")


class TestLimiteAbsolutoEmConcentracaoBaixa:
    def test_abaixo_do_limiar_vale_o_criterio_absoluto(self):
        # "Para resultados ≤ 1,0 ng/dL utilizar Erro Total Máximo de ± 0,2 ng/dL"
        # Em 0,5 ng/dL, 0,2 equivale a 40% — bem mais permissivo que os 12%.
        limite = espec.LimiteQualidade(
            valor_pct=12.0,
            referencia_pct="ControlLab",
            limiar_absoluto=1.0,
            valor_absoluto=0.2,
            referencia_absoluto="Estado da arte para baixas concentrações",
        )

        resolvido = limite.aplicar(concentracao=0.5)

        assert resolvido["tipo"] == espec.ABSOLUTO
        assert resolvido["limite_absoluto"] == pytest.approx(0.2)
        assert resolvido["limite_pct"] == pytest.approx(40.0)
        assert resolvido["referencia"] == "Estado da arte para baixas concentrações"

    def test_acima_do_limiar_vale_o_criterio_percentual(self):
        limite = espec.LimiteQualidade(
            valor_pct=12.0,
            referencia_pct="ControlLab",
            limiar_absoluto=1.0,
            valor_absoluto=0.2,
            referencia_absoluto="Estado da arte",
        )

        resolvido = limite.aplicar(concentracao=5.0)

        assert resolvido["tipo"] == espec.PERCENTUAL
        assert resolvido["limite_pct"] == pytest.approx(12.0)
        assert resolvido["limite_absoluto"] == pytest.approx(0.6)
        assert resolvido["referencia"] == "ControlLab"

    def test_a_regra_muda_o_veredito(self):
        # Um erro total observado de 30% em concentração baixa: reprovado pelo
        # critério percentual, aprovado pelo absoluto. Sem essa regra, métodos
        # corretos seriam reprovados perto do limite de detecção.
        com_regra = espec.EspecificacaoQualidade(
            erro_total=espec.LimiteQualidade(
                valor_pct=12.0,
                referencia_pct="ControlLab",
                limiar_absoluto=1.0,
                valor_absoluto=0.2,
                referencia_absoluto="Estado da arte",
            ),
            bias=espec.LimiteQualidade(valor_pct=50.0, referencia_pct="ControlLab"),
            imprecisao_por_nivel={
                1: espec.LimiteQualidade(valor_pct=50.0, referencia_pct="ControlLab")
            },
        )

        resultado = ver.avaliar_estudo(
            modulo=ver.MODULO_COMPLETO,
            especificacao=com_regra,
            niveis=[
                {"nivel": 1, "concentracao": 0.5, "cv_pct": 10.0, "bias_pct": 13.5}
            ],
        )

        erro_total = _indicador(resultado, 1, "erro total")
        assert erro_total["observado_pct"] == pytest.approx(30.0)
        assert erro_total["limite_pct"] == pytest.approx(40.0)
        assert erro_total["tipo_limite"] == espec.ABSOLUTO
        assert erro_total["status"] == ver.APROVADO


class TestConsolidacao:
    def test_precedencia_dos_status(self):
        assert ver.consolidar_status([ver.APROVADO, ver.APROVADO]) == ver.APROVADO
        assert (
            ver.consolidar_status([ver.APROVADO, ver.INDETERMINADO])
            == ver.INDETERMINADO
        )
        assert ver.consolidar_status([ver.APROVADO, ver.REPROVADO]) == ver.REPROVADO
        assert (
            ver.consolidar_status([ver.INDETERMINADO, ver.REPROVADO]) == ver.REPROVADO
        )
        assert ver.consolidar_status([]) == ver.INDETERMINADO


def _indicador(resultado: dict, nivel: int, nome: str) -> dict:
    """Localiza um indicador específico dentro do resultado do estudo."""
    for avaliacao in resultado["niveis"]:
        if avaliacao["nivel"] == nivel:
            for indicador in avaliacao["indicadores"]:
                if indicador["indicador"] == nome:
                    return indicador
    raise AssertionError(f"indicador '{nome}' não encontrado no nível {nivel}")
