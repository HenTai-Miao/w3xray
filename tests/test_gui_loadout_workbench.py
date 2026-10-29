"""Headless worker and preference contracts; real Tk acceptance is separate."""

import json
from pathlib import Path
from types import SimpleNamespace
import threading
from typing import Any, cast

from gametool import gui_loadout_workbench as gui
from gametool.loadout_report import read_loadout_report, select_loadout_report


def _selection(tmp_path: Path):
    path = tmp_path / "plan.json"
    path.write_text(json.dumps({"schema": 1, "codes": ["I001"] * 6}), encoding="utf-8")
    return select_loadout_report(read_loadout_report(path))


def test_old_worker_result_does_not_replace_new_source(tmp_path):
    selection = _selection(tmp_path)
    host = SimpleNamespace(_closed=False, _generation=8)
    gui.LoadoutWorkbench._receive_selection(cast(Any, host), selection, 7)
    assert vars(host) == {"_closed": False, "_generation": 8}


def test_search_reads_tk_values_on_calling_thread_and_delivers_via_queue(tmp_path):
    selection = _selection(tmp_path)
    main_thread = threading.get_ident()
    queued = []
    started = []

    def get_query():
        assert threading.get_ident() == main_thread
        return "I001"

    host = SimpleNamespace(
        _report=selection.report,
        _generation=4,
        _fresh=True,
        query_var=SimpleNamespace(get=get_query),
        _memo=lambda: None,
        _cancel_gui_worker_group=lambda group: None,
        _post_gui_worker=lambda ticket, callback: queued.append(callback),
        _start_gui_worker=lambda group, work, replace: started.append(
            (group, work, replace)
        ),
        _receive_selection=lambda *args, **kwargs: queued.append((args, kwargs)),
    )
    gui.LoadoutWorkbench.search(cast(Any, host))
    assert started[0][0] == "loadout-query"
    thread = threading.Thread(
        target=started[0][1], args=(SimpleNamespace(cancellation=threading.Event()),)
    )
    thread.start()
    thread.join()
    assert len(queued) == 1 and callable(queued[0])
    queued.pop(0)()
    args, kwargs = queued.pop()
    assert len(args[0].records[0].slots) == 6
    assert args[1] == 4 and kwargs["fresh"] is True


def test_preferences_preserve_complete_source_query_and_encoding_in_private_root(
    tmp_path, monkeypatch
):
    path = tmp_path / "loadout-workbench.json"
    monkeypatch.setattr(gui, "_memo_path", lambda: path)
    values = {
        "source": "C:/资料/装备.json",
        "query": "one && two\nexact",
        "encoding": "utf-16-le",
    }
    gui._save_memo(values)
    assert gui._load_memo() == values
    assert json.loads(path.read_text(encoding="utf-8")) == values
    path.write_text("broken", encoding="utf-8")
    assert gui._load_memo() == {}
