from __future__ import annotations

import unittest
from datetime import datetime, timezone

from vro.agents.services import Services
from vro.config import Settings
from vro.util import set_now
from vro.workflow import Workflow

FROZEN = datetime(2026, 10, 24, 9, 0, tzinfo=timezone.utc)


def fresh():
    set_now(FROZEN)
    svc = Services(Settings(db_path=":memory:", llm_provider="rules", app_env="test"))
    return svc, Workflow(svc)


class Base(unittest.TestCase):
    def setUp(self):
        self.svc, self.wf = fresh()

    def tearDown(self):
        set_now(None)
