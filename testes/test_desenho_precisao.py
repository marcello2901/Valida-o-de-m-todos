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

        assert resultado["cv"] is not None
        assert resultado["cv_intermediaria"] is None
        assert resultado["tipo_cv_aplicavel"] == precisao.CV_DA_CORRIDA
        assert resultado["cv_aplicavel"] == resultado["cv"]

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

    def test_o_cv_avaliado_e_o_agrupado_das_corridas(self):
        resultado = precisao.avaliar_precisao(
            self.cinco_dias(), precisao.DESENHO_MULTIPLAS_CORRIDAS
        )

        assert resultado["cv"] is not None
        assert resultado["cv_aplicavel"] == resultado["cv"]
        assert resultado["tipo_cv_aplicavel"] == precisao.CV_AGRUPADO
        assert resultado["atende_minimo"] is True
        assert resultado["avisos"] == []

    def test_traz_a_estatistica_de_cada_corrida(self):
        resultado = precisao.avaliar_precisao(
            self.cinco_dias(), precisao.DESENHO_MULTIPLAS_CORRIDAS
        )

        assert [c["corrida"] for c in resultado["corridas"]] == [1, 2, 3, 4, 5]
        primeira = resultado["corridas"][0]
        assert primeira["n"] == 5
        assert primeira["media"] == pytest.approx(10.0)
        assert primeira["desvio_padrao"] == pytest.approx(0.158113883, rel=1e-6)
        assert primeira["cv"] == pytest.approx(1.58113883, rel=1e-6)

    def test_o_cv_agrupado_e_a_repetibilidade_e_fica_abaixo_da_intermediaria(self):
        # O agrupamento junta corridas para ganhar graus de liberdade, não para
        # incorporar a variação entre elas: o número continua sendo dispersão
        # dentro de corrida, e por isso é o menor dos dois.
        resultado = precisao.avaliar_precisao(
            self.cinco_dias(), precisao.DESENHO_MULTIPLAS_CORRIDAS
        )

        assert resultado["cv"] < resultado["cv_intermediaria"]

    def test_avisa_quando_so_a_variacao_entre_dias_estoura_o_limite(self):
        # O caso perigoso da simplificação: passa no relatório, falha na rotina.
        resultado = precisao.avaliar_precisao(
            self.cinco_dias(), precisao.DESENHO_MULTIPLAS_CORRIDAS
        )
        limite = (resultado["cv"] + resultado["cv_intermediaria"]) / 2

        alerta = precisao.alerta_precisao_intermediaria(resultado, limite)

        assert alerta is not None
        assert "variação entre os dias" in alerta

    def test_nao_alerta_quando_as_duas_precisoes_cabem_no_limite(self):
        resultado = precisao.avaliar_precisao(
            self.cinco_dias(), precisao.DESENHO_MULTIPLAS_CORRIDAS
        )

        assert precisao.alerta_precisao_intermediaria(resultado, 10.0) is None

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
