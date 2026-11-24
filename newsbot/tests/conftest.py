import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
FIX = Path(__file__).resolve().parent / "fixtures"


@pytest.fixture
def fixture_text():
    return lambda name: (FIX / name).read_text(encoding="utf-8", errors="replace")


@pytest.fixture
def con(tmp_path):
    from newsbot import db
    return db.connect(tmp_path / "t.sqlite")


@pytest.fixture
def settings(tmp_path):
    from newsbot.config import Settings
    return Settings(data_dir=tmp_path)
