"""Testes da tela de resultado e do isolamento entre laboratórios.

O primeiro bloco guarda uma propriedade de segurança: um laboratório nunca pode
ver o estudo de outro. É o tipo de falha que não aparece no uso normal — só
quando alguém troca o número na barra de endereço — e por isso precisa de teste.
"""

from datetime import date
from decimal import Decimal

from django.test import TestCase
from django.urls import reverse

from catalogo.models import (
    Controle,
    EspecificacaoQualidade,
    LimiteImprecisao,
    Mensurando,
    SistemaAnalitico,
)
from contas.models import Assinatura, Laboratorio, RegistroAuditoria, Usuario
from estudos import servicos
from estudos.models import (
    VERSAO_MOTOR,
    AmostraComparacao,
    Estudo,
    NivelEstudo,
    Replica,
    Veredito,
)
from motor import precisao


def montar_laboratorio(nome: str, cnpj: str) -> Laboratorio:
    laboratorio = Laboratorio.objects.create(razao_social=nome, cnpj=cnpj)
    Assinatura.objects.create(laboratorio=laboratorio, modulo=Assinatura.COMPLETO)
    return laboratorio


def montar_estudo(laboratorio: Laboratorio, usuario: Usuario) -> Estudo:
    mensurando = Mensurando.objects.create(
        laboratorio=laboratorio,
        nome="FT4",
        unidade_medida="ng/dL",
        material_biologico="soro",
        referencia_inferior=Decimal("0.8"),
        referencia_superior=Decimal("1.8"),
    )
    teste = SistemaAnalitico.objects.create(
        laboratorio=laboratorio, papel=SistemaAnalitico.TESTE,
        equipamento="Atellica", numero_serie="IH00715", metodologia="Quimioluminescência",
    )
    comparacao = SistemaAnalitico.objects.create(
        laboratorio=laboratorio, papel=SistemaAnalitico.COMPARACAO,
        equipamento="Centaur", numero_serie="CE04412", metodologia="Quimioluminescência",
    )
    controle = Controle.objects.create(
        sistema=teste, nivel=1, nome="Controle 1", lote="L1",
        validade=date(2027, 1, 1), valor_alvo=Decimal("1.3"),
    )
    especificacao = EspecificacaoQualidade.objects.create(
        laboratorio=laboratorio, mensurando=mensurando, nome="FT4 — ControlLab",
        erro_total_maximo_pct=Decimal("12.00"), erro_total_referencia="ControlLab",
        bias_maximo_pct=Decimal("6.00"), bias_referencia="50% do ControlLab",
    )
    LimiteImprecisao.objects.create(
        especificacao=especificacao, nivel=1, maximo_pct=Decimal("4.00"), referencia="1/3 do ControlLab"
    )

    estudo = Estudo.objects.create(
        laboratorio=laboratorio,
        identificacao="Validação FT4",
        modulo=Assinatura.COMPLETO,
        desenho_precisao=precisao.DESENHO_MULTIPLAS_CORRIDAS,
        mensurando=mensurando,
        sistema_teste=teste,
        sistema_comparacao=comparacao,
        especificacao=especificacao,
        criado_por=usuario,
    )

    nivel = NivelEstudo.objects.create(
        estudo=estudo, numero=1, controle=controle, concentracao_declarada=Decimal("1.3")
    )
    for corrida in range(1, 6):
        for sequencia, valor in enumerate(["1.28", "1.30", "1.32", "1.29", "1.31"], start=1):
            Replica.objects.create(
                nivel=nivel, corrida=corrida, sequencia=sequencia,
                valor=Decimal(valor) + Decimal("0.005") * corrida,
            )
    for indice in range(1, 11):
        base = Decimal("0.5") * indice
        AmostraComparacao.objects.create(
            estudo=estudo, identificacao=f"AM-{indice:03d}",
            valor_comparacao=base, valor_teste=base * Decimal("1.02"),
        )
    return estudo


class TestIsolamentoEntreLaboratorios(TestCase):
    def setUp(self):
        self.laboratorio = montar_laboratorio("Lab A", "11.111.111/0001-11")
        self.dono = Usuario.objects.create_user(
            username="dono", password="senha-longa-de-teste", laboratorio=self.laboratorio
        )
        self.estudo = montar_estudo(self.laboratorio, self.dono)
        self.url = reverse("resultado_estudo", args=[self.estudo.pk])

    def test_dono_do_estudo_ve_o_resultado(self):
        self.client.force_login(self.dono)

        resposta = self.client.get(self.url)

        self.assertEqual(resposta.status_code, 200)
        self.assertContains(resposta, "Validação FT4")

    def test_outro_laboratorio_nao_ve_o_estudo(self):
        # Trocar o número na barra de endereço não pode revelar dado alheio.
        outro = montar_laboratorio("Lab B", "22.222.222/0001-22")
        intruso = Usuario.objects.create_user(
            username="intruso", password="senha-longa-de-teste", laboratorio=outro
        )
        self.client.force_login(intruso)

        self.assertEqual(self.client.get(self.url).status_code, 404)

    def test_usuario_sem_laboratorio_nao_ve_o_estudo(self):
        avulso = Usuario.objects.create_user(username="avulso", password="senha-longa-de-teste")
        self.client.force_login(avulso)

        self.assertEqual(self.client.get(self.url).status_code, 404)

    def test_equipe_interna_ve_qualquer_estudo(self):
        # Suporte da plataforma precisa enxergar para atender o cliente.
        suporte = Usuario.objects.create_user(
            username="suporte", password="senha-longa-de-teste", is_staff=True
        )
        self.client.force_login(suporte)

        self.assertEqual(self.client.get(self.url).status_code, 200)

    def test_visitante_nao_autenticado_e_mandado_para_o_login(self):
        self.assertEqual(self.client.get(self.url).status_code, 302)


