from __future__ import annotations

import os.path
import sqlite3
from uuid import uuid4

import pytest
from aioresponses import aioresponses


BUDGET_ID_1 = str(uuid4())


@pytest.fixture()
def db(tmpdir):
    with open(os.path.join(os.path.dirname(__file__), "seed.sql")) as f:
        contents = f.read()

    path = tmpdir / "db.sqlite"
    with sqlite3.connect(path) as con:
        con.executescript(contents)
    yield str(path)


@pytest.fixture
def mock_aioresponses():
    with aioresponses() as m:
        yield m


TOKEN = f"token-{uuid4()}"

# the below must match seed.sql
BUDGET_ID = "a20542ae-bb3e-4282-8b3e-df3bdea4be10"
