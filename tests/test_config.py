from app.config import Config, get_config


def test_api_key_hidden_from_repr():
    config = Config(api_key="sk-ant-secret")
    assert "sk-ant-secret" not in repr(config)
    assert config.has_api_key


def test_settings_page_shows_key_status_never_key(client, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-secret")
    get_config.cache_clear()
    try:
        response = client.get("/settings")
    finally:
        get_config.cache_clear()
    assert response.status_code == 200
    assert "found" in response.text
    assert "sk-ant-secret" not in response.text
