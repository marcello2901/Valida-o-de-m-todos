"""O intervalo de referência sai do analito e fica só na validação.

Ele é da metodologia, não do analito: dois imunoensaios de FT4 imprimem faixas
diferentes no laudo. Um valor único no analito servia de reserva para os dois
métodos do estudo — e classificar os resultados dos dois pela mesma faixa
esconde exatamente o desacordo que a concordância clínica existe para medir.

Apagar as colunas sem mais nada mudaria em silêncio o resultado de todo estudo
que dependia dessa reserva: a concordância clínica simplesmente deixaria de ser
calculada, e o relatório passaria a sair com uma ressalva onde antes havia
número. Por isso o valor é levado antes para o campo do estudo, que é onde ele
passa a morar — só nos estudos que ainda não declaram um intervalo próprio, e
só no lado da comparação, que é o lado que herdava.
"""

from django.db import migrations


def levar_o_intervalo_para_os_estudos(apps, schema_editor):
    Estudo = apps.get_model("estudos", "Estudo")

    herdeiros = Estudo.objects.filter(
        referencia_comparacao_inferior=None,
        referencia_comparacao_superior=None,
    ).exclude(
        mensurando__referencia_inferior=None,
        mensurando__referencia_superior=None,
    ).select_related("mensurando")

    for estudo in herdeiros.iterator():
        estudo.referencia_comparacao_inferior = estudo.mensurando.referencia_inferior
        estudo.referencia_comparacao_superior = estudo.mensurando.referencia_superior
        estudo.save(
            update_fields=[
                "referencia_comparacao_inferior",
                "referencia_comparacao_superior",
            ]
        )


def desfazer(apps, schema_editor):
    """A volta recria as colunas vazias.

    Não dá para saber qual estudo tinha intervalo próprio e qual herdou, e
    devolver o valor ao analito escolhendo um estudo qualquer inventaria um dado.
    Quem voltar preenche o analito de novo.
    """


class Migration(migrations.Migration):

    dependencies = [
        ("catalogo", "0006_reagente_recebe_o_intervalo_analitico"),
        ("estudos", "0008_amostra_qualitativa_aceita_codigo_repetido"),
    ]

    operations = [
        migrations.RunPython(levar_o_intervalo_para_os_estudos, desfazer),
        migrations.RemoveField(
            model_name="mensurando",
            name="referencia_inferior",
        ),
        migrations.RemoveField(
            model_name="mensurando",
            name="referencia_superior",
        ),
    ]
