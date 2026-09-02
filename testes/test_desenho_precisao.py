"""Testes da escolha de desenho do estudo de precisão.

A escolha entre "5 dias" e "tudo num dia" não é preferência de agenda: ela
determina qual erro o estudo consegue enxergar. Estes testes guardam essa
diferença.
"""

import pytest

from motor import comparabilidade as comp
from motor import precisao


class TestDesenhoCorridaUnica:
    def test_mede_repetibilidade_e_nao_precisao_intermediaria(self):
        replicas = [[10.0, 10.2, 9.8, 10.1, 9.9, 10.3, 9.7, 10.0, 10.1, 9.9]]

        resultado = precisao.avaliar_precisao(replicas, precisao.DESENHO_CORRIDA_UNICA)

        assert resultado["cv_repetibilidade"] is not None
        assert resultado["cv_intermediaria"] is None
        assert resultado["tipo_cv_aplicavel"] == precisao.REPETIBILIDADE
        assert resultado["cv_aplicavel"] == resultado["cv_repetibilidade"]

    def test_sempre_avisa_que_subestima_o_erro_da_rotina(self):
        # Mesmo com o número de réplicas em dia, o aviso permanece: a variação
        # entre dias não foi observada e o Erro Total sai otimista.
        replicas = [[10.0] * 5 + [10.2] * 5]

        resultado = precisao.avaliar_precisao(replicas, precisao.DESENHO_CORRIDA_UNICA)

        assert resultado["atende_minimo"] is True
        assert any("subestima" in aviso for aviso in resultado["avisos"])

    def test_menos_de_dez_replicas_nao_atende_o_minimo(self):
        resultado = precisao.avaliar_precisao(
            [[10.0, 10.2, 9.8, 10.1, 9.9]], precisao.DESENHO_CORRIDA_UNICA
        )

        assert resultado["n_total"] == 5
        assert resultado["atende_minimo"] is False
        assert any("10 réplicas" in aviso for aviso in resultado["avisos"])

    def test_varias_corridas_informadas_sao_tratadas_como_bloco_unico(self):
        # O usuário escolheu corrida única mas digitou os dados em dois dias:
        # o sistema calcula o que foi pedido e avisa o que deixou de avaliar.
        resultado = precisao.avaliar_precisao(
            [[10.0] * 5, [12.0] * 5], precisao.DESENHO_CORRIDA_UNICA
        )

        assert resultado["n_total"] == 10
        assert resultado["cv_intermediaria"] is None
        assert any("corrida única" in aviso for aviso in resultado["avisos"])


class TestDesenhoMultiplasCorridas:
    def cinco_dias(self):
        return [
            [10.0, 10.2, 9.8, 10.1, 9.9],
            [10.1, 10.3, 9.9, 10.2, 10.0],
            [9.9, 10.1, 9.7, 10.0, 9.8],
            [10.2, 10.4, 10.0, 10.3, 10.1],
            [10.0, 10.2, 9.8, 10.1, 9.9],
        ]

    def test_mede_as_duas_precisoes(self):
        resultado = precisao.avaliar_precisao(
            self.cinco_dias(), precisao.DESENHO_MULTIPLAS_CORRIDAS
        )

        assert resultado["cv_repetibilidade"] is not None
        assert resultado["cv_intermediaria"] is not None
        assert resultado["tipo_cv_aplicavel"] == precisao.INTERMEDIARIA
        assert resultado["atende_minimo"] is True
        assert resultado["avisos"] == []

    def test_o_cv_que_vai_para_o_erro_total_e_o_intermediario(self):
        # É o número maior, e é o correto: representa o método na rotina.
        resultado = precisao.avaliar_precisao(
            self.cinco_dias(), precisao.DESENHO_MULTIPLAS_CORRIDAS
        )

        assert resultado["cv_aplicavel"] == resultado["cv_intermediaria"]
        assert resultado["cv_intermediaria"] >= resultado["cv_repetibilidade"]

    def test_menos_de_cinco_corridas_gera_aviso(self):
        resultado = precisao.avaliar_precisao(
            self.cinco_dias()[:3], precisao.DESENHO_MULTIPLAS_CORRIDAS
        )

        assert resultado["atende_minimo"] is False
        assert any("5 corridas" in aviso for aviso in resultado["avisos"])

    def test_corridas_com_poucas_replicas_geram_aviso(self):
        resultado = precisao.avaliar_precisao(
            [[10.0, 10.2]] * 5, precisao.DESENHO_MULTIPLAS_CORRIDAS
        )

        assert resultado["atende_minimo"] is False
        assert any("réplicas por corrida" in aviso for aviso in resultado["avisos"])


class TestDesenhoDesconhecido:
    def test_desenho_invalido_nao_calcula_nada(self):
        resultado = precisao.avaliar_precisao([[10.0, 10.2]], "desenho_inventado")

        assert resultado["cv_aplicavel"] is None
        assert resultado["avisos"]


class TestRegressaoLinear:
    def test_reta_exata_da_r_igual_a_um(self):
        resultado = comp.regressao_linear([1, 2, 3, 4, 5], [3, 5, 7, 9, 11])

        assert resultado["inclinacao"] == pytest.approx(2.0)
        assert resultado["intercepto"] == pytest.approx(1.0)
        assert resultado["r"] == pytest.approx(1.0)
        assert resultado["r2"] == pytest.approx(1.0)

    def test_r_alto_nao_significa_concordancia(self):
        # Correlação perfeita com o método novo lendo o dobro do antigo.
        # r = 1,000 e mesmo assim os métodos não são intercambiáveis.
        resultado = comp.regressao_linear([10, 20, 30, 40], [20, 40, 60, 80])

        assert resultado["r"] == pytest.approx(1.0)
        assert resultado["inclinacao"] == pytest.approx(2.0)

    def test_sinaliza_amplitude_insuficiente(self):
        # Amostras concentradas numa faixa estreita com ruído: r baixo indica
        # que a faixa estudada não sustenta a regressão.
        estreita = comp.regressao_linear(
            [10.0, 10.1, 10.2, 10.1, 10.0, 10.2],
            [10.3, 9.9, 10.5, 10.0, 10.4, 9.8],
        )
        ampla = comp.regressao_linear([1, 20, 40, 60, 80, 100], [2, 21, 41, 59, 81, 99])

        assert estreita["amplitude_adequada"] is False
        assert ampla["amplitude_adequada"] is True

    def test_erro_padrao_da_estimativa_e_zero_na_reta_exata(self):
        resultado = comp.regressao_linear([1, 2, 3, 4, 5], [3, 5, 7, 9, 11])

        assert resultado["erro_padrao_estimativa"] == pytest.approx(0.0, abs=1e-12)

    def test_sem_variacao_nao_ha_reta(self):
        resultado = comp.regressao_linear([5, 5, 5, 5], [4, 6, 5, 7])

        assert resultado["inclinacao"] is None
        assert "sem variação" in resultado["observacao"]
