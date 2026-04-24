from __future__ import annotations

from reconciler_for_ynab._main import main


def test_main_points_to_manager_for_ynab(capsys):
    ret = main()

    capsys.readouterr()
    assert ret == 1
