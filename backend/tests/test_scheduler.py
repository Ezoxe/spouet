"""Tests du parsing cron (scheduler) — fonctions pures, sans DB ni Celery broker."""

from __future__ import annotations

import pytest

from spouet.scheduler.syncer import parse_cron


def test_parse_cron_valid_hourly() -> None:
    sched = parse_cron("0 * * * *")
    # crontab.minute est un set d'entiers {0}
    assert 0 in sched.minute


def test_parse_cron_valid_complex() -> None:
    sched = parse_cron("*/15 8-18 * * 1-5")
    assert 0 in sched.minute and 15 in sched.minute
    assert 8 in sched.hour and 18 in sched.hour


@pytest.mark.parametrize(
    "expr",
    [
        "",  # vide
        "0 *",  # trop peu de champs
        "0 * * * * *",  # trop de champs
        "abc def ghi jkl mno",  # champs non numériques
    ],
)
def test_parse_cron_invalid_raises(expr: str) -> None:
    with pytest.raises(ValueError):
        parse_cron(expr)
