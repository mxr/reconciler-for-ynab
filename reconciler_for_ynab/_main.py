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

_NEG_BAL_ACCT_TYPES = frozenset(("checking", "savings", "cash"))

_LOCALE_EN_US = "en_US"


@dataclass(frozen=True)
class Transaction:
    plan_id: str
    id: str
    amount: Decimal
    payee: str
    cleared: str

    def pretty(self, currency: str, locale: str | None) -> str:
        return f"{format_currency(self.amount, currency=currency, locale=locale):>10} - {self.payee}"


@dataclass(frozen=True)
class PlanAccount:
    plan_id: str
    account_name: str
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
        help="Whether to **DROP ALL TABLES** and fetch all plan data again. If unset, this tool only does an incremental refresh",
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

        plan_accts = fetch_plan_accts(cur, account_name_regexes)
        transactions = fetch_transactions(cur, plan_accts)

    rets = list(
        await asyncio.gather(
            *(
                asyncio.create_task(
                    _reconcile_account(
                        token,
                        acct,
                        txns,
                        rt * (-1 if acct.account_type in _NEG_BAL_ACCT_TYPES else 1),
                        reconcile,
                    )
                )
                for rt, acct, txns in zip(
                    raw_targets, plan_accts, transactions, strict=True
                )
            )
        )
    )

    print("Done.")

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
    plan_acct: PlanAccount,
    transactions: list[Transaction],
    target: Decimal,
    reconcile: bool,
) -> int:
    prefix = f"[{plan_acct.account_name}]"

    to_reconcile, balance_met = find_to_reconcile(
        transactions,
        plan_acct.cleared_balance,
        target,
        progress_desc=f"{prefix} Testing combinations",
    )

    if not to_reconcile:
        if balance_met:
            print(f"{prefix} Balance already reconciled to target")
            return 0
        else:
            pretty_target = format_currency(
                target, currency=plan_acct.currency, locale=_LOCALE_EN_US
            )
            print(f"{prefix} No match found for target {pretty_target}")
            return 1

    print(
        f"{prefix} Match found:",
        *(
            f"{prefix} * {t.pretty(plan_acct.currency, _LOCALE_EN_US)}"
            for t in sorted(to_reconcile, key=lambda t: t.amount)
        ),
        sep=os.linesep,
    )

    if reconcile:
        await do_reconcile(
            token,
            plan_acct.plan_id,
            to_reconcile,
            progress_desc=f"{prefix} Reconciling",
        )

    return 0


def fetch_plan_accts(
    cur: sqlite3.Cursor, account_name_regexes: list[str]
) -> list[PlanAccount]:
    plan_accts = cur.execute(
        f"""
            SELECT
                plans.id as plan_id
                , plans.name as plan_name
                , accounts.name as account_name
                , accounts.type as account_type
                , accounts.id as account_id
                , accounts.type as account_type
                , accounts.cleared_balance
                , plans.currency_format_iso_code
            FROM accounts
            JOIN plans
                ON accounts.plan_id = plans.id
            WHERE
                TRUE
                AND NOT deleted
                AND NOT closed
                AND ({" OR ".join("REGEXP(accounts.name, ?)" for _ in account_name_regexes)})
            ORDER BY
                CASE
                    {" ".join(f"WHEN REGEXP(accounts.name, ?) THEN {i}" for i, _ in enumerate(account_name_regexes))}
                END
            """,
        (*account_name_regexes, *account_name_regexes),
    ).fetchall()

    if len(plan_accts) != len(account_name_regexes):
        raise ValueError(
            f"\n❌ Must have {len(account_name_regexes)} total account matches for the supplied pairs, "
            f"but instead found: {_pretty(plan_accts)}\n"
            "Change account regexes to be more precise and try again."
        )

    return [
        PlanAccount(
            plan_id=pl["plan_id"],
            account_name=pl["account_name"],
            account_id=pl["account_id"],
            cleared_balance=Decimal(-pl["cleared_balance"]) / 1000,
            account_type=pl["account_type"],
            currency=pl["currency_format_iso_code"],
        )
        for pl in plan_accts
    ]


def _pretty(plan_accts: list[dict[str, Any]]) -> str:
    if not plan_accts:
        return "nothing!"

    return "\n" + "\n".join(
        sorted(f" * {pl['plan_name']} - {pl['account_name']}" for pl in plan_accts)
    )


def fetch_transactions(
    cur: sqlite3.Cursor, plan_accts: list[PlanAccount]
) -> list[list[Transaction]]:
    assert plan_accts

    unreconciled = cur.execute(
        f"""
            SELECT
                id
                , plan_id
                , account_id
                , amount
                , payee_name
                , cleared
            FROM transactions
            WHERE
                TRUE
                AND cleared != 'reconciled'
                AND NOT deleted
                AND ({" OR ".join("account_id = ?" for _ in plan_accts)})
            ORDER BY date
            """,
        tuple(pl.account_id for pl in plan_accts),
    ).fetchall()

    grouped: dict[str, list[Transaction]] = {pl.account_id: [] for pl in plan_accts}
    for u in unreconciled:
        grouped[u["account_id"]].append(
            Transaction(
                u["plan_id"],
                u["id"],
                Decimal(-u["amount"]) / 1000,
                u["payee_name"],
                u["cleared"],
            )
        )

    return list(grouped.values())


def find_to_reconcile(
    transactions: list[Transaction],
    account_balance: Decimal,
    target: Decimal,
    progress_desc: str,
) -> tuple[tuple[Transaction, ...], bool]:
    cleared, uncleared = partition(transactions, lambda t: t.cleared == "cleared")

    reconciled_balance = account_balance - sum(t.amount for t in cleared)
    if reconciled_balance == target and not cleared:
        return (), True

    with tldm[Never](
        total=2 ** len(uncleared),
        desc=progress_desc,
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
    token: str,
    plan_id: str,
    to_reconcile: Sequence[Transaction],
    progress_desc: str,
) -> None:
    yc = YnabClient(token)
    with tldm[Never](total=len(to_reconcile), desc=progress_desc) as pbar:
        async with aiohttp.ClientSession() as session:
            try:
                await yc.reconcile(session, pbar, plan_id, [t.id for t in to_reconcile])
            except Error4034:
                await asyncio.gather(
                    *(
                        yc.reconcile(session, pbar, to_reconcile[0].plan_id, [t.id])
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
        plan_id: str,
        transaction_ids: list[str],
    ) -> None:
        reconciled = [{"id": t, "cleared": "reconciled"} for t in transaction_ids]

        url = f"https://api.ynab.com/v1/plans/{plan_id}/transactions"

        async with session.request(
            "PATCH", url, headers=self.headers, json={"transactions": reconciled}
        ) as resp:
            body = await resp.json()

        if body.get("error", {}).get("id") == "403.4":
            raise Error4034()

        pbar.update(len(transaction_ids))


def main(argv: Sequence[str] | None = None) -> int:
    return asyncio.run(async_main(argv))