class TestConteudoDoResultado(TestCase):
    def setUp(self):
        self.laboratorio = montar_laboratorio("Lab A", "11.111.111/0001-11")
        self.dono = Usuario.objects.create_user(
            username="dono", password="senha-longa-de-teste", laboratorio=self.laboratorio
        )
        self.estudo = montar_estudo(self.laboratorio, self.dono)
        self.client.force_login(self.dono)
        self.resposta = self.client.get(reverse("resultado_estudo", args=[self.estudo.pk]))

    def test_traz_as_faixas_do_estudo(self):
        # A rastreabilidade deixou de ser uma seção única e virou três faixas
        # condensáveis, cada uma resumida numa linha quando resolvida.
        for faixa in [
            "Analito e limites",
            "Sistemas analíticos",
            "Insumos e controles",
            "Precisão",
            "Comparabilidade",
            "Veredito por nível",
        ]:
            self.assertContains(self.resposta, faixa)

    def test_as_faixas_resolvidas_nascem_fechadas(self):
        # Só a etapa corrente abre sozinha: é isso que faz a tela caber num olhar.
        corpo = self.resposta.content.decode()
        assert corpo.count("<details class=\"cartao faixa\">") >= 3, "faixas de rastreabilidade deveriam nascer condensadas"
        assert "<details class=\"cartao faixa\" open>" in corpo, "a etapa corrente deveria nascer aberta"

    def test_traz_as_medidas_pedidas(self):
        for medida in [
            "Erro sistemático médio",
            "Regressão de Deming",
            "Passing-Bablok",
            "Concordância de Lin",
            "Concordância analítica",
            "Concordância clínica",
        ]:
            self.assertContains(self.resposta, medida)

    def test_desenha_os_graficos(self):
        # Os gráficos são SVG embutido; sem biblioteca externa, sem JavaScript.
        self.assertContains(self.resposta, "<svg")
        self.assertContains(self.resposta, "Levey-Jennings")

    def test_mostra_a_referencia_cientifica_de_cada_limite(self):
        self.assertContains(self.resposta, "ControlLab")

    def test_distingue_previa_de_veredito_congelado(self):
        # O estudo do fixture não foi concluído: o cabeçalho tem de dizer que o
        # resultado é prévia, não decisão assinada.
        self.assertContains(self.resposta, "Prévia")
        self.assertNotContains(self.resposta, "Congelado em")

    def test_avisa_quando_faltam_amostras_para_o_ep09(self):
        # O estudo tem 10 amostras; o EP09 pede 40.
        self.assertContains(self.resposta, "CLSI EP09")

    def test_nao_vaza_o_estudo_no_titulo_de_erro(self):
        outro = montar_laboratorio("Lab B", "22.222.222/0001-22")
        intruso = Usuario.objects.create_user(
            username="intruso", password="senha-longa-de-teste", laboratorio=outro
        )
        self.client.force_login(intruso)

        resposta = self.client.get(reverse("resultado_estudo", args=[self.estudo.pk]))

        self.assertNotContains(resposta, "Validação FT4", status_code=404)


