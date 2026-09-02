"""Testes do módulo qualitativo (CLSI EP12)."""

import pytest

from motor import estatistica as est
from motor import qualitativo as qual


class TestTabelaContingencia:
    def test_monta_a_tabela_a_partir_de_booleanos(self):
        referencia = [True, True, False, False]
        teste = [True, False, True, False]

        tabela = qual.tabela_contingencia(referencia, teste)

        assert tabela["verdadeiros_positivos"] == 1
        assert tabela["falsos_negativos"] == 1
        assert tabela["falsos_positivos"] == 1
        assert tabela["verdadeiros_negativos"] == 1
        assert tabela["n"] == 4

    def test_aceita_as_formas_usuais_de_registro(self):
        # O laboratório digita "Reagente"/"Não Reagente", "POS"/"NEG", 1/0.
        referencia = ["Positivo", "reagente", "NEG", "não reagente", 1, 0]
        teste = ["POS", "P", "negativo", "N", "sim", "não"]

        tabela = qual.tabela_contingencia(referencia, teste)

        assert tabela["n"] == 6
        assert tabela["verdadeiros_positivos"] == 3
        assert tabela["verdadeiros_negativos"] == 3

    def test_descarta_par_com_resultado_ilegivel(self):
        tabela = qual.tabela_contingencia(
            ["Positivo", "indeterminado", "Negativo"],
            ["Positivo", "Positivo", "Negativo"],
        )

        assert tabela["n"] == 2
        assert tabela["descartados"] == 1


class TestDesempenho:
    def test_indicadores_com_valores_conferiveis_a_mao(self):
        # VP=45, FP=5, FN=10, VN=40 (n=100)
        # Sensibilidade = 45/55 = 81,82%
        # Especificidade = 40/45 = 88,89%
        # Concordância = 85/100 = 85%
        tabela = {
            "verdadeiros_positivos": 45,
            "falsos_positivos": 5,
            "falsos_negativos": 10,
            "verdadeiros_negativos": 40,
            "n": 100,
            "descartados": 0,
        }

        resultado = qual.desempenho(tabela)

        assert resultado["sensibilidade_pct"] == pytest.approx(45 / 55 * 100)
        assert resultado["especificidade_pct"] == pytest.approx(40 / 45 * 100)
        assert resultado["concordancia_pct"] == pytest.approx(85.0)

    def test_kappa_conferivel_a_mao(self):
        # Mesma tabela: concordância observada = 0,85
        # Concordância esperada = (55×50 + 45×50) / 100² = 5000/10000 = 0,50
        # Kappa = (0,85 − 0,50) / (1 − 0,50) = 0,70
        tabela = {
            "verdadeiros_positivos": 45,
            "falsos_positivos": 5,
            "falsos_negativos": 10,
            "verdadeiros_negativos": 40,
            "n": 100,
            "descartados": 0,
        }

        resultado = qual.desempenho(tabela)

        assert resultado["kappa"] == pytest.approx(0.70)
        assert resultado["classificacao_kappa"] == "substancial (0,61–0,80)"

    def test_kappa_expoe_o_teste_que_so_diz_negativo(self):
        # Doença rara (2%) e um teste que responde "negativo" para todos:
        # acerta 98% dos casos e não tem valor nenhum. A concordância bruta
        # elogia esse teste; o kappa o reprova.
        tabela = {
            "verdadeiros_positivos": 0,
            "falsos_positivos": 0,
            "falsos_negativos": 2,
            "verdadeiros_negativos": 98,
            "n": 100,
            "descartados": 0,
        }

        resultado = qual.desempenho(tabela)

        assert resultado["concordancia_pct"] == pytest.approx(98.0)
        assert resultado["sensibilidade_pct"] == pytest.approx(0.0)
        assert resultado["kappa"] == pytest.approx(0.0)

    def test_valores_preditivos_dependem_da_prevalencia(self):
        # Mesmo teste, prevalências diferentes: o VPP desaba quando a doença
        # é rara. É por isso que o VPP da amostra estudada não pode ser
        # apresentado como se valesse para a população atendida.
        tabela = {
            "verdadeiros_positivos": 90,
            "falsos_positivos": 10,
            "falsos_negativos": 10,
            "verdadeiros_negativos": 90,
            "n": 200,
            "descartados": 0,
        }

        alta = qual.desempenho(tabela, prevalencia_pct=50.0)
        baixa = qual.desempenho(tabela, prevalencia_pct=1.0)

        assert alta["vpp_pct"] > 85
        assert baixa["vpp_pct"] < 15
        assert baixa["prevalencia_usada_pct"] == 1.0

    def test_sem_positivos_na_referencia_nao_ha_sensibilidade(self):
        tabela = {
            "verdadeiros_positivos": 0,
            "falsos_positivos": 3,
            "falsos_negativos": 0,
            "verdadeiros_negativos": 47,
            "n": 50,
            "descartados": 0,
        }

        resultado = qual.desempenho(tabela)

        assert resultado["sensibilidade_pct"] is None
        assert resultado["especificidade_pct"] == pytest.approx(94.0)


class TestIntervaloWilson:
    def test_nao_colapsa_quando_o_acerto_e_total(self):
        # 10 acertos em 10. O intervalo clássico devolveria (100%, 100%),
        # afirmando certeza absoluta a partir de dez observações. O de Wilson
        # mantém o limite inferior honesto.
        intervalo = est.intervalo_wilson(10, 10)

        assert intervalo[0] < 80.0
        assert intervalo[1] == pytest.approx(100.0)

    def test_intervalo_encolhe_com_mais_observacoes(self):
        estreito = est.intervalo_wilson(500, 1000)
        largo = est.intervalo_wilson(5, 10)

        assert (estreito[1] - estreito[0]) < (largo[1] - largo[0])

    def test_permanece_dentro_de_zero_e_cem(self):
        for sucessos, total in [(0, 5), (5, 5), (1, 3), (0, 1)]:
            inferior, superior = est.intervalo_wilson(sucessos, total)
            assert 0.0 <= inferior <= superior <= 100.0

    def test_entrada_invalida(self):
        assert est.intervalo_wilson(5, 0) is None
        assert est.intervalo_wilson(11, 10) is None
