import socket

import pytest


@pytest.fixture(autouse=True)
def _no_network(monkeypatch):
    """The suite runs on committed data/raw/ alone: no ESPN credentials, no network.

    Anything that tries to open a connection fails loudly instead of quietly reaching ESPN.
    """

    def blocked(*args, **kwargs):
        raise RuntimeError("tests must not use the network; read data/raw/ (finished seasons) instead")

    monkeypatch.setattr(socket.socket, "connect", blocked)
    monkeypatch.setattr(socket, "create_connection", blocked)


@pytest.fixture(scope="session")
def player_league():
    """Every committed season with player data, loaded once: lineups and trade values are cached on it."""
    from mustafatron.transform import load_league

    return load_league(range(2015, 2026), player_data=True)
