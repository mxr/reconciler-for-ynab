# reconciler-for-ynab

[![pre-commit.ci status](https://results.pre-commit.ci/badge/github/mxr/reconciler-for-ynab/main.svg)](https://results.pre-commit.ci/latest/github/mxr/reconciler-for-ynab/main)

Reconcile for YNAB - Reconcile YNAB transactions from the CLI

## What This Does

When YNAB imports your transactions and balances in sync, reconciliation is a simple one-click process. But sometimes there’s a mismatch, and hunting it down is tedious. I was frustrated with going line-by-line through records to find which transactions should be cleared and reconciled, so I wrote this tool. It streamlines the process by finding which transactions should be reconciled to match a target balance. It will either output the transactions to reconcile, or reconcile them automatically through the [YNAB API](https://api.ynab.com/).

Suppose I want to automatically reconcile my credit card ending in 1234 to \$1,471.52. I can do that as follows:

```console
$ reconciler-for-ynab --reconcile --account-name-regex 'credit.+1234' --target 1471.32 
** Refreshing SQLite DB **
Fetching budget data...
Budget Data: 100%|████████████████████████████████████████████████████████| 10/10 [00:00<00:00, 52.24it/s]
Done
Inserting budget data...
Payees: 100%|█████████████████████████████████████████████████████████████| 7/7 [00:00<00:00, 2252.93it/s]
Transactions: 100%|███████████████████████████████████████████████████████| 14/14 [00:00<00:00, 10605.07it/s]
Done
** Done **
Testing combinations: 100%|███████████████████████████████████████████████| 32/32 [00:00<00:00, 1065220.06it/s]
Match found:
*      $3.04 - Starbucks
*     $45.14 - Caffe Panna
Reconciling: 100%|████████████████████████████████████████████████████████| 2/2 [00:00<00:00, 11.76it/s]
Done
```

## Installation

```console
$ pip install reconciler-for-ynab
```

## Usage

### Token

Provision a [YNAB Personal Access Token](https://api.ynab.com/#personal-access-tokens) and save it as an environment variable.

```console
$ export YNAB_PERSONAL_ACCESS_TOKEN="..."
```

### Quickstart

Run the tool from the terminal to print out the transactions:

```console
$ reconciler-for-ynab --account-name-regex 1234 --target 500.30
```

Run it again with `--reconcile` to reconcile the account.

```console
$ reconciler-for-ynab --account-name-regex 1234 --target 500.30 --reconcile
```

### All Options

```console
$ reconcile-for-ynab --help
usage: reconciler-for-ynab [-h] --account-name-regex ACCOUNT_NAME_REGEX --target TARGET [--reconcile] [--sqlite-export-for-ynab-db SQLITE_EXPORT_FOR_YNAB_DB]
                           [--sqlite-export-for-ynab-full-refresh] [--version]

options:
  -h, --help            show this help message and exit
  --account-name-regex ACCOUNT_NAME_REGEX
                        Regex to match account name (must match exactly one account)
  --target TARGET       Target balance to match towards for reconciliation
  --reconcile           Whether to actually perform the reconciliation - if not set, just shows the transcations that would be reconciled
  --sqlite-export-for-ynab-db SQLITE_EXPORT_FOR_YNAB_DB
                        Path to sqlite-export-for-ynab SQLite DB file (respects sqlite-export-for-ynab configuration)
  --sqlite-export-for-ynab-full-refresh
                        Whether to do a full refresh of the YNAB data - if not set, only does an incremental refresh
  --version             show program's version number and exit
```
