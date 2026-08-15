from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from taskdock.docking import _Window, _panel_owns_foreground


class DockingInteractionTests(unittest.TestCase):
    def test_defers_docking_while_panel_itself_is_foreground(self) -> None:
        panel = _Window(101, "Task Dock", "msedge.exe", None, False)

        self.assertTrue(_panel_owns_foreground(panel, 101))

    def test_defers_docking_for_edge_owned_native_popup(self) -> None:
        panel = _Window(101, "Task Dock", "msedge.exe", None, False)
        with mock.patch("taskdock.docking._process_executable", return_value="msedge.exe"):
            self.assertTrue(_panel_owns_foreground(panel, 202))

    def test_keeps_docking_active_for_codex_foreground(self) -> None:
        panel = _Window(101, "Task Dock", "msedge.exe", None, False)
        with mock.patch("taskdock.docking._process_executable", return_value="Codex.exe"):
            self.assertFalse(_panel_owns_foreground(panel, 303))


if __name__ == "__main__":
    unittest.main()
