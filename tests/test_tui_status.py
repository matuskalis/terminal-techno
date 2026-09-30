"""The status line follows the engine when a queued board swap lands between two key presses."""

from types import SimpleNamespace

from tui import Ui


class SmallScreen:
    """Just enough of a curses window for Ui.draw on a terminal too small to draw the board."""

    def erase(self):
        pass

    def getmaxyx(self):
        return (10, 20)

    def addstr(self, *args):
        pass

    def refresh(self):
        pass


def engine(board=0, pending=None):
    names = ("alpha", "bravo", "charlie")
    return SimpleNamespace(board=board, pending=pending, boards=[SimpleNamespace(name=n) for n in names])


def test_status_follows_a_board_that_lands_between_keys():
    eng = engine(board=0, pending=1)
    ui = Ui(eng)
    ui.status = "next: 2 bravo"
    eng.board, eng.pending = 1, None  # the queued swap landed on the bar line, no key was pressed
    ui.draw(SmallScreen())
    assert ui.status == "board 2 bravo"


def test_status_is_left_alone_while_the_board_stays_the_same():
    eng = engine(board=0)
    ui = Ui(eng)
    ui.status = "crossfade off"
    ui.draw(SmallScreen())
    assert ui.status == "crossfade off"
