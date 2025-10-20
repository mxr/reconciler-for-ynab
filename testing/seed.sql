CREATE TABLE budgets (
    id TEXT PRIMARY KEY
    , name TEXT
    , currency_format_currency_symbol TEXT
)
;

INSERT INTO budgets VALUES (
    'a20542ae-bb3e-4282-8b3e-df3bdea4be10'
    , 'My Budget'
    , '$'
)
;

CREATE TABLE accounts (
    id TEXT PRIMARY KEY
    , budget_id TEXT
    , cleared_balance INT
    , closed BOOLEAN
    , deleted BOOLEAN
    , name TEXT
    , type TEXT
)
;

INSERT INTO accounts VALUES (
    '8fe2a49b-17b9-47a1-8aaa-c60d661e7f25'
    , (
        SELECT id FROM budgets
        ORDER BY id LIMIT 1
    )
    , 430000
    , 0
    , 0
    , 'Checking'
    , 'checking'
)
;

INSERT INTO accounts VALUES (
    'ab56a1c8-439e-4eaf-931b-37f2d68d1cf5'
    , (
        SELECT id FROM budgets
        ORDER BY id LIMIT 1
    )
    , -200000
    , 0
    , 0
    , 'Credit Card'
    , 'creditCard'
)
;

CREATE TABLE transactions (
    id TEXT PRIMARY KEY
    , budget_id TEXT
    , account_id TEXT
    , "date" TEXT
    , amount INT
    , payee_name TEXT
    , cleared TEXT
    , deleted BOOLEAN
)
;

INSERT INTO transactions VALUES (
    'ae3d9f6b-07f1-4c49-9137-5133c8bf0500'
    , (
        SELECT id FROM budgets
        ORDER BY id LIMIT 1
    )
    , (
        SELECT id FROM accounts
        WHERE name = 'Checking' LIMIT 1
    )
    , '2025-08-01'
    , 400000
    , 'Payee'
    , 'reconciled'
    , 0
)
;

INSERT INTO transactions VALUES (
    '9a97f337-28db-4c2d-990f-d9ec0e9bc765'
    , (
        SELECT id FROM budgets
        ORDER BY id LIMIT 1
    )
    , (
        SELECT id FROM accounts
        WHERE name = 'Checking' LIMIT 1
    )
    , '2025-08-01'
    , 30000
    , 'Payee'
    , 'cleared'
    , 0
)
;

INSERT INTO transactions VALUES (
    'c479c335-b54f-48b9-8b74-49a907f1b3f2'
    , (
        SELECT id FROM budgets
        ORDER BY id LIMIT 1
    )
    , (
        SELECT id FROM accounts
        WHERE name = 'Checking' LIMIT 1
    )
    , '2025-08-01'
    , 60000
    , 'Payee'
    , 'uncleared'
    , 0
)
;

INSERT INTO transactions VALUES (
    '96817e5f-d272-4012-9790-38f8a8e2be90'
    , (
        SELECT id FROM budgets
        ORDER BY id LIMIT 1
    )
    , (
        SELECT id FROM accounts
        WHERE name = 'Checking' LIMIT 1
    )
    , '2025-08-01'
    , 20000
    , 'Payee'
    , 'uncleared'
    , 0
)
;


INSERT INTO transactions VALUES (
    'eeef0922-b226-4f8a-bf00-66d4d98e348c'
    , (
        SELECT id FROM budgets
        ORDER BY id LIMIT 1
    )
    , (
        SELECT id FROM accounts
        WHERE name = 'Checking' LIMIT 1
    )
    , '2025-08-01'
    , 10000
    , 'Payee'
    , 'uncleared'
    , 0
)
;


INSERT INTO transactions VALUES (
    '21c45599-4113-4888-9969-66d42553d870'
    , (
        SELECT id FROM budgets
        ORDER BY id LIMIT 1
    )
    , (
        SELECT id FROM accounts
        WHERE name = 'Credit Card' LIMIT 1
    )
    , '2025-08-01'
    , -400000
    , 'Payee'
    , 'reconciled'
    , 0
)
;

INSERT INTO transactions VALUES (
    '956ff61f-b0e4-4f36-bf7d-f31d008ff7e4'
    , (
        SELECT id FROM budgets
        ORDER BY id LIMIT 1
    )
    , (
        SELECT id FROM accounts
        WHERE name = 'Credit Card' LIMIT 1
    )
    , '2025-08-01'
    , -30000
    , 'Payee'
    , 'cleared'
    , 0
)
;

INSERT INTO transactions VALUES (
    'c9ca467d-e89d-4d0d-8356-f37d4f798c5f'
    , (
        SELECT id FROM budgets
        ORDER BY id LIMIT 1
    )
    , (
        SELECT id FROM accounts
        WHERE name = 'Credit Card' LIMIT 1
    )
    , '2025-08-01'
    , -60000
    , 'Payee'
    , 'uncleared'
    , 0
)
;

INSERT INTO transactions VALUES (
    '258b33fb-a2b2-4833-9274-05697c68ff1d'
    , (
        SELECT id FROM budgets
        ORDER BY id LIMIT 1
    )
    , (
        SELECT id FROM accounts
        WHERE name = 'Credit Card' LIMIT 1
    )
    , '2025-08-01'
    , -20000
    , 'Payee'
    , 'uncleared'
    , 0
)
;


INSERT INTO transactions VALUES (
    'd9faa297-f59e-4516-bcbf-664b298ff09e'
    , (
        SELECT id FROM budgets
        ORDER BY id LIMIT 1
    )
    , (
        SELECT id FROM accounts
        WHERE name = 'Credit Card' LIMIT 1
    )
    , '2025-08-01'
    , -10000
    , 'Payee'
    , 'uncleared'
    , 0
)
;
