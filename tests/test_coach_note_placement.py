"""Item 2: the per-game coach note moves into the left column, under the KPI
sidebar (condensed), on all three game dashboards. It must be a sibling of the
sidebar container (not inside the tab-content column, whose children are
replaced on selection change), so its render callback is never clobbered."""
import inspect

import pytest


@pytest.mark.parametrize("module", ["hitting", "pitching", "catching"])
def test_note_card_in_left_column_not_main(module):
    layout = __import__(f"app.dashboards.{module}.layout", fromlist=["layout"])
    src = inspect.getsource(layout)
    assert f'note_card("{module}")' in src
    # left column widened for the note textarea
    assert '"260px"' in src
    # the main content column still exists...
    assert "[selector_row, tabs" in src
    # ...but the note card now sits BEFORE it (i.e. in the left column), not
    # inside the [selector_row, tabs, note_card, tab-content] main column.
    assert src.index("note_card") < src.index("[selector_row, tabs")
