from __future__ import annotations

import hashlib
import json
import multiprocessing
import os
import shutil
import sys
import tempfile
import traceback
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def _hold_batch_state_lock_worker(run_dir, acquired, release, result_queue) -> None:
    try:
        from paper_automation.batch_workflow import batch_state_lock

        with batch_state_lock(run_dir, timeout=5.0):
            acquired.set()
            if not release.wait(10.0):
                raise TimeoutError("test_release_timeout")
        result_queue.put(("released", ""))
    except BaseException as exc:
        result_queue.put(("error", f"{type(exc).__name__}: {exc}"))


def _attempt_batch_state_lock_worker(run_dir, result_queue) -> None:
    try:
        from paper_automation.batch_workflow import batch_state_lock

        with batch_state_lock(run_dir, timeout=0.3):
            result_queue.put(("acquired", ""))
    except TimeoutError as exc:
        result_queue.put(("timeout", str(exc)))
    except BaseException as exc:
        result_queue.put(("error", f"{type(exc).__name__}: {exc}"))


def _claim_manual_retry_worker(run_dir, start, result_queue) -> None:
    try:
        from paper_automation.batch_workflow import claim_manual_retry

        if not start.wait(10.0):
            raise TimeoutError("test_start_timeout")
        claimed, state = claim_manual_retry(run_dir, timeout=5.0)
        result_queue.put(("ok", claimed, state["manual_retry_used"]))
    except BaseException as exc:
        result_queue.put(("error", f"{type(exc).__name__}: {exc}", False))


def _concurrent_state_save_worker(paths, payload, start, replace_barrier, result_queue) -> None:
    try:
        from paper_automation.batch_workflow import save_batch_state

        if not start.wait(10.0):
            raise TimeoutError("test_start_timeout")
        original_replace = os.replace
        temporary_name = ""
        first_replace = True

        def coordinated_replace(source, destination):
            nonlocal first_replace, temporary_name
            temporary_name = Path(source).name
            if first_replace:
                first_replace = False
                replace_barrier.wait(timeout=10.0)
            return original_replace(source, destination)

        with patch.object(os, "replace", new=coordinated_replace):
            save_batch_state(paths, payload)
        result_queue.put(("ok", payload["writer"], temporary_name))
    except BaseException as exc:
        result_queue.put(("error", f"{type(exc).__name__}: {exc}"))


def _copy_pdf_worker(source, destination, filename, start, started, result_queue) -> None:
    try:
        from paper_automation.batch_workflow import copy_pdf_safely

        if not start.wait(10.0):
            raise TimeoutError("test_start_timeout")
        started.set()
        copied = copy_pdf_safely(source, destination, filename)
        result_queue.put(("ok", str(copied)))
    except BaseException as exc:
        result_queue.put(
            ("error", f"{type(exc).__name__}: {exc}", traceback.format_exc())
        )


def _controlled_copy_pdf_worker(
    source,
    destination,
    filename,
    publish_reached,
    release_publish,
    phase_queue,
    result_queue,
) -> None:
    """Pause at the old partial write or the new atomic publish boundary."""

    try:
        from paper_automation.batch_workflow import copy_pdf_safely

        original_copyfileobj = shutil.copyfileobj
        original_link = os.link
        phase_reported = False

        def report_phase(phase):
            nonlocal phase_reported
            if phase_reported:
                return
            phase_reported = True
            phase_queue.put(phase)
            publish_reached.set()
            if not release_publish.wait(10.0):
                raise TimeoutError("test_publish_release_timeout")

        def controlled_copyfileobj(source_handle, target_handle, length=0):
            prefix = source_handle.read(5)
            target_handle.write(prefix)
            target_handle.flush()
            os.fsync(target_handle.fileno())
            report_phase("direct_write")
            return original_copyfileobj(source_handle, target_handle, length)

        def controlled_link(source_path, target_path, *args, **kwargs):
            report_phase("hard_link")
            return original_link(source_path, target_path, *args, **kwargs)

        with patch.object(shutil, "copyfileobj", new=controlled_copyfileobj), patch.object(
            os,
            "link",
            new=controlled_link,
        ):
            copied = copy_pdf_safely(source, destination, filename)
        result_queue.put(("ok", str(copied)))
    except BaseException as exc:
        result_queue.put(("error", f"{type(exc).__name__}: {exc}"))


