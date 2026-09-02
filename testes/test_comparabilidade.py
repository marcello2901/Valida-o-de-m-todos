"""Testes do módulo de comparabilidade (CLSI EP09).

A regressão de Deming é conferida contra uma implementação independente: a
primeira componente principal calculada pelo numpy. São dois caminhos numéricos
distintos para o mesmo resultado — se ambos concordam, o erro teria que estar
nos dois ao mesmo tempo.
"""

import numpy as np
import pytest

from motor import comparabilidade as comp


def inclinacao_por_componente_principal(x, y):
    """Regressão ortogonal via decomposição da matriz de covariância (numpy).

    Caminho independente do usado em ``motor.comparabilidade.deming``: aqui a
    direção da reta vem do autovetor dominante, não da fórmula fechada.
    """
    dados = np.column_stack([np.asarray(x, dtype=float), np.asarray(y, dtype=float)])
    centrados = dados - dados.mean(axis=0)
    covariancia = np.cov(centrados, rowvar=False)
    autovalores, autovetores = np.linalg.eigh(covariancia)
    principal = autovetores[:, np.argmax(autovalores)]
    return principal[1] / principal[0]


class TestDeming:
    def test_reta_exata_e_recuperada(self):
        # Pontos exatamente sobre y = 2x + 1: qualquer regressão honesta
        # devolve inclinação 2 e intercepto 1.
        resultado = comp.deming([1, 2, 3, 4, 5], [3, 5, 7, 9, 11])

        assert resultado["inclinacao"] == pytest.approx(2.0)
        assert resultado["intercepto"] == pytest.approx(1.0)
        assert resultado["metodo"] == "Deming"

    def test_confere_com_componente_principal_do_numpy(self):
        # Dados com dispersão nos dois eixos, como numa comparação real.
        x = [10.2, 20.5, 31.1, 39.8, 50.4, 60.9, 70.2, 80.7, 90.1, 99.6]
        y = [11.1, 21.0, 30.4, 41.2, 49.7, 62.0, 69.5, 82.1, 89.4, 101.2]

        deming = comp.deming(x, y, lambda_erro=1.0)

        assert deming["inclinacao"] == pytest.approx(
            inclinacao_por_componente_principal(x, y), rel=1e-9
        )

    def test_lambda_invalido_e_recusado(self):
        resultado = comp.deming([1, 2, 3], [2, 4, 6], lambda_erro=0)

        assert resultado["inclinacao"] is None

    def test_poucas_amostras_nao_geram_reta(self):
        resultado = comp.deming([1, 2], [2, 4])

        assert resultado["inclinacao"] is None
        assert "3 amostras" in resultado["observacao"]

    def test_sem_variacao_no_metodo_de_comparacao(self):
        # Todas as amostras com o mesmo valor em X: não há reta a estimar.
        resultado = comp.deming([5, 5, 5, 5], [4, 6, 5, 7])

        assert resultado["inclinacao"] is None
        assert "covariância" in resultado["observacao"]

    def test_sinaliza_quando_nao_atinge_o_minimo_do_ep09(self):
        poucas = comp.deming([1, 2, 3, 4, 5], [1, 2, 3, 4, 5])
        assert poucas["atende_minimo_ep09"] is False

        muitas = comp.deming(list(range(1, 45)), list(range(1, 45)))
        assert muitas["atende_minimo_ep09"] is True


