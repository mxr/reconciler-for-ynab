from __future__ import annotations

import json
import re
import sqlite3
from configparser import ConfigParser
from pathlib import Path
from unittest.mock import patch

import pytest

from reconciler_for_ynab._main import _ENV_TOKEN
from reconciler_for_ynab._main import _PACKAGE
from reconciler_for_ynab._main import _row_factory
from reconciler_for_ynab._main import do_reconcile
from reconciler_for_ynab._main import fetch_budget_accts
from reconciler_for_ynab._main import fetch_transactions
from reconciler_for_ynab._main import main
from reconciler_for_ynab._main import YnabClient
from testing.fixtures import BUDGET_ID
from testing.fixtures import db
from testing.fixtures import mock_aioresponses
from testing.fixtures import TOKEN


def test_main_version(capsys):
    cp = ConfigParser()
    cp.read(Path(__file__).parent.parent / "setup.cfg")
    expected_version = cp["metadata"]["version"]

    with pytest.raises(SystemExit) as excinfo:
        main(("--version",))
    assert excinfo.value.code == 0

    out, _ = capsys.readouterr()
    assert out == f"{_PACKAGE} {expected_version}\n"


# TODO add credit card
@patch("reconciler_for_ynab._main.sync")
@pytest.mark.usefixtures(db.__name__)
@pytest.mark.parametrize(
    ("target", "expected"),
    (
        pytest.param(500, 0, id="reconciles cleared and uncleared"),
        pytest.param(430, 0, id="reconciles only cleared"),
        pytest.param(600, 1, id="no match"),
    ),
)
def test_main(sync, db, monkeypatch, target, expected):
    monkeypatch.setenv(_ENV_TOKEN, TOKEN)

    ret = main(
        (
            "--account-name-regex",
            "Checking",
            "--target",
            str(target),
            "--sqlite-export-for-ynab-db",
            db,
        )
    )
    sync.assert_called()
    assert ret == expected


@patch("reconciler_for_ynab._main.sync")
def test_main_nothing_to_do(sync, db, monkeypatch):
    monkeypatch.setenv(_ENV_TOKEN, TOKEN)

    with sqlite3.connect(db) as con:
        con.execute(
            "UPDATE transactions SET cleared = 'uncleared' where cleared = 'cleared'"
        )

    ret = main(
        (
            "--account-name-regex",
            "Checking",
            "--target",
            "430",
            "--sqlite-export-for-ynab-db",
            db,
        )
    )
    sync.assert_called()
    assert ret == 0


@patch("reconciler_for_ynab._main.sync")
@patch.object(YnabClient, "reconcile")
@pytest.mark.usefixtures(db.__name__)
def test_main_reconciles(sync, reconcile, db, monkeypatch):
    monkeypatch.setenv(_ENV_TOKEN, TOKEN)

    ret = main(
        (
            "--account-name-regex",
            "Checking",
            "--target",
            "500",
            "--sqlite-export-for-ynab-db",
            db,
            "--reconcile",
        )
    )
    sync.assert_called()
    assert ret == 0
    reconcile.assert_called()


def test_main_no_token(monkeypatch):
    monkeypatch.setenv(_ENV_TOKEN, "")

    with pytest.raises(ValueError) as excinfo:
        main(("--account-name-regex", "checking.+123", "--target", "410.50"))

    assert "Must set YNAB access token" in str(excinfo.value)


def test_main_mode_single_requires_single_targeting_params():
    with pytest.raises(ValueError) as excinfo:
        main(())

    assert "--mode single" in str(excinfo.value)


def test_main_mode_single_rejects_batch_targeting_params():
    with pytest.raises(ValueError) as excinfo:
        main(("--account-target-pairs", "Checking=500"))

    assert "--account-target-pairs" in str(excinfo.value)


def test_main_mode_batch_requires_account_target_pairs():
    with pytest.raises(ValueError) as excinfo:
        main(("--mode", "batch"))

    assert "--account-target-pairs" in str(excinfo.value)


