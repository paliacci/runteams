import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

import chat_attachments
from runteams_core import task_inputs


class TaskInputTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="runteams-task-inputs-")
        self.root = Path(self.temporary.name)
        self.staging = self.root / "staging"
        with chat_attachments._SELECTIONS_LOCK:
            chat_attachments._SELECTIONS.clear()

    def tearDown(self):
        with chat_attachments._SELECTIONS_LOCK:
            chat_attachments._SELECTIONS.clear()
        self.temporary.cleanup()

    def test_file_and_folder_are_stable_snapshots_materialized_for_employee(self):
        source = self.root / "source"
        source.mkdir()
        brief = source / "brief.md"
        brief.write_text("frozen brief", encoding="utf-8")
        research = source / "research"
        research.mkdir()
        (research / "notes.txt").write_text("source notes", encoding="utf-8")

        with mock.patch.object(
                chat_attachments, "_selection_root", return_value=str(self.staging)):
            selections = chat_attachments._stage_native_paths([brief, research])
            saved = task_inputs.consume(
                self.root / "core", 17,
                [item["token"] for item in selections])

        serialized = json.dumps(saved, ensure_ascii=False)
        self.assertNotIn(str(source), serialized)
        self.assertEqual([item["kind"] for item in saved], ["file", "folder"])
        self.assertTrue(all(item["ref"].startswith("task-input://17/") for item in saved))

        # The task owns a copy: later edits to the user's source cannot change a run.
        brief.write_text("changed after selection", encoding="utf-8")
        (research / "notes.txt").write_text("changed after selection", encoding="utf-8")
        workspace = self.root / "workspace"
        materialized = task_inputs.materialize(
            self.root / "core", 17, saved, workspace)
        self.assertEqual(
            (workspace / materialized[0]["path"]).read_text(encoding="utf-8"),
            "frozen brief")
        self.assertEqual(
            (workspace / materialized[1]["path"] / "notes.txt").read_text(
                encoding="utf-8"),
            "source notes")

        source_path = task_inputs.source_for_item(self.root / "core", 17, saved[0])
        self.assertEqual(source_path.read_text(encoding="utf-8"), "frozen brief")

        task_inputs.remove(self.root / "core", 17, saved[0]["id"])
        self.assertFalse(
            task_inputs.task_root(self.root / "core", 17).joinpath(saved[0]["id"]).exists())
        task_inputs.discard_task(self.root / "core", 17)
        self.assertFalse((self.root / "core" / "task-inputs" / "task-17").exists())


if __name__ == "__main__":
    unittest.main()
