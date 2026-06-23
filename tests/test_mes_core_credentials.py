from app.core.mes_core_credentials import _parse_secret_json


def test_parse_rds_managed_secret_json():
    creds = _parse_secret_json(
        {
            "username": "mescore",
            "password": "S3cret!",
            "host": "nyra-mes-core.example.rds.amazonaws.com",
            "port": 5432,
            "dbname": "postgres",
        },
        host="",
        port="5432",
        name="",
        user="",
    )
    assert creds.user == "mescore"
    assert creds.password == "S3cret!"
    assert creds.host.endswith(".amazonaws.com")
    assert creds.name == "postgres"


def test_parse_plain_password_secret():
    creds = _parse_secret_json(
        {"password": "plain-only"},
        host="db.example.com",
        port="5432",
        name="postgres",
        user="mescore",
    )
    assert creds.password == "plain-only"
    assert creds.host == "db.example.com"
    assert creds.user == "mescore"
