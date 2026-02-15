from __future__ import annotations

import argparse
import asyncio
import itertools
import os
import re
import sqlite3
from dataclasses import dataclass
from dataclasses import field
from decimal import Decimal
from importlib.metadata import version
from pathlib import Path
from typing import Any
from typing import Never
from typing import TYPE_CHECKING

import aiohttp
from babel.numbers import format_currency
from sqlite_export_for_ynab import default_db_path
from sqlite_export_for_ynab import sync
from tldm import tldm

if TYPE_CHECKING:
    from collections.abc import Callable
    from collections.abc import Iterable
    from collections.abc import Sequence


_ENV_TOKEN = "YNAB_PERSONAL_ACCESS_TOKEN"

_PACKAGE = "reconciler-for-ynab"

_NEGATIVE_BAL_ACCOOUNT_TYPES = frozenset(("checking", "savings", "cash"))


@dataclass(frozen=True)
class Transaction:
    budget_id: str
    id: str
    amount: Decimal
    payee: str
    cleared: str

    def pretty(self, currency: str, locale: str | None) -> str:
        return f"{format_currency(self.amount, currency=currency, locale=locale):>10} - {self.payee}"


@dataclass(frozen=True)
class BudgetAccount:
    budget_id: str
    account_id: str
    account_type: str
    cleared_balance: Decimal
    currency: str


async def async_main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog=_PACKAGE)
    parser.add_argument(
        "--mode",
        choices=("single", "batch"),
        default="single",
        help="Reconciliation mode. `single` uses --account-name-regex/--target. `batch` uses --account-target-pairs.",
    )
    parser.add_argument(
        "--account-name-regex",
        help="Regex to match account name (must match exactly one account)",
    )
    parser.add_argument(
        "--target",
        type=lambda s: Decimal(re.sub("[,$]", "", s)),
        help="Target balance to match towards for reconciliation",
    )
    parser.add_argument(
        "--account-target-pairs",
        nargs="+",
        help=(
            "Batch mode only. Account regex/target pairs in "
            "`ACCOUNT_NAME_REGEX=TARGET` format (example: `Checking=500.30`)."
        ),
    )
    parser.add_argument(
        "--reconcile",
        action="store_true",
        help="Whether to actually perform the reconciliation - if unset, this tool only prints the transactions that would be reconciled",
    )
    parser.add_argument(
        "--sqlite-export-for-ynab-db",
        type=Path,
        default=default_db_path(),
        help="Path to sqlite-export-for-ynab SQLite DB file (respects sqlite-export-for-ynab configuration; if unset, will be %(default)s)",
    )
    parser.add_argument(
        "--sqlite-export-for-ynab-full-refresh",
        action="store_true",
        help="Whether **DROP ALL TABLES** and fetch all budget data again. If unset, this tool only does an incremental refresh",
    )
    parser.add_argument(
        "--version", action="version", version=f"%(prog)s {version(_PACKAGE)}"
    )

    args = parser.parse_args(argv)
    mode: str = args.mode
    account_name_regex: str | None = args.account_name_regex
    raw_target: Decimal | None = args.target
    account_target_pairs: list[str] | None = args.account_target_pairs
    reconcile: bool = args.reconcile
    db: Path = args.sqlite_export_for_ynab_db
    full_refresh: bool = args.sqlite_export_for_ynab_full_refresh

    if mode == "single":
        if account_target_pairs:
            raise ValueError(
                "`--account-target-pairs` is only valid when `--mode batch` is selected."
            )
        if account_name_regex is None or raw_target is None:
            raise ValueError(
                "`--mode single` requires both `--account-name-regex` and `--target`."
            )
        account_name_regexes = [account_name_regex]
        raw_targets = [raw_target]
    else:
        assert mode == "batch"
        if account_name_regex is not None or raw_target is not None:
            raise ValueError(
                "`--mode batch` cannot be used with `--account-name-regex` or `--target`; "
                "use `--account-target-pairs` instead."
            )
        if not account_target_pairs:
            raise ValueError("`--mode batch` requires `--account-target-pairs`.")
        account_name_regexes, raw_targets = _parse_account_targets(account_target_pairs)

    token = os.environ.get(_ENV_TOKEN)
    if not token:
        raise ValueError(
            f"Must set YNAB access token as {_ENV_TOKEN!r} "
            "environment variable. See "
            "https://api.ynab.com/#personal-access-tokens"
        )

    print("** Refreshing SQLite DB **")
    await sync(token, db, full_refresh)
    print("** Done **")

    with sqlite3.connect(db) as con:
        con.create_function(
            "REGEXP", 2, lambda x, y: bool(re.search(y, x, re.IGNORECASE))
        )
        con.row_factory = _row_factory

        cur = con.cursor()

        budget_accts = fetch_budget_accts(cur, account_name_regexes)
        transactions = fetch_transactions(cur, budget_accts)

    rets = []
    for rt, acct, txns in zip(raw_targets, budget_accts, transactions, strict=True):
        rets.append(
            await _reconcile_account(
                token,
                acct,
                txns,
                rt * (-1 if acct.account_type in _NEGATIVE_BAL_ACCOOUNT_TYPES else 1),
                reconcile,
            )
        )

    if len(rets) > 1:
        print("Batch reconciling done.")

    return max(rets)