class TestQuadro(TestCase):
    """O quadro precisa colocar cada estudo na coluna certa e dizer o que falta."""

    def setUp(self):
        self.laboratorio = montar_laboratorio("Lab A", "11.111.111/0001-11")
        self.dono = Usuario.objects.create_user(
            username="dono", password="senha-longa-de-teste", laboratorio=self.laboratorio
        )
        self.estudo = montar_estudo(self.laboratorio, self.dono)
        self.url = reverse("quadro")

    def test_o_estudo_aparece_no_quadro(self):
        self.client.force_login(self.dono)

        resposta = self.client.get(self.url)

        self.assertEqual(resposta.status_code, 200)
        self.assertContains(resposta, "FT4")

    def test_estudo_com_dados_parciais_fica_em_coletando(self):
        # 25 réplicas de 25 e 10 amostras de 40: começou, não terminou.
        self.assertEqual(self.estudo.coluna_quadro(), Estudo.COLUNA_COLETANDO)

    def test_estudo_sem_dado_nenhum_fica_em_rascunho(self):
        self.estudo.amostras_comparacao.all().delete()
        Replica.objects.filter(nivel__estudo=self.estudo).delete()

        self.assertEqual(self.estudo.coluna_quadro(), Estudo.COLUNA_RASCUNHO)

    def test_estudo_liberado_fica_na_ultima_coluna(self):
        self.estudo.situacao = Estudo.LIBERADO

        self.assertEqual(self.estudo.coluna_quadro(), Estudo.COLUNA_LIBERADO)

    def test_a_proxima_acao_diz_quantas_amostras_faltam(self):
        # A precisão está completa; o que trava é a comparabilidade.
        self.assertEqual(self.estudo.proxima_acao(), "Faltam 30 amostras")

    def test_a_proxima_acao_aponta_a_replica_seguinte(self):
        Replica.objects.filter(nivel__estudo=self.estudo, corrida__gte=4).delete()

        self.assertEqual(self.estudo.proxima_acao(), "Nível 1, réplica 16")

    def test_estudo_de_outro_laboratorio_nao_aparece(self):
        outro = montar_laboratorio("Lab B", "22.222.222/0001-22")
        intruso = Usuario.objects.create_user(
            username="intruso", password="senha-longa-de-teste", laboratorio=outro
        )
        self.client.force_login(intruso)

        self.assertNotContains(self.client.get(self.url), "FT4")

    def test_visitante_vai_para_o_login(self):
        self.assertEqual(self.client.get(self.url).status_code, 302)


class TestCalcularELiberar(TestCase):
    """As duas ações que movem o estudo pelo quadro.

    São o ponto em que um cálculo vira registro de qualidade, então o que se
    testa aqui é sobretudo o que elas *recusam* fazer.
    """

    def setUp(self):
        self.laboratorio = montar_laboratorio("Lab A", "11.111.111/0001-11")
        self.responsavel = Usuario.objects.create_user(
            username="responsavel", password="senha-longa-de-teste",
            laboratorio=self.laboratorio, funcao=Usuario.RESPONSAVEL,
        )
        self.analista = Usuario.objects.create_user(
            username="analista", password="senha-longa-de-teste",
            laboratorio=self.laboratorio, funcao=Usuario.ANALISTA,
        )
        self.estudo = montar_estudo(self.laboratorio, self.responsavel)
        self.calcular_url = reverse("concluir_estudo", args=[self.estudo.pk])
        self.liberar_url = reverse("liberar_estudo", args=[self.estudo.pk])

    def test_calcular_congela_o_retrato_e_move_o_estudo(self):
        self.client.force_login(self.analista)

        self.client.post(self.calcular_url)

        self.estudo.refresh_from_db()
        self.assertEqual(self.estudo.situacao, Estudo.CONCLUIDO)
        self.assertEqual(self.estudo.coluna_quadro(), Estudo.COLUNA_CALCULADO)
        veredito = self.estudo.veredito
        self.assertEqual(veredito.versao_motor, VERSAO_MOTOR)
        self.assertIn("precisao", veredito.detalhamento)

    def test_o_retrato_guarda_os_limites_vigentes_no_momento(self):
        # É o que permite defender o número numa auditoria: a ficha pode mudar
        # depois, mas o relatório mostra contra o que se decidiu na época.
        self.client.force_login(self.analista)

        self.client.post(self.calcular_url)

        limites = self.estudo.veredito.detalhamento["especificacao"]
        self.assertEqual(limites["erro_total"]["valor_pct"], 12.0)
        self.assertEqual(limites["erro_total"]["referencia"], "ControlLab")

    def test_calcular_registra_na_trilha_de_auditoria(self):
        self.client.force_login(self.analista)

        self.client.post(self.calcular_url)

        registro = RegistroAuditoria.objects.get(acao="calculou o estudo")
        self.assertEqual(registro.usuario, self.analista)
        self.assertEqual(registro.laboratorio, self.laboratorio)

    def test_estudo_sem_dado_nenhum_nao_calcula(self):
        self.estudo.amostras_comparacao.all().delete()
        Replica.objects.filter(nivel__estudo=self.estudo).delete()
        self.client.force_login(self.analista)

        self.client.post(self.calcular_url)

        self.estudo.refresh_from_db()
        self.assertEqual(self.estudo.situacao, Estudo.RASCUNHO)
        self.assertFalse(hasattr(self.estudo, "veredito"))

    def test_recalcular_substitui_o_retrato_anterior(self):
        self.client.force_login(self.analista)
        self.client.post(self.calcular_url)

        self.client.post(self.calcular_url)

        self.assertEqual(Veredito.objects.filter(estudo=self.estudo).count(), 1)
        self.assertTrue(RegistroAuditoria.objects.filter(acao="recalculou o estudo").exists())

    def test_get_nao_calcula(self):
        # Mudança de estado por GET seria disparada por um simples recarregar.
        self.client.force_login(self.analista)

        resposta = self.client.get(self.calcular_url)

        self.assertEqual(resposta.status_code, 405)
        self.assertFalse(Veredito.objects.exists())

    def test_laboratorio_alheio_nao_calcula(self):
        outro = montar_laboratorio("Lab B", "22.222.222/0001-22")
        intruso = Usuario.objects.create_user(
            username="intruso", password="senha-longa-de-teste", laboratorio=outro
        )
        self.client.force_login(intruso)

        self.assertEqual(self.client.post(self.calcular_url).status_code, 404)
        self.assertFalse(Veredito.objects.exists())

    def test_analista_nao_libera(self):
        # Assinar relatório de validação é ato do responsável técnico.
        self.client.force_login(self.analista)
        self.client.post(self.calcular_url)

        self.client.post(self.liberar_url)

        self.estudo.refresh_from_db()
        self.assertEqual(self.estudo.situacao, Estudo.CONCLUIDO)

    def test_responsavel_libera_e_assina(self):
        self.client.force_login(self.responsavel)
        self.client.post(self.calcular_url)

        self.client.post(self.liberar_url)

        self.estudo.refresh_from_db()
        self.assertEqual(self.estudo.situacao, Estudo.LIBERADO)
        self.assertEqual(self.estudo.veredito.liberado_por, self.responsavel)
        self.assertIsNotNone(self.estudo.veredito.liberado_em)

    def test_nao_libera_sem_calcular_antes(self):
        self.client.force_login(self.responsavel)

        self.client.post(self.liberar_url)

        self.estudo.refresh_from_db()
        self.assertEqual(self.estudo.situacao, Estudo.RASCUNHO)

    def test_estudo_liberado_nao_recalcula(self):
        # Recalcular um relatório assinado descolaria o número do que se assinou.
        self.client.force_login(self.responsavel)
        self.client.post(self.calcular_url)
        self.client.post(self.liberar_url)
        congelado_em = self.estudo.veredito.calculado_em

        self.client.post(self.calcular_url)

        self.estudo.refresh_from_db()
        self.assertEqual(self.estudo.situacao, Estudo.LIBERADO)
        self.assertEqual(self.estudo.veredito.calculado_em, congelado_em)

    def test_a_tela_avisa_quando_o_recalculo_diverge_do_assinado(self):
        # A ficha do analito apertou depois da assinatura: a tela recalcula ao
        # vivo, o relatório mantém o número assinado, e o usuário precisa ver
        # que os dois deixaram de bater.
        self.client.force_login(self.responsavel)
        self.client.post(self.calcular_url)
        self.assertEqual(self.estudo.veredito.resultado, Veredito.APROVADO)

        ficha = self.estudo.especificacao
        ficha.erro_total_maximo_pct = Decimal("1.00")
        ficha.save()
        ficha.limites_imprecisao.update(maximo_pct=Decimal("0.25"))

        resposta = self.client.get(reverse("resultado_estudo", args=[self.estudo.pk]))

        self.assertContains(resposta, "não bate com o veredito congelado")