class TestPassingBablok:
    def test_reta_exata_e_recuperada(self):
        resultado = comp.passing_bablok([1, 2, 3, 4, 5], [3, 5, 7, 9, 11])

        assert resultado["inclinacao"] == pytest.approx(2.0)
        assert resultado["intercepto"] == pytest.approx(1.0)

    def test_inclinacao_e_reciproca_ao_inverter_os_eixos(self):
        # Propriedade do estimador: trocar comparação por teste tem de produzir
        # a inclinação recíproca. Regressão por mínimos quadrados NÃO tem essa
        # propriedade — é justamente por isso que ela não serve aqui.
        x = [10.0, 20.0, 30.0, 40.0, 52.0, 61.0]
        y = [11.0, 19.0, 32.0, 39.0, 50.0, 63.0]

        direta = comp.passing_bablok(x, y)
        inversa = comp.passing_bablok(y, x)

        assert direta["inclinacao"] == pytest.approx(
            1 / inversa["inclinacao"], rel=1e-9
        )

    def test_resiste_a_valor_discrepante(self):
        # Um ponto grosseiramente errado desloca pouco a mediana das
        # inclinações, enquanto arrastaria uma regressão de mínimos quadrados.
        x = [10.0, 20.0, 30.0, 40.0, 50.0, 60.0, 70.0]
        y_limpo = [10.0, 20.0, 30.0, 40.0, 50.0, 60.0, 70.0]
        y_com_erro = [10.0, 20.0, 30.0, 40.0, 50.0, 60.0, 700.0]

        limpo = comp.passing_bablok(x, y_limpo)
        sujo = comp.passing_bablok(x, y_com_erro)

        assert limpo["inclinacao"] == pytest.approx(1.0)
        assert sujo["inclinacao"] == pytest.approx(1.0)

    def test_poucas_amostras_nao_geram_reta(self):
        resultado = comp.passing_bablok([1, 2], [2, 4])

        assert resultado["inclinacao"] is None


class TestBlandAltman:
    def test_vies_medio_e_limites(self):
        # Diferenças (teste − comparação): 2, 2, 2, 2 → viés 2, DP 0
        resultado = comp.bland_altman([10, 20, 30, 40], [12, 22, 32, 42])

        assert resultado["n"] == 4
        assert resultado["vies"] == pytest.approx(2.0)
        assert resultado["vies_pct"] == pytest.approx(2 / 25 * 100)
        assert resultado["desvio_padrao_diferencas"] == pytest.approx(0.0)
        assert resultado["limite_inferior"] == pytest.approx(2.0)
        assert resultado["limite_superior"] == pytest.approx(2.0)

    def test_limites_de_concordancia_com_dispersao(self):
        # Diferenças: 1, 3, 1, 3 → média 2 ; DP amostral = sqrt(4/3)
        resultado = comp.bland_altman([10, 20, 30, 40], [11, 23, 31, 43])
        dp = resultado["desvio_padrao_diferencas"]

        assert resultado["vies"] == pytest.approx(2.0)
        assert dp == pytest.approx((4 / 3) ** 0.5)
        assert resultado["limite_superior"] == pytest.approx(2 + 1.96 * dp)
        assert resultado["limite_inferior"] == pytest.approx(2 - 1.96 * dp)

    def test_par_incompleto_e_descartado_inteiro(self):
        # Amostra sem resultado no método novo não pode desalinhar os demais.
        resultado = comp.bland_altman([10, 20, 30], [12, None, 32])

        assert resultado["n"] == 2
        assert resultado["vies"] == pytest.approx(2.0)

    def test_sem_dados(self):
        resultado = comp.bland_altman([], [])

        assert resultado["n"] == 0
        assert resultado["vies"] is None


class TestBiasNoNivel:
    def test_bias_no_ponto_de_decisao_clinica(self):
        # Reta y = 1,10x + 0 avaliada em 100: estimado 110, bias +10 (+10%).
        resultado = comp.bias_no_nivel(inclinacao=1.10, intercepto=0.0, nivel=100)

        assert resultado["valor_estimado"] == pytest.approx(110.0)
        assert resultado["bias"] == pytest.approx(10.0)
        assert resultado["bias_pct"] == pytest.approx(10.0)

    def test_vies_constante_pesa_mais_em_concentracao_baixa(self):
        # Reta y = x + 1: o mesmo desvio absoluto de 1 unidade representa 10%
        # em concentração 10 e apenas 1% em concentração 100. É por isso que o
        # bias precisa ser avaliado no nível de decisão, não na média geral.
        baixo = comp.bias_no_nivel(1.0, 1.0, 10)
        alto = comp.bias_no_nivel(1.0, 1.0, 100)

        assert baixo["bias_pct"] == pytest.approx(10.0)
        assert alto["bias_pct"] == pytest.approx(1.0)

    def test_sem_reta_nao_ha_bias(self):
        resultado = comp.bias_no_nivel(None, None, 100)

        assert resultado["bias"] is None
