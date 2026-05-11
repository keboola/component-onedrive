"""
Created on 12. 11. 2018

@author: esner
"""

import os
from unittest import mock

import pytest
from freezegun import freeze_time

from component import Component


@freeze_time("2010-10-10")
@mock.patch.dict(os.environ, {"KBC_DATADIR": "./non-existing-dir"})
def test_run_no_cfg_fails():
    with pytest.raises(ValueError):
        comp = Component()
        comp.run()