class TestGradeDeReplicas(TestCase):
    """A grade de lançamento: 30 linhas por nível, salvas de uma vez."""

    def setUp(self):
        self.laboratorio = montar_laboratorio("Lab A", "11.111.111/0001-11")
        self.usuario = Usuario.objects.create_user(
            username="analista", password="senha-longa-de-teste",
            laboratorio=self.laboratorio, funcao=Usuario.ANALISTA,
        )
        self.estudo = montar_estudo(self.laboratorio, self.usuario)
        self.nivel = self.estudo.niveis.get(numero=1)
        self.url = reverse("replicas_estudo", args=[self.estudo.pk])
        self.client.force_login(self.usuario)

    def test_a_grade_tem_trinta_linhas_por_nivel(self):
        colunas = servicos.montar_grade(self.estudo)

        self.assertEqual(len(colunas), 1)
        self.assertEqual(len(colunas[0]["linhas"]), 30)

    def test_as_linhas_se_agrupam_de_cinco_em_cinco_por_corrida(self):
        # O desenho de referência do EP15: cada bloco de 5 é uma corrida.
        linhas = servicos.montar_grade(self.estudo)[0]["linhas"]

        self.assertEqual((linhas[0]["corrida"], linhas[0]["sequencia"]), (1, 1))
        self.assertEqual((linhas[4]["corrida"], linhas[4]["sequencia"]), (1, 5))
        self.assertEqual((linhas[5]["corrida"], linhas[5]["sequencia"]), (2, 1))
        self.assertEqual((linhas[29]["corrida"], linhas[29]["sequencia"]), (6, 5))

    def test_em_corrida_unica_todas_as_linhas_sao_a_mesma_corrida(self):
        self.estudo.desenho_precisao = precisao.DESENHO_CORRIDA_UNICA
        self.estudo.save(update_fields=["desenho_precisao"])

        linhas = servicos.montar_grade(self.estudo)[0]["linhas"]

        self.assertEqual({linha["corrida"] for linha in linhas}, {1})
        self.assertEqual(linhas[29]["sequencia"], 30)

    def test_a_grade_traz_as_replicas_ja_lancadas(self):
        linhas = servicos.montar_grade(self.estudo)[0]["linhas"]

        self.assertEqual(linhas[0]["valor"], Decimal("1.2850"))
        self.assertIsNone(linhas[25]["valor"])

    def test_salvar_grava_o_que_foi_digitado(self):
        resposta = self.client.post(self.url, {f"nivel_{self.nivel.pk}_26": "1,33"})

        self.assertEqual(resposta.status_code, 302)
        gravada = Replica.objects.get(nivel=self.nivel, corrida=6, sequencia=1)
        self.assertEqual(gravada.valor, Decimal("1.3300"))

    def test_campo_em_branco_apaga_a_replica(self):
        antes = Replica.objects.filter(nivel=self.nivel).count()

        self.client.post(self.url, {f"nivel_{self.nivel.pk}_1": ""})

        self.assertEqual(Replica.objects.filter(nivel=self.nivel).count(), antes - 1)

    def test_valor_ilegivel_nao_grava_nada(self):
        # Tudo ou nada: gravar metade de uma corrida e recusar o resto deixaria o
        # laboratório com um estudo pela metade sem perceber.
        antes = Replica.objects.filter(nivel=self.nivel).count()

        resposta = self.client.post(
            self.url,
            {f"nivel_{self.nivel.pk}_26": "1,40", f"nivel_{self.nivel.pk}_27": "abc"},
            follow=True,
        )

        self.assertEqual(Replica.objects.filter(nivel=self.nivel).count(), antes)
        self.assertContains(resposta, "não é um número")

    def test_replica_excluida_com_justificativa_nao_e_alterada(self):
        alvo = Replica.objects.get(nivel=self.nivel, corrida=1, sequencia=1)
        alvo.excluida = True
        alvo.justificativa_exclusao = "bolha na cubeta"
        alvo.save()

        self.client.post(self.url, {})

        alvo.refresh_from_db()
        self.assertTrue(alvo.excluida)
        self.assertEqual(alvo.justificativa_exclusao, "bolha na cubeta")

    def test_a_media_interlaboratorial_e_gravada_junto(self):
        self.client.post(
            self.url,
            {f"alvo_{self.nivel.pk}": "1,32", f"provedor_{self.nivel.pk}": NivelEstudo.ELAB},
        )

        self.nivel.refresh_from_db()
        self.assertEqual(self.nivel.media_interlaboratorial, Decimal("1.3200"))
        self.assertEqual(self.nivel.provedor_interlaboratorial, NivelEstudo.ELAB)

    def test_acrescentar_nivel_cria_a_coluna(self):
        outro = Controle.objects.create(
            sistema=self.estudo.sistema_teste, mensurando=self.estudo.mensurando,
            nivel=2, nome="Controle 2", lote="L2",
            validade=date(2027, 1, 1), valor_alvo=Decimal("3.0"),
        )

        self.client.post(self.url, {"acao": "adicionar_nivel", "controle": outro.pk})

        self.assertEqual(self.estudo.niveis.count(), 2)
        self.assertEqual(self.estudo.niveis.get(numero=2).controle, outro)

    def test_nao_oferece_controle_de_outro_analito(self):
        # Mesmo equipamento, analito diferente: não pode virar coluna deste estudo.
        outro_analito = Mensurando.objects.create(
            laboratorio=self.laboratorio, nome="HbA1c",
            unidade_medida="%", material_biologico="sangue total",
        )
        alheio = Controle.objects.create(
            sistema=self.estudo.sistema_teste, mensurando=outro_analito,
            nivel=1, nome="Controle HbA1c", lote="LX",
            validade=date(2027, 1, 1), valor_alvo=Decimal("5.6"),
        )

        resposta = self.client.get(self.url)
        self.assertNotContains(resposta, "Controle HbA1c")

        self.client.post(self.url, {"acao": "adicionar_nivel", "controle": alheio.pk})
        self.assertEqual(self.estudo.niveis.count(), 1)

    def test_estudo_liberado_nao_aceita_lancamento(self):
        self.estudo.situacao = Estudo.LIBERADO
        self.estudo.save(update_fields=["situacao"])

        resposta = self.client.get(self.url)

        self.assertEqual(resposta.status_code, 302)

    def test_laboratorio_alheio_nao_abre_a_grade(self):
        outro = montar_laboratorio("Lab B", "22.222.222/0001-22")
        intruso = Usuario.objects.create_user(
            username="intruso", password="senha-longa-de-teste", laboratorio=outro
        )
        self.client.force_login(intruso)

        self.assertEqual(self.client.get(self.url).status_code, 404)


