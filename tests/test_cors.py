"""CORS policy: wildcard never combined with credentials; explicit origins are honoured."""

from app.main import cors_options


def test_wildcard_disables_credentials():
    options = cors_options("*")

    assert options["allow_origins"] == ["*"]
    assert options["allow_credentials"] is False


def test_empty_value_falls_back_to_wildcard_without_credentials():
    options = cors_options("  ")

    assert options["allow_origins"] == ["*"]
    assert options["allow_credentials"] is False


def test_explicit_origins_are_trimmed_and_allow_credentials():
    options = cors_options("https://viewer.example.org, https://app.example.org ,")

    assert options["allow_origins"] == ["https://viewer.example.org", "https://app.example.org"]
    assert options["allow_credentials"] is True


def test_wildcard_inside_a_list_still_disables_credentials():
    options = cors_options("https://app.example.org,*")

    assert options["allow_origins"] == ["*"]
    assert options["allow_credentials"] is False


def test_only_methods_used_by_the_api_are_allowed():
    assert cors_options("*")["allow_methods"] == ["GET", "POST", "OPTIONS"]


def test_default_app_does_not_reflect_origin_with_credentials(client):
    response = client.get("/health", headers={"Origin": "https://evil.example"})

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "*"
    assert "access-control-allow-credentials" not in response.headers
