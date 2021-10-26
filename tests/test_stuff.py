import sys
sys.path.insert(0, '')

import app
import pytest

def test_percent():
    assert app.percent(100.0, 1.0) == 1.0