def test_main_mode_batch_rejects_single_targeting_params():
    with pytest.raises(ValueError) as excinfo:
        main(("--mode", "batch", "--account-name-regex", "Checking", "--target", "500"))

    assert "--mode batch" in str(excinfo.value)


@patch("reconciler_for_ynab._main.sync")
@pytest.mark.usefixtures(db.__name__)
def test_main_mode_batch(sync, db, monkeypatch):
    monkeypatch.setenv(_ENV_TOKEN, TOKEN)
    with sqlite3.connect(db) as con:
        # Force one batch account to have no unreconciled transactions so we
        # verify grouped transaction output still includes an empty entry.
        con.execute(
            """
            UPDATE transactions
            SET cleared = 'reconciled'
            WHERE account_id = (SELECT id FROM accounts WHERE name = 'Checking')
            """
        )

    ret = main(
        (
            "--mode",
            "batch",
            "--account-target-pairs",
            "Checking=430",
            "Credit=290",
            "--sqlite-export-for-ynab-db",
            db,
        )
    )

    sync.assert_called()
    assert ret == 0


@patch("reconciler_for_ynab._main.sync")
@pytest.mark.usefixtures(db.__name__)
@pytest.mark.parametrize(
    ("regex", "substr"),
    (
        pytest.param("c", "My Budget", id="more than 1"),
        pytest.param("foo", "nothing!", id="none"),
    ),
)
def test_main_not_one_account(sync, db, monkeypatch, regex, substr):
    monkeypatch.setenv(_ENV_TOKEN, TOKEN)

    with pytest.raises(ValueError) as excinfo:
        main(
            (
                "--account-name-regex",
                regex,
                "--target",
                "500",
                "--sqlite-export-for-ynab-db",
                db,
            )
        )

    assert "Must have 1 total account matches" in str(excinfo.value)
    assert substr in str(excinfo.value)


@pytest.mark.asyncio
@patch("reconciler_for_ynab._main.sync")
@pytest.mark.usefixtures(db.__name__)
@pytest.mark.usefixtures(mock_aioresponses.__name__)
async def test_main_do_reconcile(sync, db, mock_aioresponses):
    with sqlite3.connect(db) as con:
        con.create_function(
            "REGEXP", 2, lambda x, y: bool(re.search(y, x, re.IGNORECASE))
        )
        con.row_factory = _row_factory

        cur = con.cursor()

        transactions = fetch_transactions(cur, fetch_budget_accts(cur, ["checking"]))[0]

    mock_aioresponses.patch(
        re.compile("https://api.ynab.com/v1/budgets/.+/transactions"),
        body=json.dumps(
            {
                "data": {
                    "transactions": [
                        {"id": t.id, "cleared": "reconciled"} for t in transactions
                    ]
                }
            }
        ),
    )

    await do_reconcile(TOKEN, BUDGET_ID, transactions)


@pytest.mark.asyncio
@patch("reconciler_for_ynab._main.sync")
@pytest.mark.usefixtures(db.__name__)
@pytest.mark.usefixtures(mock_aioresponses.__name__)
async def test_main_do_reconcile_error_4034(sync, db, mock_aioresponses):
    with sqlite3.connect(db) as con:
        con.create_function(
            "REGEXP", 2, lambda x, y: bool(re.search(y, x, re.IGNORECASE))
        )
        con.row_factory = _row_factory

        cur = con.cursor()

        transactions = fetch_transactions(cur, fetch_budget_accts(cur, ["checking"]))[0]

    mock_aioresponses.patch(
        re.compile("https://api.ynab.com/v1/budgets/.+/transactions"),
        body=json.dumps(
            {
                "data": {
                    "transactions": [
                        {"id": t.id, "cleared": "reconciled"} for t in transactions
                    ]
                }
            }
        ),
        payload={"error": {"id": "403.4"}},
    )

    for t in transactions:
        mock_aioresponses.patch(
            re.compile("https://api.ynab.com/v1/budgets/.+/transactions"),
            body=json.dumps(
                {"data": {"transactions": [{"id": t.id, "cleared": "reconciled"}]}}
            ),
        )

    await do_reconcile(TOKEN, BUDGET_ID, transactions)