def _parse_account_targets(
    account_target_pairs: list[str],
) -> tuple[list[str], list[Decimal]]:
    account_name_regexes: list[str] = []
    raw_targets: list[Decimal] = []
    for pair in account_target_pairs:
        regex, _, target = pair.partition("=")
        account_name_regexes.append(regex)
        raw_targets.append(Decimal(re.sub("[,$]", "", target)))
    return account_name_regexes, raw_targets


async def _reconcile_account(
    token: str,
    budget_acct: BudgetAccount,
    transactions: list[Transaction],
    target: Decimal,
    reconcile: bool,
) -> int:
    to_reconcile, balance_met = find_to_reconcile(
        transactions, budget_acct.cleared_balance, target
    )

    if not to_reconcile:
        if balance_met:
            print("Balance already reconciled to target")
            return 0
        else:
            print("No match found")
            return 1

    print("Match found:")
    for t in sorted(to_reconcile, key=lambda t: t.amount):
        print("*", t.pretty(budget_acct.currency, "en_US"))

    if reconcile:
        await do_reconcile(token, budget_acct.budget_id, to_reconcile)

    print("Done")
    return 0


def fetch_budget_accts(
    cur: sqlite3.Cursor, account_name_regexes: list[str]
) -> list[BudgetAccount]:
    budget_accts = cur.execute(
        f"""
            SELECT
                budgets.id as budget_id
                , budgets.name as budget_name
                , accounts.name as account_name
                , accounts.type as account_type
                , accounts.id as account_id
                , accounts.type as account_type
                , accounts.cleared_balance
                , budgets.currency_format_currency_symbol
            FROM accounts
            JOIN budgets
                ON accounts.budget_id = budgets.id
            WHERE
                TRUE
                AND NOT deleted
                AND NOT closed
                AND ({" OR ".join("REGEXP(accounts.name, ?)" for _ in account_name_regexes)})
            ORDER BY budget_name, account_name
            """,
        tuple(account_name_regexes),
    ).fetchall()

    if len(budget_accts) != len(account_name_regexes):
        raise ValueError(
            f"\n❌ Must have {len(account_name_regexes)} total account matches for the supplied pairs, "
            f"but instead found: {_pretty(budget_accts)}\n"
            "Change account regexes to be more precise and try again."
        )

    return [
        BudgetAccount(
            budget_id=b["budget_id"],
            account_id=b["account_id"],
            cleared_balance=Decimal(-b["cleared_balance"]) / 1000,
            account_type=b["account_type"],
            currency=b["currency_format_currency_symbol"],
        )
        for b in budget_accts
    ]


def _pretty(budget_accts: list[dict[str, Any]]) -> str:
    if not budget_accts:
        return "nothing!"

    return "\n" + "\n".join(
        sorted(f" * {b['budget_name']} - {b['account_name']}" for b in budget_accts)
    )


