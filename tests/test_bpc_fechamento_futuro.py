"""BPC com 63 ou 64 anos nunca é desqualificado: fica com a equipe (fechamento futuro). Reteste de 26/11."""
from app.cerebro import turno


class _Idoso:
    config = {"catalogo": {"slug": "bpc-loas-idoso-v2"}}


class _Auxilio:
    config = {"catalogo": {"slug": "auxilio-acidente-midia"}}


def test_64_anos_sem_outro_motivo_e_fechamento_futuro():
    assert turno._fechamento_futuro_bpc(_Idoso(), {"beneficiario_idade": 64, "recebe_beneficio": "nenhum"})


def test_63_anos_tambem():
    assert turno._fechamento_futuro_bpc(_Idoso(), {"beneficiario_idade": "63"})


def test_62_anos_pode_desqualificar():
    assert not turno._fechamento_futuro_bpc(_Idoso(), {"beneficiario_idade": 62})


def test_64_anos_que_ja_recebe_aposentadoria_desqualifica():
    assert not turno._fechamento_futuro_bpc(_Idoso(), {"beneficiario_idade": 64, "recebe_beneficio": "aposentadoria"})


def test_64_anos_com_advogado_no_caso_desqualifica():
    assert not turno._fechamento_futuro_bpc(_Idoso(), {"beneficiario_idade": 64, "tem_advogado_no_caso": "sim"})


def test_fora_do_bpc_nao_vale():
    assert not turno._fechamento_futuro_bpc(_Auxilio(), {"beneficiario_idade": 64})