class TestIntervalosDeReferenciaPorMetodo(TestCase):
    """Cada metodologia classifica contra o intervalo que ela imprime no laudo."""

    def setUp(self):
        self.laboratorio = montar_laboratorio("Lab A", "11.111.111/0001-11")
        self.usuario = Usuario.objects.create_user(
            username="analista", password="senha-longa-de-teste", laboratorio=self.laboratorio
        )
        self.estudo = montar_estudo(self.laboratorio, self.usuario)

    def test_sem_intervalo_proprio_o_estudo_herda_o_do_mensurando(self):
        self.assertEqual(
            self.estudo.intervalo_de_comparacao(), (Decimal("0.8"), Decimal("1.8"))
        )
        self.assertEqual(self.estudo.intervalo_de_teste(), (None, None))

    def test_o_intervalo_do_estudo_prevalece_sobre_o_do_mensurando(self):
        self.estudo.referencia_comparacao_inferior = Decimal("0.9")
        self.estudo.referencia_comparacao_superior = Decimal("1.7")
        self.estudo.save()

        self.assertEqual(
            self.estudo.intervalo_de_comparacao(), (Decimal("0.9"), Decimal("1.7"))
        )

    def test_intervalos_diferentes_chegam_ao_calculo(self):
        self.estudo.referencia_teste_inferior = Decimal("0.85")
        self.estudo.referencia_teste_superior = Decimal("1.86")
        self.estudo.save()

        clinica = servicos.calcular(self.estudo)["comparabilidade"]["clinica"]

        self.assertTrue(clinica["intervalos_diferentes"])
        self.assertEqual(clinica["intervalo_teste"], (0.85, 1.86))

    def test_a_tela_mostra_os_dois_intervalos_usados(self):
        self.estudo.referencia_teste_inferior = Decimal("0.85")
        self.estudo.referencia_teste_superior = Decimal("1.86")
        self.estudo.save()
        self.client.force_login(self.usuario)

        resposta = self.client.get(reverse("resultado_estudo", args=[self.estudo.pk]))

        self.assertContains(resposta, "0,85")
        self.assertContains(resposta, "1,86")

    def test_a_tela_traz_pearson_e_a_regressao_simples(self):
        self.client.force_login(self.usuario)

        resposta = self.client.get(reverse("resultado_estudo", args=[self.estudo.pk]))

        self.assertContains(resposta, "Correlação de Pearson")
        self.assertContains(resposta, "Regressão linear simples")
        self.assertContains(resposta, "regressão linear simples")
        self.assertContains(resposta, "identidade (y = x)")


