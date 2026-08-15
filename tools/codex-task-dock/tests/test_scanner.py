from __future__ import annotations

import tempfile
import time
import unittest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from taskdock.scanner import IncrementalTaskScanner


class IncrementalTaskScannerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.dev = self.root / "docs" / "Dev"
        self.dev.mkdir(parents=True)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_reads_only_changed_known_files_after_initial_scan(self) -> None:
        first = self.dev / "task_alpha.md"
        second = self.dev / "task_beta.md"
        first.write_text("## DEV-20260814-1 第一项\n\n状态：待开发\n", encoding="utf-8")
        second.write_text("## DEV-20260814-2 第二项\n\n状态：待开发\n", encoding="utf-8")
        scanner = IncrementalTaskScanner(self.dev, poll_seconds=3, directory_backstop_ticks=20)

        tasks = scanner.tick(force=True)
        self.assertEqual(2, len(tasks))
        self.assertEqual(2, scanner.metrics["content_reads"])
        scanner.tick()
        self.assertEqual(0, scanner.metrics["files_read_last_tick"])

        time.sleep(0.01)
        first.write_text("## DEV-20260814-1 第一项已更新\n\n状态：待开发\n", encoding="utf-8")
        scanner.tick()
        self.assertEqual(1, scanner.metrics["files_read_last_tick"])
        self.assertEqual(3, scanner.metrics["content_reads"])

    def test_ignores_done_archives_and_completed_detail_checkboxes(self) -> None:
        (self.dev / "task_archive_done.md").write_text("## DEV-20260814-9 旧任务\n", encoding="utf-8")
        (self.dev / "task_current.md").write_text(
            "## DEV-20260814-3 当前任务\n\n"
            "- [x] 已完成的内部步骤\n"
            "- [ ] 仍需处理的独立步骤\n",
            encoding="utf-8",
        )
        scanner = IncrementalTaskScanner(self.dev)

        tasks = scanner.tick(force=True)

        self.assertEqual(2, len(tasks))
        self.assertTrue(all(task.source_name == "task_current.md" for task in tasks))
        self.assertTrue(any("仍需处理" in task.title for task in tasks))

    def test_delete_checks_source_signature_before_editing(self) -> None:
        source = self.dev / "task_delete.md"
        source.write_text("前言\n\n## DEV-20260814-4 删除我\n\n状态：待开发\n", encoding="utf-8")
        scanner = IncrementalTaskScanner(self.dev)
        task = scanner.tick(force=True)[0]
        source.write_text("插入的新内容\n" + source.read_text(encoding="utf-8"), encoding="utf-8")

        with self.assertRaisesRegex(ValueError, "变化"):
            scanner.delete_task_source(task)

    def test_generated_task_id_survives_unrelated_lines_inserted_above(self) -> None:
        source = self.dev / "task_generic.md"
        body = "## 开发任务：保持稳定标识\n\n状态：待开发\n"
        source.write_text(body, encoding="utf-8")
        scanner = IncrementalTaskScanner(self.dev)
        first_id = scanner.tick(force=True)[0].id
        time.sleep(0.01)
        source.write_text("项目说明\n\n" + body, encoding="utf-8")

        second_id = scanner.tick()[0].id

        self.assertEqual(first_id, second_id)

    def test_explicit_ids_are_unique_across_source_documents(self) -> None:
        (self.dev / "task_alpha.md").write_text(
            "## P0-1 Alpha task\n\nStatus: pending\n",
            encoding="utf-8",
        )
        (self.dev / "task_beta.md").write_text(
            "## P0-1 Beta task\n\nStatus: pending\n",
            encoding="utf-8",
        )
        scanner = IncrementalTaskScanner(self.dev)

        tasks = scanner.tick(force=True)

        self.assertEqual(2, len(tasks))
        self.assertEqual(2, len({task.id for task in tasks}))
        self.assertEqual({"P0-1"}, {task.display_id for task in tasks})
        for task in tasks:
            selected = scanner.task_by_id(task.id)
            self.assertIsNotNone(selected)
            self.assertEqual(task.source_name, selected.source_name)
            self.assertEqual(task.title, selected.title)


if __name__ == "__main__":
    unittest.main()