class BatchFileTests(unittest.TestCase):
    def _join_workers(self, *workers) -> None:
        for worker in workers:
            if worker is None:
                continue
            worker.join(10.0)
            if worker.is_alive():
                worker.terminate()
                worker.join(5.0)
            self.assertFalse(worker.is_alive(), f"worker did not stop: {worker.name}")

    def test_paths_and_state_are_created_under_new_run_directory(self) -> None:
        from paper_automation.batch_workflow import create_batch_paths, load_batch_state, save_batch_state

        with tempfile.TemporaryDirectory() as tmp:
            paths = create_batch_paths(Path(tmp), now=datetime(2026, 7, 10, 17, 0, 0))
            save_batch_state(paths, {"version": 1, "rows": []})

            self.assertEqual(paths.root.name, "paper_batch_20260710_170000")
            self.assertTrue(paths.pdfs.is_dir())
            self.assertTrue(paths.reports.is_dir())
            self.assertEqual(load_batch_state(paths.root)["version"], 1)

    def test_state_save_fsyncs_unique_temp_before_atomic_replace(self) -> None:
        import paper_automation.batch_workflow as workflow

        with tempfile.TemporaryDirectory() as tmp:
            paths = workflow.create_batch_paths(Path(tmp))
            events = []
            real_fsync = os.fsync
            real_replace = os.replace

            def recording_fsync(file_descriptor):
                events.append(("fsync", ""))
                return real_fsync(file_descriptor)

            def recording_replace(source, destination):
                events.append(("replace", Path(source).name))
                return real_replace(source, destination)

            with patch.object(os, "fsync", side_effect=recording_fsync), patch.object(
                os,
                "replace",
                side_effect=recording_replace,
            ):
                workflow.save_batch_state(paths, {"version": 1, "rows": []})

            self.assertGreaterEqual(len(events), 2)
            self.assertEqual(events[0][0], "fsync")
            self.assertEqual(events[1][0], "replace")
            self.assertTrue(events[1][1].startswith("batch_state.json."))
            self.assertNotEqual(events[1][1], "batch_state.json.tmp")
            self.assertFalse(list(paths.working.glob("batch_state.json.*.tmp")))

    def test_concurrent_state_saves_remain_valid_and_leave_no_temp_files(self) -> None:
        from paper_automation.batch_workflow import create_batch_paths, load_batch_state

        context = multiprocessing.get_context("spawn")
        with tempfile.TemporaryDirectory() as tmp:
            paths = create_batch_paths(Path(tmp))
            start = context.Event()
            replace_barrier = context.Barrier(2)
            result_queue = context.Queue()
            payloads = [
                {"version": 1, "writer": "one", "rows": [{"value": "a" * 2048}]},
                {"version": 1, "writer": "two", "rows": [{"value": "b" * 2048}]},
            ]
            workers = [
                context.Process(
                    target=_concurrent_state_save_worker,
                    args=(paths, payload, start, replace_barrier, result_queue),
                )
                for payload in payloads
            ]
            for worker in workers:
                worker.start()
            start.set()
            try:
                results = [result_queue.get(timeout=15.0) for _ in workers]
            finally:
                self._join_workers(*workers)

            self.assertEqual(
                sorted(result[0] for result in results),
                ["ok", "ok"],
                results,
            )
            self.assertEqual(len({result[2] for result in results}), 2)
            self.assertTrue(
                all(result[2].startswith("batch_state.json.") for result in results)
            )
            self.assertIn(load_batch_state(paths.root)["writer"], {"one", "two"})
            self.assertFalse(paths.state.with_suffix(".json.tmp").exists())
            self.assertFalse(list(paths.working.glob("batch_state.json.*.tmp")))

    def test_batch_state_lock_excludes_second_process_until_timeout(self) -> None:
        import paper_automation.batch_workflow as workflow

        self.assertTrue(hasattr(workflow, "batch_state_lock"))
        context = multiprocessing.get_context("spawn")
        with tempfile.TemporaryDirectory() as tmp:
            paths = workflow.create_batch_paths(Path(tmp))
            acquired = context.Event()
            release = context.Event()
            holder_result = context.Queue()
            contender_result = context.Queue()
            holder = context.Process(
                target=_hold_batch_state_lock_worker,
                args=(paths.root, acquired, release, holder_result),
            )
            contender = None
            holder.start()
            try:
                self.assertTrue(acquired.wait(10.0), "holder did not acquire state lock")
                contender = context.Process(
                    target=_attempt_batch_state_lock_worker,
                    args=(paths.root, contender_result),
                )
                contender.start()
                self.assertEqual(contender_result.get(timeout=10.0)[0], "timeout")
            finally:
                release.set()
                self._join_workers(holder, contender)

            self.assertEqual(holder_result.get(timeout=5.0)[0], "released")
            self.assertEqual(holder.exitcode, 0)
            self.assertEqual(contender.exitcode, 0)

    def test_batch_state_lock_is_released_after_context_exception(self) -> None:
        import paper_automation.batch_workflow as workflow

        self.assertTrue(hasattr(workflow, "batch_state_lock"))
        with tempfile.TemporaryDirectory() as tmp:
            paths = workflow.create_batch_paths(Path(tmp))
            with self.assertRaisesRegex(RuntimeError, "synthetic"):
                with workflow.batch_state_lock(paths.root, timeout=1.0):
                    raise RuntimeError("synthetic")

            with workflow.batch_state_lock(paths.root, timeout=1.0):
                pass

    def test_two_processes_cannot_claim_the_same_manual_retry(self) -> None:
        import paper_automation.batch_workflow as workflow

        self.assertTrue(hasattr(workflow, "claim_manual_retry"))
        context = multiprocessing.get_context("spawn")
        with tempfile.TemporaryDirectory() as tmp:
            paths = workflow.create_batch_paths(Path(tmp))
            workflow.save_batch_state(
                paths,
                {"version": 1, "manual_retry_used": False, "rows": []},
            )
            start = context.Event()
            result_queue = context.Queue()
            workers = [
                context.Process(
                    target=_claim_manual_retry_worker,
                    args=(paths.root, start, result_queue),
                )
                for _ in range(2)
            ]
            for worker in workers:
                worker.start()
            start.set()
            try:
                results = [result_queue.get(timeout=15.0) for _ in workers]
            finally:
                self._join_workers(*workers)

            self.assertEqual(
                [result[0] for result in results],
                ["ok", "ok"],
                results,
            )
            self.assertEqual(sorted(result[1] for result in results), [False, True])
            self.assertTrue(all(result[2] for result in results))
            self.assertTrue(workflow.load_batch_state(paths.root)["manual_retry_used"])

    def test_custom_run_name_is_cleaned_and_always_timestamped(self) -> None:
        from paper_automation.batch_workflow import create_batch_paths

        with tempfile.TemporaryDirectory() as tmp:
            paths = create_batch_paths(
                Path(tmp),
                run_name="Ti alloy batch",
                now=datetime(2026, 7, 10, 17, 0, 0),
            )

            self.assertEqual(paths.root.name, "Ti_alloy_batch_20260710_170000")

    def test_same_timestamp_creates_unique_run_directories(self) -> None:
        from paper_automation.batch_workflow import create_batch_paths

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            now = datetime(2026, 7, 10, 17, 0, 0)

            first = create_batch_paths(root, now=now)
            second = create_batch_paths(root, now=now)

            self.assertEqual(first.root.name, "paper_batch_20260710_170000")
            self.assertEqual(second.root.name, "paper_batch_20260710_170000_2")
            self.assertNotEqual(first.root, second.root)

    def test_run_name_rejects_absolute_and_traversal_paths(self) -> None:
        from paper_automation.batch_workflow import create_batch_paths

        with tempfile.TemporaryDirectory() as tmp:
            sandbox = Path(tmp)
            output_root = sandbox / "output"
            invalid_names = [
                str(sandbox / "absolute"),
                "..",
                "../escape",
                r"..\escape",
            ]

            for run_name in invalid_names:
                with self.subTest(run_name=run_name):
                    with self.assertRaisesRegex(ValueError, "invalid_run_name"):
                        create_batch_paths(output_root, run_name=run_name)

    def test_run_name_rejects_superscript_windows_device_names(self) -> None:
        from paper_automation.batch_workflow import create_batch_paths

        with tempfile.TemporaryDirectory() as tmp:
            for run_name in ("COM¹", "COM²", "COM³", "LPT¹", "LPT²", "LPT³"):
                with self.subTest(run_name=run_name):
                    with self.assertRaisesRegex(ValueError, "invalid_run_name"):
                        create_batch_paths(Path(tmp), run_name=run_name)

    def test_pdf_validation_and_copy_are_non_destructive_and_deduplicated(self) -> None:
        from paper_automation.batch_workflow import copy_pdf_safely, is_valid_pdf

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source.pdf"
            source.write_bytes(b"%PDF-1.7\nvalid payload")
            destination = root / "pdfs"

            first = copy_pdf_safely(source, destination, "paper.pdf")
            second = copy_pdf_safely(source, destination, "paper.pdf")

            self.assertTrue(is_valid_pdf(first))
            self.assertEqual(first, second)
            self.assertTrue(source.exists())
            self.assertEqual(len(list(destination.glob("*.pdf"))), 1)

    def test_same_pdf_concurrent_copies_publish_one_complete_target(self) -> None:
        from paper_automation.batch_workflow import is_valid_pdf

        context = multiprocessing.get_context("spawn")
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source.pdf"
            source.write_bytes(b"%PDF-1.7\nconcurrent identical payload")
            destination = root / "pdfs"
            publish_reached = context.Event()
            release_publish = context.Event()
            phase_queue = context.Queue()
            result_queue = context.Queue()
            second_start = context.Event()
            second_started = context.Event()
            first = context.Process(
                target=_controlled_copy_pdf_worker,
                args=(
                    source,
                    destination,
                    "paper.pdf",
                    publish_reached,
                    release_publish,
                    phase_queue,
                    result_queue,
                ),
            )
            second = context.Process(
                target=_copy_pdf_worker,
                args=(
                    source,
                    destination,
                    "paper.pdf",
                    second_start,
                    second_started,
                    result_queue,
                ),
            )
            first.start()
            results = []
            try:
                self.assertTrue(
                    publish_reached.wait(10.0),
                    "first worker did not reach its publish boundary",
                )
                phase = phase_queue.get(timeout=5.0)
                second.start()
                second_start.set()
                self.assertTrue(second_started.wait(10.0), "second worker did not start")
                if phase == "direct_write":
                    results.append(result_queue.get(timeout=10.0))
                release_publish.set()
                while len(results) < 2:
                    results.append(result_queue.get(timeout=10.0))
            finally:
                release_publish.set()
                self._join_workers(first, second)

            self.assertEqual([result[0] for result in results], ["ok", "ok"], results)
            copied_paths = [Path(result[1]) for result in results]
            delivered = list(destination.glob("*.pdf"))
            self.assertEqual(copied_paths[0], copied_paths[1])
            self.assertEqual(len(delivered), 1)
            self.assertTrue(is_valid_pdf(delivered[0]))

    def test_terminated_publish_leaves_no_partial_pdf_and_next_copy_recovers(self) -> None:
        from paper_automation.batch_workflow import copy_pdf_safely, is_valid_pdf

        context = multiprocessing.get_context("spawn")
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source.pdf"
            payload = b"%PDF-1.7\nrecoverable payload after termination"
            source.write_bytes(payload)
            destination = root / "pdfs"
            publish_reached = context.Event()
            release_publish = context.Event()
            phase_queue = context.Queue()
            result_queue = context.Queue()
            worker = context.Process(
                target=_controlled_copy_pdf_worker,
                args=(
                    source,
                    destination,
                    "paper.pdf",
                    publish_reached,
                    release_publish,
                    phase_queue,
                    result_queue,
                ),
            )
            worker.start()
            try:
                self.assertTrue(
                    publish_reached.wait(10.0),
                    "worker did not reach its publish boundary",
                )
                phase_queue.get(timeout=5.0)
                worker.terminate()
                worker.join(10.0)
                self.assertFalse(worker.is_alive())
            finally:
                if worker.is_alive():
                    worker.terminate()
                    worker.join(5.0)

            delivered_before_recovery = list(destination.glob("*.pdf"))
            recovered = copy_pdf_safely(source, destination, "paper.pdf")
            delivered_after_recovery = list(destination.glob("*.pdf"))

            self.assertEqual(delivered_before_recovery, [])
            self.assertEqual(delivered_after_recovery, [recovered])
            self.assertEqual(recovered.read_bytes(), payload)
            self.assertTrue(is_valid_pdf(recovered))
            self.assertFalse(list(destination.glob(".pdf_snapshot_*.tmp")))

    def test_pdf_publish_lock_has_a_bounded_timeout(self) -> None:
        import paper_automation.batch_workflow as workflow

        context = multiprocessing.get_context("spawn")
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source.pdf"
            source.write_bytes(b"%PDF-1.7\npublish lock timeout payload")
            destination = root / "pdfs"
            publish_reached = context.Event()
            release_publish = context.Event()
            phase_queue = context.Queue()
            result_queue = context.Queue()
            worker = context.Process(
                target=_controlled_copy_pdf_worker,
                args=(
                    source,
                    destination,
                    "paper.pdf",
                    publish_reached,
                    release_publish,
                    phase_queue,
                    result_queue,
                ),
            )
            worker.start()
            try:
                self.assertTrue(publish_reached.wait(10.0))
                self.assertEqual(phase_queue.get(timeout=5.0), "hard_link")
                with self.assertRaisesRegex(TimeoutError, "pdf_publish_lock_timeout"):
                    workflow.copy_pdf_safely(
                        source,
                        destination,
                        "paper.pdf",
                        lock_timeout=0.1,
                    )
            finally:
                release_publish.set()
                self._join_workers(worker)

            self.assertEqual(result_queue.get(timeout=5.0)[0], "ok")

    def test_hard_link_publish_failure_never_exposes_a_formal_pdf(self) -> None:
        import paper_automation.batch_workflow as workflow

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source.pdf"
            source.write_bytes(b"%PDF-1.7\nhard link failure payload")
            destination = root / "pdfs"

            with patch.object(
                os,
                "link",
                side_effect=OSError("synthetic hard-link failure"),
            ):
                with self.assertRaisesRegex(OSError, "hard_link_publish_failed"):
                    workflow.copy_pdf_safely(source, destination, "paper.pdf")

            self.assertFalse(list(destination.glob("*.pdf")))
            self.assertFalse(list(destination.glob(".pdf_snapshot_*.tmp")))

    def test_copy_rejects_absolute_and_traversal_filenames(self) -> None:
        from paper_automation.batch_workflow import copy_pdf_safely

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source.pdf"
            source.write_bytes(b"%PDF-1.7\nvalid payload")
            destination = root / "pdfs"
            (destination / "nested").mkdir(parents=True)
            invalid_names = [
                str(root / "outside.pdf"),
                "../outside.pdf",
                r"..\outside.pdf",
                "nested/paper.pdf",
                r"nested\paper.pdf",
            ]

            for filename in invalid_names:
                with self.subTest(filename=filename):
                    with self.assertRaisesRegex(ValueError, "invalid_filename"):
                        copy_pdf_safely(source, destination, filename)

    def test_copy_rejects_superscript_windows_device_filenames(self) -> None:
        from paper_automation.batch_workflow import copy_pdf_safely

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source.pdf"
            source.write_bytes(b"%PDF-1.7\nvalid payload")
            destination = root / "pdfs"

            for reserved in ("COM¹", "COM²", "COM³", "LPT¹", "LPT²", "LPT³"):
                filename = f"{reserved}.pdf"
                with self.subTest(filename=filename):
                    try:
                        copy_pdf_safely(source, destination, filename)
                    except Exception as exc:
                        self.assertIsInstance(exc, ValueError)
                        self.assertRegex(str(exc), "invalid_filename")
                    else:
                        self.fail("reserved Windows device filename was accepted")

    def test_different_pdf_content_uses_hash_suffix_without_overwriting(self) -> None:
        from paper_automation.batch_workflow import copy_pdf_safely

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            first_source = root / "first.pdf"
            second_source = root / "second.pdf"
            first_payload = b"%PDF-1.7\nfirst payload"
            second_payload = b"%PDF-1.7\nsecond payload"
            first_source.write_bytes(first_payload)
            second_source.write_bytes(second_payload)
            destination = root / "pdfs"

            first = copy_pdf_safely(first_source, destination, "paper.pdf")
            second = copy_pdf_safely(second_source, destination, "paper.pdf")

            short_hash = hashlib.sha256(second_payload).hexdigest()[:8]
            self.assertEqual(first.name, "paper.pdf")
            self.assertEqual(second.name, f"paper_{short_hash}.pdf")
            self.assertEqual(first.read_bytes(), first_payload)
            self.assertEqual(second.read_bytes(), second_payload)

    def test_different_pdf_content_concurrent_copies_publish_unique_targets(self) -> None:
        from paper_automation.batch_workflow import is_valid_pdf

        context = multiprocessing.get_context("spawn")
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            sources = [root / "first.pdf", root / "second.pdf"]
            payloads = [
                b"%PDF-1.7\nconcurrent first payload",
                b"%PDF-1.7\nconcurrent second payload",
            ]
            for source, payload in zip(sources, payloads):
                source.write_bytes(payload)
            destination = root / "pdfs"
            start = context.Event()
            result_queue = context.Queue()
            started_events = [context.Event(), context.Event()]
            workers = [
                context.Process(
                    target=_copy_pdf_worker,
                    args=(
                        source,
                        destination,
                        "paper.pdf",
                        start,
                        started,
                        result_queue,
                    ),
                )
                for source, started in zip(sources, started_events)
            ]
            for worker in workers:
                worker.start()
            start.set()
            try:
                self.assertTrue(all(event.wait(10.0) for event in started_events))
                results = [result_queue.get(timeout=15.0) for _ in workers]
            finally:
                self._join_workers(*workers)

            self.assertEqual([result[0] for result in results], ["ok", "ok"], results)
            copied_paths = {Path(result[1]) for result in results}
            self.assertEqual(len(copied_paths), 2)
            self.assertEqual({path.read_bytes() for path in copied_paths}, set(payloads))
            self.assertTrue(all(is_valid_pdf(path) for path in copied_paths))
            self.assertEqual(set(destination.glob("*.pdf")), copied_paths)

    def test_occupied_hash_candidate_gets_numeric_suffix_without_overwriting(self) -> None:
        from paper_automation.batch_workflow import copy_pdf_safely

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source.pdf"
            source_payload = b"%PDF-1.7\nnew source payload"
            requested_payload = b"%PDF-1.7\nrequested target payload"
            occupied_payload = b"%PDF-1.7\noccupied hash payload"
            source.write_bytes(source_payload)
            destination = root / "pdfs"
            destination.mkdir()
            requested = destination / "paper.pdf"
            requested.write_bytes(requested_payload)
            short_hash = hashlib.sha256(source_payload).hexdigest()[:8]
            occupied = destination / f"paper_{short_hash}.pdf"
            occupied.write_bytes(occupied_payload)

            copied = copy_pdf_safely(source, destination, "paper.pdf")

            self.assertEqual(copied.name, f"paper_{short_hash}_2.pdf")
            self.assertEqual(requested.read_bytes(), requested_payload)
            self.assertEqual(occupied.read_bytes(), occupied_payload)
            self.assertEqual(copied.read_bytes(), source_payload)

    def test_copy_uses_verified_snapshot_if_source_changes_after_first_read(self) -> None:
        import paper_automation.batch_workflow as workflow

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source.pdf"
            source_payload = b"%PDF-1.7\nstable snapshot payload"
            source.write_bytes(source_payload)
            destination = root / "pdfs"
            destination.mkdir()
            (destination / "paper.pdf").write_bytes(b"%PDF-1.7\nexisting target")
            expected_hash = hashlib.sha256(source_payload).hexdigest()[:8]
            original_copyfileobj = shutil.copyfileobj
            original_link = os.link
            mutation_seen = False

            def mutate_original_once():
                nonlocal mutation_seen
                if not mutation_seen:
                    source.write_bytes(b"")
                    mutation_seen = True

            def mutate_original_then_copy(source_handle, target_handle, length=0):
                mutate_original_once()
                return original_copyfileobj(source_handle, target_handle, length)

            def mutate_original_then_link(source_path, target_path, *args, **kwargs):
                mutate_original_once()
                return original_link(source_path, target_path, *args, **kwargs)

            with patch.object(
                shutil,
                "copyfileobj",
                side_effect=mutate_original_then_copy,
            ), patch.object(os, "link", side_effect=mutate_original_then_link):
                copied = workflow.copy_pdf_safely(source, destination, "paper.pdf")

            self.assertTrue(mutation_seen)
            self.assertEqual(copied.name, f"paper_{expected_hash}.pdf")
            self.assertEqual(copied.read_bytes(), source_payload)
            self.assertTrue(workflow.is_valid_pdf(copied))
            self.assertFalse(list(destination.glob(".pdf_snapshot_*.tmp")))

    def test_non_pdf_is_rejected(self) -> None:
        from paper_automation.batch_workflow import copy_pdf_safely

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "login.pdf"
            source.write_text("<html>login</html>", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "not_pdf_response"):
                copy_pdf_safely(source, root / "pdfs", "paper.pdf")
            self.assertFalse(list((root / "pdfs").glob(".pdf_snapshot_*.tmp")))
