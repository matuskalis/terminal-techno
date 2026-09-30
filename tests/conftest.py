import random

import numpy as np
import pytest


@pytest.fixture(autouse=True)
def seeded_randomness():
    """The kick click, hats and claps draw noise from numpy's global generator, randomize_track from random's."""
    np.random.seed(1234)
    random.seed(1234)
