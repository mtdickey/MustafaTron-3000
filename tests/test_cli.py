"""CLI exit codes: the ETL workflow alerts on EXIT_AUTH, so it must be distinct and reliable."""

import pytest

from mustafatron import cli
from mustafatron.config import MissingSecretError
from mustafatron.espn.client import EspnAuthError


@pytest.mark.parametrize(
    ("error", "code"),
    [(EspnAuthError("401 Unauthorized"), cli.EXIT_AUTH), (MissingSecretError("no"), cli.EXIT_MISSING_SECRET)],
)
def test_errors_map_to_exit_codes(monkeypatch, capsys, error, code):
    def fail(args):
        raise error

    monkeypatch.setattr(cli, "cmd_fetch", fail)
    assert cli.main(["fetch", "--seasons", "2026"]) == code
    assert "error:" in capsys.readouterr().err


def test_publish_also_reports_expired_cookies(monkeypatch, capsys):
    def fail(args):
        raise EspnAuthError("ESPN rejected the login cookies (HTTP 401): update ESPN_SWID / ESPN_S2")

    monkeypatch.setattr(cli, "cmd_publish", fail)
    assert cli.main(["publish"]) == cli.EXIT_AUTH
    assert "ESPN_SWID / ESPN_S2" in capsys.readouterr().err