def fetch_transactions(
    cur: sqlite3.Cursor, budget_accts: list[BudgetAccount]
) -> list[list[Transaction]]:
    assert budget_accts

    unreconciled = cur.execute(
        f"""
            SELECT
                id
                , budget_id
                , account_id
                , amount
                , payee_name
                , cleared
            FROM transactions
            WHERE
                TRUE
                AND cleared != 'reconciled'
                AND NOT deleted
                AND ({" OR ".join("account_id = ?" for _ in budget_accts)})
            ORDER BY date
            """,
        tuple(b.account_id for b in budget_accts),
    ).fetchall()

    grouped: dict[str, list[Transaction]] = {b.account_id: [] for b in budget_accts}
    for u in unreconciled:
        grouped[u["account_id"]].append(
            Transaction(
                u["budget_id"],
                u["id"],
                Decimal(-u["amount"]) / 1000,
                u["payee_name"],
                u["cleared"],
            )
        )

    return list(grouped.values())


def find_to_reconcile(
    transactions: list[Transaction], account_balance: Decimal, target: Decimal
) -> tuple[tuple[Transaction, ...], bool]:
    cleared, uncleared = partition(transactions, lambda t: t.cleared == "cleared")

    reconciled_balance = account_balance - sum(t.amount for t in cleared)
    if reconciled_balance == target and not cleared:
        return (), True

    with tldm[Never](
        total=2 ** len(uncleared),
        desc="Testing combinations",
        complete_bar_on_early_finish=True,
    ) as pbar:
        for n in range(len(uncleared) + 1):
            for combo in itertools.combinations(uncleared, n):
                if (
                    reconciled_balance
                    + sum(t.amount for t in itertools.chain(cleared, combo))
                    == target
                ):
                    return tuple(itertools.chain(cleared, combo)), True
                pbar.update()

    return (), False


async def do_reconcile(
    token: str, budget_id: str, to_reconcile: Sequence[Transaction]
) -> None:
    yc = YnabClient(token)
    with tldm[Never](total=len(to_reconcile), desc="Reconciling") as pbar:
        async with aiohttp.ClientSession() as session:
            try:
                await yc.reconcile(
                    session, pbar, budget_id, [t.id for t in to_reconcile]
                )
            except Error4034:
                await asyncio.gather(
                    *(
                        yc.reconcile(session, pbar, to_reconcile[0].budget_id, [t.id])
                        for t in to_reconcile
                    )
                )


def partition[T](
    items: Iterable[T], func: Callable[[T], bool]
) -> tuple[list[T], list[T]]:
    trues, falses = [], []
    for i in items:
        if func(i):
            trues.append(i)
        else:
            falses.append(i)
    return trues, falses


def _row_factory(c: sqlite3.Cursor, row: tuple[Any, ...]) -> dict[str, Any]:
    return {d[0]: r for d, r in zip(c.description, row, strict=True)}


class Error4034(Exception):
    """Raised when an internal YNAB rate-limit is reached. A workaround is to reconcile one-at-a-time."""


@dataclass
class YnabClient:
    token: str
    headers: dict[str, str] = field(init=False)

    def __post_init__(self) -> None:
        self.headers = {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json",
        }

    async def reconcile(
        self,
        session: aiohttp.ClientSession,
        pbar: tldm[Never],
        budget_id: str,
        transaction_ids: list[str],
    ) -> None:
        reconciled = [{"id": t, "cleared": "reconciled"} for t in transaction_ids]

        url = f"https://api.ynab.com/v1/budgets/{budget_id}/transactions"

        async with session.request(
            "PATCH", url, headers=self.headers, json={"transactions": reconciled}
        ) as resp:
            body = await resp.json()

        if body.get("error", {}).get("id") == "403.4":
            raise Error4034()

        pbar.update(len(transaction_ids))


def main(argv: Sequence[str] | None = None) -> int:
    return asyncio.run(async_main(argv))
