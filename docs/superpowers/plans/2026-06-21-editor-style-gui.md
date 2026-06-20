# Editor-Style GUI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Redesign the GUI into an editor-style Warcraft III map workbench with a map overview and unified analysis report.

**Architecture:** Add a pure `w3xtool.gui_reports` module that formats overview/report blocks from `MapData`. Keep GUI construction in `App`, but only add thin widgets and refresh calls there so new behavior does not deepen the already oversized GUI file.

**Tech Stack:** Python 3.14, CustomTkinter, tkinter ttk, pytest.

---

### Task 1: Report Model

**Files:**
- Create: `w3xtool/gui_reports.py`
- Test: `tests/test_gui_reports.py`

- [ ] Write failing tests for overview/report blocks.
- [ ] Implement frozen dataclasses and report builders.
- [ ] Run focused tests.

### Task 2: Editor-Style Tabs

**Files:**
- Modify: `w3xtool/gui.py`
- Modify: `tests/gui_base.py`
- Test: `tests/test_gui_layout.py`

- [ ] Write failing GUI tests for tab labels and refresh behavior.
- [ ] Add `总览` and `分析报告` tabs.
- [ ] Rename existing tabs toward editor terminology without breaking backing attributes.
- [ ] Refresh the two new text panels when a map renders.
- [ ] Run focused GUI tests.

### Task 3: Regression

**Files:**
- Modify: `README.md`

- [ ] Document the editor-style GUI layout.
- [ ] Run the full test suite.
- [ ] Check touched source file pure LOC.
