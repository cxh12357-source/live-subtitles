import requests
import pytest
from captioner.download import download_translation


def test_disconnected_download_preserves_explicit_error(monkeypatch):
    def disconnected(*args,**kwargs):
        raise requests.ConnectionError('test: network disconnected')
    monkeypatch.setattr(requests,'get',disconnected)
    with pytest.raises(requests.ConnectionError,match='network disconnected'):
        download_translation('en','zh')