class TestGradeDeAmostras(TestCase):
    """Grade de amostras pareadas: 40 linhas abertas, ampliáveis."""

    def setUp(self):
        self.laboratorio = montar_laboratorio("Lab A", "11.111.111/0001-11")
        self.usuario = Usuario.objects.create_user(
            username="analista", password="senha-longa-de-teste",
            laboratorio=self.laboratorio, funcao=Usuario.ANALISTA,
        )
        self.estudo = montar_estudo(self.laboratorio, self.usuario)
        self.url = reverse("amostras_estudo", args=[self.estudo.pk])
        self.client.force_login(self.usuario)

    def test_abre_com_o_minimo_do_ep09(self):
        grade = servicos.montar_grade_amostras(self.estudo)

        self.assertEqual(grade["total"], 40)
        self.assertEqual(sum(len(pista) for pista in grade["pistas"]), 40)

    def test_as_linhas_se_repartem_em_pistas_de_vinte(self):
        grade = servicos.montar_grade_amostras(self.estudo)

        self.assertEqual([len(pista) for pista in grade["pistas"]], [20, 20])

    def test_as_amostras_ja_lancadas_ocupam_as_primeiras_linhas(self):
        # O fixture cadastra 10 amostras.
        linhas = servicos.montar_grade_amostras(self.estudo)["pistas"][0]

        self.assertEqual(linhas[0]["identificacao"], "AM-001")
        self.assertIsNotNone(linhas[0]["comparacao"])
        self.assertEqual(linhas[10]["identificacao"], "")

    def test_pedir_mais_linhas_amplia_a_grade(self):
        grade = servicos.montar_grade_amostras(self.estudo, linhas_pedidas=50)

        self.assertEqual(grade["total"], 50)
        self.assertEqual([len(pista) for pista in grade["pistas"]], [20, 20, 10])

    def test_a_grade_nunca_encolhe_abaixo_do_que_ja_foi_digitado(self):
        # Um número pequeno na barra de endereço não pode esconder amostra.
        for indice in range(11, 46):
            AmostraComparacao.objects.create(
                estudo=self.estudo, identificacao=f"AM-{indice:03d}",
                valor_comparacao=Decimal("1.0"), valor_teste=Decimal("1.0"),
            )

        grade = servicos.montar_grade_amostras(self.estudo, linhas_pedidas=5)

        self.assertEqual(grade["total"], 45)

    def test_o_botao_de_mais_linhas_leva_a_grade_maior(self):
        resposta = self.client.post(self.url, {"acao": "adicionar_linhas", "total": "40"})

        self.assertEqual(resposta.status_code, 302)
        self.assertIn("linhas=50", resposta["Location"])

    def test_salvar_grava_a_amostra_nova(self):
        self.client.post(
            self.url,
            {
                "total": "40",
                "amostra_11_id": "AM-011",
                "amostra_11_comparacao": "3,20",
                "amostra_11_teste": "3,26",
            },
        )

        gravada = AmostraComparacao.objects.get(estudo=self.estudo, identificacao="AM-011")
        self.assertEqual(gravada.valor_comparacao, Decimal("3.2000"))
        self.assertEqual(gravada.valor_teste, Decimal("3.2600"))

    def test_identificacao_em_branco_recebe_a_sugerida(self):
        # Ninguém deveria digitar quarenta identificadores sequenciais à mão.
        self.client.post(
            self.url,
            {"total": "40", "amostra_12_id": "", "amostra_12_comparacao": "1", "amostra_12_teste": "1"},
        )

        self.assertTrue(
            AmostraComparacao.objects.filter(estudo=self.estudo, identificacao="AM-012").exists()
        )

    def test_meia_amostra_nao_grava_nada(self):
        # Um par incompleto não entra em regressão nenhuma.
        antes = self.estudo.amostras_comparacao.count()

        resposta = self.client.post(
            self.url,
            {"total": "40", "amostra_11_comparacao": "3,20", "amostra_11_teste": ""},
            follow=True,
        )

        self.assertEqual(self.estudo.amostras_comparacao.count(), antes)
        self.assertContains(resposta, "nos dois sistemas")

    def test_identificacao_repetida_e_recusada_com_as_linhas(self):
        resposta = self.client.post(
            self.url,
            {
                "total": "40",
                "amostra_11_id": "DUPLA", "amostra_11_comparacao": "1", "amostra_11_teste": "1",
                "amostra_12_id": "DUPLA", "amostra_12_comparacao": "2", "amostra_12_teste": "2",
            },
            follow=True,
        )

        self.assertContains(resposta, "repete a da linha 11")
        self.assertFalse(
            AmostraComparacao.objects.filter(estudo=self.estudo, identificacao="DUPLA").exists()
        )

    def test_valor_ilegivel_nao_grava_nada(self):
        antes = self.estudo.amostras_comparacao.count()

        self.client.post(
            self.url,
            {
                "total": "40",
                "amostra_11_comparacao": "1", "amostra_11_teste": "1",
                "amostra_12_comparacao": "abc", "amostra_12_teste": "2",
            },
        )

        self.assertEqual(self.estudo.amostras_comparacao.count(), antes)

    def test_campos_em_branco_apagam_a_amostra(self):
        antes = self.estudo.amostras_comparacao.count()

        self.client.post(
            self.url,
            {"total": "40", "amostra_1_id": "AM-001", "amostra_1_comparacao": "", "amostra_1_teste": ""},
        )

        self.assertEqual(self.estudo.amostras_comparacao.count(), antes - 1)

    def test_envio_parcial_nao_apaga_o_que_nao_veio(self):
        # A mesma armadilha da grade de réplicas: ausente não é vazio.
        antes = self.estudo.amostras_comparacao.count()

        self.client.post(self.url, {"total": "40"})

        self.assertEqual(self.estudo.amostras_comparacao.count(), antes)

    def test_amostra_excluida_com_justificativa_nao_e_alterada(self):
        alvo = self.estudo.amostras_comparacao.first()
        alvo.excluida = True
        alvo.justificativa_exclusao = "hemólise"
        alvo.save()

        self.client.post(
            self.url,
            {"total": "40", "amostra_1_id": "OUTRA", "amostra_1_comparacao": "9", "amostra_1_teste": "9"},
        )

        alvo.refresh_from_db()
        self.assertTrue(alvo.excluida)
        self.assertEqual(alvo.justificativa_exclusao, "hemólise")

    def test_estudo_liberado_nao_aceita_lancamento(self):
        self.estudo.situacao = Estudo.LIBERADO
        self.estudo.save(update_fields=["situacao"])

        self.assertEqual(self.client.get(self.url).status_code, 302)

    def test_laboratorio_alheio_nao_abre_a_grade(self):
        outro = montar_laboratorio("Lab B", "22.222.222/0001-22")
        intruso = Usuario.objects.create_user(
            username="intruso", password="senha-longa-de-teste", laboratorio=outro
        )
        self.client.force_login(intruso)

        self.assertEqual(self.client.get(self.url).status_code, 404)

    def test_um_numero_absurdo_de_linhas_nao_derruba_a_tela(self):
        resposta = self.client.get(self.url, {"linhas": "999999"})

        self.assertEqual(resposta.status_code, 200)

    def test_o_card_do_quadro_leva_a_grade_que_falta(self):
        # Precisão completa, comparabilidade não: o card promete amostras.
        self.assertEqual(self.estudo.proxima_acao(), "Faltam 30 amostras")
        self.assertEqual(self.estudo.tela_da_proxima_acao(), "amostras_estudo")

    def test_com_precisao_incompleta_o_card_leva_as_replicas(self):
        Replica.objects.filter(nivel__estudo=self.estudo, corrida__gte=4).delete()

        self.assertEqual(self.estudo.tela_da_proxima_acao(), "replicas_estudo")

    def test_o_cabecalho_nao_diz_quarenta_e_um_de_quarenta(self):
        # Passar do mínimo não é erro, e "41 de 40" lia como se fosse.
        AmostraComparacao.objects.create(
            estudo=self.estudo, identificacao="AM-041",
            valor_comparacao=Decimal("1.0"), valor_teste=Decimal("1.0"),
        )

        resposta = self.client.get(self.url)

        self.assertContains(resposta, "11 amostras lançadas")
        self.assertNotContains(resposta, "de 40 lançadas")

    def test_o_cabecalho_diz_quanto_falta_para_o_minimo(self):
        resposta = self.client.get(self.url)

        self.assertContains(resposta, "Faltam 30 para o mínimo do EP09")


class TestLeituraDeNumeroBrasileiro(TestCase):
    """Como o programa lê um número copiado de planilha em português.

    O Excel em pt-BR copia 1234,56 como “1.234,56”. Trocar só a vírgula por
    ponto produzia “1.234.56”, recusado como não-numérico — ou seja, glicose,
    CK e ferritina, que passam de mil na rotina, não entravam.
    """

    def test_virgula_decimal(self):
        self.assertEqual(servicos.converter_numero("0,930"), Decimal("0.930"))

    def test_ponto_de_milhar_com_virgula_decimal(self):
        self.assertEqual(servicos.converter_numero("1.234,56"), Decimal("1234.56"))
        self.assertEqual(servicos.converter_numero("1.234.567,89"), Decimal("1234567.89"))

    def test_formato_americano_tambem_e_lido(self):
        self.assertEqual(servicos.converter_numero("1,234.56"), Decimal("1234.56"))

    def test_zero_a_esquerda_nao_e_milhar(self):
        # "0.930" só pode ser 0,930: nenhum separador de milhar segue um zero.
        self.assertEqual(servicos.converter_numero("0.930"), Decimal("0.930"))

    def test_quatro_digitos_antes_do_ponto_nao_sao_milhar(self):
        # O milhar sairia como "1.234.567"; então "1234.567" é decimal.
        self.assertEqual(servicos.converter_numero("1234.567"), Decimal("1234.567"))

    def test_o_caso_ambiguo_e_recusado_em_vez_de_adivinhado(self):
        # "1.500" tanto pode ser 1,5 quanto 1500. Adivinhar errado aqui não dá
        # um número estranho: dá um número mil vezes maior num laudo assinado.
        with self.assertRaises(servicos.NumeroAmbiguo):
            servicos.converter_numero("1.500")

    def test_a_recusa_explica_as_duas_leituras(self):
        try:
            servicos.converter_numero("12.345")
        except servicos.NumeroAmbiguo as ambiguo:
            self.assertIn("12,345", str(ambiguo))
            self.assertIn("12345", str(ambiguo))
        else:
            self.fail("deveria ter recusado")

    def test_a_grade_recusa_o_ambiguo_com_a_linha(self):
        laboratorio = montar_laboratorio("Lab A", "11.111.111/0001-11")
        usuario = Usuario.objects.create_user(
            username="analista", password="senha-longa-de-teste", laboratorio=laboratorio
        )
        estudo = montar_estudo(laboratorio, usuario)
        self.client.force_login(usuario)

        resposta = self.client.post(
            reverse("amostras_estudo", args=[estudo.pk]),
            {"total": "40", "amostra_11_comparacao": "1.500", "amostra_11_teste": "1,6"},
            follow=True,
        )

        self.assertContains(resposta, "Linha 11")
        self.assertContains(resposta, "pode ser")

    def test_valores_acima_de_mil_entram_pela_grade(self):
        # Glicose de 1.234 mg/dL vinda da planilha: antes era recusada.
        laboratorio = montar_laboratorio("Lab A", "11.111.111/0001-11")
        usuario = Usuario.objects.create_user(
            username="analista", password="senha-longa-de-teste", laboratorio=laboratorio
        )
        estudo = montar_estudo(laboratorio, usuario)
        self.client.force_login(usuario)

        self.client.post(
            reverse("amostras_estudo", args=[estudo.pk]),
            {"total": "40", "amostra_11_comparacao": "1.234,50", "amostra_11_teste": "1.240,00"},
        )

        gravada = AmostraComparacao.objects.get(estudo=estudo, identificacao="AM-011")
        self.assertEqual(gravada.valor_comparacao, Decimal("1234.5000"))
