from __future__ import annotations

import errno
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

    def test_batch_state_lock_rejects_negative_and_non_finite_timeouts(self) -> None:
        import paper_automation.batch_workflow as workflow

        with tempfile.TemporaryDirectory() as tmp:
            paths = workflow.create_batch_paths(Path(tmp))
            for timeout in (-1.0, float("nan"), float("inf"), float("-inf")):
                with self.subTest(timeout=timeout):
                    with self.assertRaisesRegex(
                        ValueError,
                        "invalid_batch_state_lock_timeout",
                    ):
                        with workflow.batch_state_lock(paths.root, timeout=timeout):
                            self.fail("invalid timeout acquired the state lock")

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

    def test_same_pdf_content_logic_never_reuses_a_symlink(self) -> None:
        import paper_automation.batch_workflow as workflow

        with tempfile.TemporaryDirectory() as tmp:
            pdf = Path(tmp) / "paper.pdf"
            payload = b"%PDF-1.7\nlogic symlink payload"
            pdf.write_bytes(payload)
            expected_hash = hashlib.sha256(payload).hexdigest()

            with patch.object(Path, "is_symlink", return_value=True):
                reusable = workflow._same_pdf_content(pdf, expected_hash)

            self.assertFalse(reusable)

    def test_copy_treats_real_symlinks_as_occupied_and_publishes_independent_pdf(
        self,
    ) -> None:
        import paper_automation.batch_workflow as workflow

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source.pdf"
            payload = b"%PDF-1.7\nreal symlink payload"
            source.write_bytes(payload)
            destination = root / "pdfs"
            destination.mkdir()
            short_hash = hashlib.sha256(payload).hexdigest()[:8]
            target = destination / "paper.pdf"
            hash_candidate = destination / f"paper_{short_hash}.pdf"
            try:
                target.symlink_to(source)
                hash_candidate.symlink_to(source)
            except (OSError, NotImplementedError) as exc:
                permission_error = (
                    isinstance(exc, PermissionError)
                    or getattr(exc, "errno", None) in {errno.EACCES, errno.EPERM}
                    or getattr(exc, "winerror", None) in {5, 1314}
                )
                if permission_error or isinstance(exc, NotImplementedError):
                    self.skipTest(f"file symlinks unavailable: {exc}")
                raise

            copied = workflow.copy_pdf_safely(source, destination, "paper.pdf")

            self.assertEqual(copied.name, f"paper_{short_hash}_2.pdf")
            self.assertTrue(target.is_symlink())
            self.assertTrue(hash_candidate.is_symlink())
            self.assertFalse(copied.is_symlink())
            self.assertFalse(os.path.samefile(source, copied))
            self.assertEqual(copied.read_bytes(), payload)
            self.assertTrue(workflow.is_valid_pdf(copied))

            source.write_bytes(b"%PDF-1.7\nsource changed later")
            self.assertEqual(copied.read_bytes(), payload)

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

    def test_copy_rejects_negative_and_non_finite_lock_timeouts(self) -> None:
        import paper_automation.batch_workflow as workflow

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source.pdf"
            source.write_bytes(b"%PDF-1.7\ninvalid timeout payload")
            destination = root / "pdfs"

            for index, timeout in enumerate(
                (-1.0, float("nan"), float("inf"), float("-inf")),
                start=1,
            ):
                with self.subTest(timeout=timeout):
                    with self.assertRaisesRegex(
                        ValueError,
                        "invalid_pdf_publish_lock_timeout",
                    ):
                        workflow.copy_pdf_safely(
                            source,
                            destination,
                            f"paper_{index}.pdf",
                            lock_timeout=timeout,
                        )

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


class BatchStageTests(unittest.TestCase):
    def test_stage_result_keeps_normalized_fields(self) -> None:
        from paper_automation.batch_stages import StageResult

        result = StageResult(
            task_id="paper-0001",
            doi="10.1016/example",
            title="Example",
            status="downloaded",
            file="paper.pdf",
            reason="",
            source="oa",
        )

        self.assertEqual(result.source, "oa")
        self.assertEqual(result.task_id, "paper-0001")

    def test_route_splits_sciencedirect_from_other_publishers(self) -> None:
        from paper_automation.batch_stages import split_institutional_rows

        rows = [
            {"task_id": "paper-0001", "doi": "10.1016/j.actamat.2024.1"},
            {"task_id": "paper-0002", "doi": "10.1038/s41467-020-1"},
            {"task_id": "paper-0003", "doi": ""},
        ]

        science_direct, other = split_institutional_rows(rows)

        self.assertEqual([row["task_id"] for row in science_direct], ["paper-0001"])
        self.assertEqual([row["task_id"] for row in other], ["paper-0002", "paper-0003"])

    def test_manual_retry_statuses_are_explicit(self) -> None:
        from paper_automation.batch_stages import needs_manual_retry

        self.assertTrue(needs_manual_retry("auth_required", ""))
        self.assertTrue(needs_manual_retry("failed", "captcha_required"))
        self.assertTrue(needs_manual_retry("failed", "turnstile_detected"))
        self.assertTrue(needs_manual_retry("failed", "institutional login required"))
        self.assertFalse(needs_manual_retry("unsupported_publisher", ""))

    def test_write_stage_input_preserves_rows_as_utf8_sig_csv(self) -> None:
        import csv

        from paper_automation.batch_stages import write_stage_input

        with tempfile.TemporaryDirectory() as tmp:
            path = write_stage_input(
                [{"task_id": "paper-0001", "doi": "10.1016/a", "title": "中文标题"}],
                Path(tmp) / "working" / "input.csv",
            )

            self.assertTrue(path.read_bytes().startswith(b"\xef\xbb\xbf"))
            with path.open("r", newline="", encoding="utf-8-sig") as handle:
                rows = list(csv.DictReader(handle))

        self.assertEqual(rows, [{"task_id": "paper-0001", "doi": "10.1016/a", "title": "中文标题", "authors": "", "journal": "", "year": ""}])

    def test_multi_doi_stage_row_is_explicit_failure_and_never_sent_downstream(self) -> None:
        from types import SimpleNamespace

        from paper_automation.batch_stages import (
            BatchOptions,
            run_non_elsevier_stage,
            run_oa_stage,
            run_sciencedirect_stage,
            write_stage_input,
        )
        from paper_automation.parser import parse_mixed_text

        row = {
            "task_id": "paper-0001",
            "doi": "10.1016/first 10.1038/second",
            "title": "One source row with two DOI values",
        }
        parsed = parse_mixed_text(row["doi"])
        self.assertEqual([candidate.doi for candidate in parsed], ["10.1016/first", "10.1038/second"])
        self.assertEqual([candidate.source_index for candidate in parsed], [1, 1])

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with patch(
                "paper_automation.batch_stages.run_workflow",
                return_value=SimpleNamespace(manifest_csv="", output_dir=""),
            ) as oa_lower:
                oa_results = run_oa_stage([row], root / "oa-output", BatchOptions())

            input_path = write_stage_input([row], root / "input.csv")
            with patch("paper_automation.batch_stages.sd_main", return_value=0) as sd_lower:
                sd_results = run_sciencedirect_stage(input_path, root / "sd-output", BatchOptions())
            with patch(
                "paper_automation.batch_stages.run_institutional_workflow",
                return_value=SimpleNamespace(report_path=""),
            ) as institutional_lower:
                institutional_results = run_non_elsevier_stage(
                    input_path,
                    root / "institutional-output",
                    BatchOptions(),
                )

        for source, results in (
            ("oa", oa_results),
            ("sciencedirect", sd_results),
            ("non_elsevier", institutional_results),
        ):
            with self.subTest(source=source):
                self.assertEqual(len(results), 1)
                self.assertEqual(results[0].task_id, "paper-0001")
                self.assertEqual(results[0].status, "failed")
                self.assertEqual(results[0].reason, "multiple_dois_in_stage_input")
                self.assertEqual(results[0].source, source)

        oa_lower.assert_not_called()
        sd_lower.assert_not_called()
        institutional_lower.assert_not_called()

    def test_multi_doi_failure_preserves_owner_and_duplicate_layout(self) -> None:
        import csv
        from types import SimpleNamespace

        from paper_automation.batch_stages import BatchOptions, run_oa_stage

        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp) / "oa_run"
            valid_pdf = run_dir / "pdfs" / "owner.pdf"
            valid_pdf.parent.mkdir(parents=True)
            valid_pdf.write_bytes(b"%PDF-1.7\nowner fixture")
            manifest = run_dir / "metadata" / "manifest.csv"
            manifest.parent.mkdir(parents=True)
            received_lines: list[str] = []

            def fake_workflow(input_text: str, *args, **kwargs):
                received_lines.extend(input_text.splitlines())
                with manifest.open("w", newline="", encoding="utf-8-sig") as handle:
                    writer = csv.DictWriter(handle, fieldnames=["source_index", "doi", "title", "download_status", "file", "reason"])
                    writer.writeheader()
                    writer.writerow({"source_index": "1", "doi": "10.1000/owner", "title": "Owner", "download_status": "downloaded", "file": "owner.pdf"})
                return SimpleNamespace(manifest_csv=str(manifest), output_dir=str(run_dir))

            with patch("paper_automation.batch_stages.run_workflow", side_effect=fake_workflow):
                results = run_oa_stage(
                    [
                        {"task_id": "paper-0001", "doi": "10.1000/first 10.1000/second", "title": "Multi"},
                        {"task_id": "paper-0002", "doi": "10.1000/owner", "title": "Owner"},
                        {"task_id": "paper-0003", "doi": "https://doi.org/10.1000/OWNER", "title": "Duplicate"},
                    ],
                    run_dir.parent,
                    BatchOptions(),
                )

        self.assertEqual(received_lines, ["10.1000/owner"])
        self.assertEqual([result.task_id for result in results], ["paper-0001", "paper-0002", "paper-0003"])
        self.assertEqual([result.status for result in results], ["failed", "downloaded", "duplicate"])
        self.assertEqual(results[0].reason, "multiple_dois_in_stage_input")
        self.assertEqual(results[2].reason, "duplicate_stage_input")

    def test_oa_adapter_maps_manifest_rows_in_input_order(self) -> None:
        import csv
        from types import SimpleNamespace

        from paper_automation.batch_stages import BatchOptions, run_oa_stage

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            run_dir = root / "oa_run"
            valid_pdf = run_dir / "pdfs" / "oa.pdf"
            valid_pdf.parent.mkdir(parents=True)
            valid_pdf.write_bytes(b"%PDF-1.7\nvalid fixture")
            manifest = run_dir / "metadata" / "final_manifest.csv"
            manifest.parent.mkdir(parents=True)
            with manifest.open("w", newline="", encoding="utf-8-sig") as handle:
                writer = csv.DictWriter(handle, fieldnames=["source_index", "doi", "title", "download_status", "file", "reason"])
                writer.writeheader()
                writer.writerow({"source_index": "2", "doi": "10.1000/b", "title": "Resolved metadata B", "download_status": "failed", "reason": "no_legal_open_pdf"})
                writer.writerow({"source_index": "1", "doi": "10.1000/a", "title": "Resolved metadata A", "download_status": "downloaded", "file": "oa.pdf"})

            with patch(
                "paper_automation.batch_stages.run_workflow",
                return_value=SimpleNamespace(manifest_csv=str(manifest), output_dir=str(run_dir)),
            ) as mocked:
                results = run_oa_stage(
                    [
                        {"task_id": "paper-0001", "doi": "https://doi.org/10.1000/a", "title": "Original title A"},
                        {"task_id": "paper-0002", "doi": "https://doi.org/10.1000/b", "title": "Original title B"},
                    ],
                    root,
                    BatchOptions(email="researcher@example.edu"),
                )

        self.assertEqual([result.task_id for result in results], ["paper-0001", "paper-0002"])
        self.assertEqual([result.status for result in results], ["downloaded", "failed"])
        self.assertEqual([result.doi for result in results], ["10.1000/a", "10.1000/b"])
        self.assertEqual([result.title for result in results], ["Resolved metadata A", "Resolved metadata B"])
        self.assertEqual(results[0].file, str(valid_pdf.resolve()))
        self.assertEqual(results[1].reason, "no_legal_open_pdf")
        self.assertEqual(mocked.call_args.kwargs["email"], "researcher@example.edu")

    def test_oa_relative_pdf_falls_back_to_manifest_run_directory(self) -> None:
        import csv
        from types import SimpleNamespace

        from paper_automation.batch_stages import BatchOptions, run_oa_stage

        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp) / "oa_run"
            valid_pdf = run_dir / "pdfs" / "fallback.pdf"
            valid_pdf.parent.mkdir(parents=True)
            valid_pdf.write_bytes(b"%PDF-1.7\nfallback fixture")
            manifest = run_dir / "metadata" / "final_manifest.csv"
            manifest.parent.mkdir(parents=True)
            with manifest.open("w", newline="", encoding="utf-8-sig") as handle:
                writer = csv.DictWriter(handle, fieldnames=["source_index", "doi", "title", "download_status", "file", "reason"])
                writer.writeheader()
                writer.writerow({"source_index": "1", "doi": "10.1000/a", "title": "A", "download_status": "downloaded", "file": "fallback.pdf"})

            with patch(
                "paper_automation.batch_stages.run_workflow",
                return_value=SimpleNamespace(manifest_csv=str(manifest), output_dir=None),
            ):
                results = run_oa_stage(
                    [{"task_id": "paper-0001", "doi": "10.1000/a", "title": "A"}],
                    run_dir.parent,
                    BatchOptions(),
                )

        self.assertEqual(results[0].status, "downloaded")
        self.assertEqual(results[0].file, str(valid_pdf.resolve()))

    def test_oa_adapter_falls_back_to_clean_doi_and_normalized_title(self) -> None:
        import csv
        from types import SimpleNamespace

        from paper_automation.batch_stages import BatchOptions, run_oa_stage

        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp) / "oa_run"
            manifest = run_dir / "metadata" / "final_manifest.csv"
            manifest.parent.mkdir(parents=True)
            with manifest.open("w", newline="", encoding="utf-8-sig") as handle:
                writer = csv.DictWriter(handle, fieldnames=["source_index", "doi", "title", "download_status", "file", "reason"])
                writer.writeheader()
                writer.writerow({"doi": "10.1000/url", "title": "Resolved URL title", "download_status": "failed", "reason": "no_legal_open_pdf"})
                writer.writerow({"doi": "", "title": "Normalized   Title", "download_status": "needs_review", "reason": "title_only"})

            with patch(
                "paper_automation.batch_stages.run_workflow",
                return_value=SimpleNamespace(manifest_csv=str(manifest), output_dir=str(run_dir)),
            ):
                results = run_oa_stage(
                    [
                        {"task_id": "paper-0001", "doi": "https://doi.org/10.1000/url", "title": "Original URL title"},
                        {"task_id": "paper-0002", "doi": "", "title": " normalized title "},
                    ],
                    run_dir.parent,
                    BatchOptions(),
                )

        self.assertEqual([result.task_id for result in results], ["paper-0001", "paper-0002"])
        self.assertEqual([result.reason for result in results], ["no_legal_open_pdf", "title_only"])

    def test_oa_source_index_ignores_empty_stage_lines(self) -> None:
        import csv
        from types import SimpleNamespace

        from paper_automation.batch_stages import BatchOptions, run_oa_stage

        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp) / "oa_run"
            valid_pdf = run_dir / "pdfs" / "after-empty.pdf"
            valid_pdf.parent.mkdir(parents=True)
            valid_pdf.write_bytes(b"%PDF-1.7\nafter empty fixture")
            manifest = run_dir / "metadata" / "final_manifest.csv"
            manifest.parent.mkdir(parents=True)
            with manifest.open("w", newline="", encoding="utf-8-sig") as handle:
                writer = csv.DictWriter(handle, fieldnames=["source_index", "doi", "title", "download_status", "file", "reason"])
                writer.writeheader()
                writer.writerow({"source_index": "1", "doi": "10.1000/after-empty", "title": "Resolved", "download_status": "downloaded", "file": "after-empty.pdf"})

            with patch(
                "paper_automation.batch_stages.run_workflow",
                return_value=SimpleNamespace(manifest_csv=str(manifest), output_dir=str(run_dir)),
            ) as mocked:
                results = run_oa_stage(
                    [
                        {"task_id": "paper-0001", "doi": "", "title": ""},
                        {"task_id": "paper-0002", "doi": "10.1000/after-empty", "title": "Original"},
                    ],
                    run_dir.parent,
                    BatchOptions(),
                )

        self.assertEqual(mocked.call_args.args[0], "10.1000/after-empty")
        self.assertEqual([result.task_id for result in results], ["paper-0001", "paper-0002"])
        self.assertEqual(results[0].reason, "missing_stage_report_row")
        self.assertEqual(results[1].status, "downloaded")
        self.assertEqual(results[1].file, str(valid_pdf.resolve()))

    def test_oa_missing_manifest_path_values_are_safe_failures(self) -> None:
        from types import SimpleNamespace

        from paper_automation.batch_stages import BatchOptions, run_oa_stage

        variants = {
            "none": SimpleNamespace(manifest_csv=None, output_dir=""),
            "empty": SimpleNamespace(manifest_csv="", output_dir=""),
            "missing_attribute": SimpleNamespace(output_dir=""),
        }
        for name, workflow_result in variants.items():
            with self.subTest(name=name), tempfile.TemporaryDirectory() as tmp, patch(
                "paper_automation.batch_stages.run_workflow",
                return_value=workflow_result,
            ):
                caught = None
                try:
                    results = run_oa_stage(
                        [{"task_id": "paper-0001", "doi": "10.1000/a", "title": "A"}],
                        Path(tmp),
                        BatchOptions(),
                    )
                except Exception as exc:
                    caught = exc
                    results = []

                self.assertIsNone(caught, f"unexpected {type(caught).__name__}: {caught}")
                self.assertEqual(results[0].status, "failed")
                self.assertEqual(results[0].reason, "stage_report_missing")

    def test_sciencedirect_adapter_maps_success_auth_and_cli_options(self) -> None:
        import csv

        from paper_automation.batch_stages import BatchOptions, run_sciencedirect_stage, write_stage_input

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            valid_pdf = root / "sciencedirect" / "pdfs" / "download.pdf"
            valid_pdf.parent.mkdir(parents=True)
            valid_pdf.write_bytes(b"%PDF-1.7\nfixture")
            input_path = write_stage_input(
                [
                    {"task_id": "paper-0001", "doi": "10.1016/a", "title": "A"},
                    {"task_id": "paper-0002", "doi": "10.1016/b", "title": "B"},
                ],
                root / "input.csv",
            )

            def fake_sd_main(argv: list[str]) -> int:
                report_dir = Path(argv[argv.index("--out") + 1]) / "sciencedirect"
                report_dir.mkdir(parents=True, exist_ok=True)
                with (report_dir / "pdf_download_report.csv").open("w", newline="", encoding="utf-8-sig") as handle:
                    fields = ["doi", "pii", "title", "status", "file", "reason", "manual_pdf_url", "manual_status", "manual_reason"]
                    writer = csv.DictWriter(handle, fieldnames=fields)
                    writer.writeheader()
                    writer.writerow({"doi": "10.1016/a", "title": "A", "status": "success", "file": "download.pdf"})
                    writer.writerow({"doi": "10.1016/b", "title": "B", "status": "failed", "reason": "auth_required"})
                return 0

            with patch("paper_automation.batch_stages.sd_main", side_effect=fake_sd_main) as mocked:
                results = run_sciencedirect_stage(
                    input_path,
                    root,
                    BatchOptions(
                        email="researcher@example.edu",
                        cookies="cookies.json",
                        browser_exe="C:/Browser/browser.exe",
                        login_wait_seconds=30,
                    ),
                )

        argv = mocked.call_args.args[0]
        self.assertEqual([result.task_id for result in results], ["paper-0001", "paper-0002"])
        self.assertEqual(results[0].status, "downloaded")
        self.assertEqual(results[0].file, str(valid_pdf.resolve()))
        self.assertEqual(results[1].reason, "auth_required")
        self.assertIn("--run-name", argv)
        self.assertEqual(argv[argv.index("--run-name") + 1], "sciencedirect")
        self.assertIn("--no-download-supplements", argv)
        self.assertEqual(argv[argv.index("--cookies") + 1], "cookies.json")
        self.assertEqual(argv[argv.index("--browser-exe") + 1], "C:/Browser/browser.exe")
        self.assertEqual(argv[argv.index("--login-wait-seconds") + 1], "30")

    def test_sciencedirect_adapter_rejects_invalid_pdf_and_missing_stage_rows(self) -> None:
        import csv

        from paper_automation.batch_stages import BatchOptions, run_sciencedirect_stage, write_stage_input

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            invalid_pdf = root / "login.pdf"
            invalid_pdf.write_text("<html>login</html>", encoding="utf-8")
            input_path = write_stage_input(
                [
                    {"task_id": "paper-0001", "doi": "10.1016/a", "title": "A"},
                    {"task_id": "paper-0002", "doi": "10.1016/b", "title": "B"},
                ],
                root / "input.csv",
            )

            def fake_sd_main(argv: list[str]) -> int:
                report_dir = Path(argv[argv.index("--out") + 1]) / "sciencedirect"
                report_dir.mkdir(parents=True, exist_ok=True)
                with (report_dir / "pdf_download_report.csv").open("w", newline="", encoding="utf-8-sig") as handle:
                    fields = ["doi", "pii", "title", "status", "file", "reason", "manual_pdf_url", "manual_status", "manual_reason"]
                    writer = csv.DictWriter(handle, fieldnames=fields)
                    writer.writeheader()
                    writer.writerow({"doi": "10.1016/a", "title": "A", "status": "success", "file": str(invalid_pdf)})
                return 0

            with patch("paper_automation.batch_stages.sd_main", side_effect=fake_sd_main):
                results = run_sciencedirect_stage(input_path, root, BatchOptions())

        self.assertEqual(results[0].status, "failed")
        self.assertEqual(results[0].reason, "invalid_pdf")
        self.assertEqual(results[1].status, "failed")
        self.assertEqual(results[1].reason, "missing_stage_report_row")

    def test_sciencedirect_adapter_reports_nonzero_exit_without_report(self) -> None:
        from paper_automation.batch_stages import BatchOptions, run_sciencedirect_stage, write_stage_input

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            input_path = write_stage_input(
                [{"task_id": "paper-0001", "doi": "10.1016/a", "title": "A"}],
                root / "input.csv",
            )
            with patch("paper_automation.batch_stages.sd_main", return_value=3):
                results = run_sciencedirect_stage(input_path, root, BatchOptions())

        self.assertEqual(results[0].status, "failed")
        self.assertEqual(results[0].reason, "stage_exit_code_3")

    def test_sciencedirect_nonzero_exit_preserves_reported_rows(self) -> None:
        import csv

        from paper_automation.batch_stages import BatchOptions, run_sciencedirect_stage, write_stage_input

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            valid_pdf = root / "sciencedirect" / "pdfs" / "partial.pdf"
            valid_pdf.parent.mkdir(parents=True)
            valid_pdf.write_bytes(b"%PDF-1.7\npartial fixture")
            input_path = write_stage_input(
                [
                    {"task_id": "paper-0001", "doi": "10.1016/a", "title": "A"},
                    {"task_id": "paper-0002", "doi": "10.1016/b", "title": "B"},
                ],
                root / "input.csv",
            )

            def fake_sd_main(argv: list[str]) -> int:
                report_dir = Path(argv[argv.index("--out") + 1]) / "sciencedirect"
                with (report_dir / "pdf_download_report.csv").open("w", newline="", encoding="utf-8-sig") as handle:
                    fields = ["doi", "pii", "title", "status", "file", "reason", "manual_pdf_url", "manual_status", "manual_reason"]
                    writer = csv.DictWriter(handle, fieldnames=fields)
                    writer.writeheader()
                    writer.writerow({"doi": "10.1016/a", "title": "A", "status": "success", "file": "partial.pdf"})
                return 7

            with patch("paper_automation.batch_stages.sd_main", side_effect=fake_sd_main):
                results = run_sciencedirect_stage(input_path, root, BatchOptions())

        self.assertEqual([result.task_id for result in results], ["paper-0001", "paper-0002"])
        self.assertEqual(results[0].status, "downloaded")
        self.assertEqual(results[0].file, str(valid_pdf.resolve()))
        self.assertEqual(results[1].status, "failed")
        self.assertEqual(results[1].reason, "stage_exit_code_7")

    def test_sciencedirect_adapter_reports_missing_report(self) -> None:
        from paper_automation.batch_stages import BatchOptions, run_sciencedirect_stage, write_stage_input

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            input_path = write_stage_input(
                [{"task_id": "paper-0001", "doi": "10.1016/a", "title": "A"}],
                root / "input.csv",
            )
            with patch("paper_automation.batch_stages.sd_main", return_value=0):
                results = run_sciencedirect_stage(input_path, root, BatchOptions())

        self.assertEqual(results[0].status, "failed")
        self.assertEqual(results[0].reason, "stage_report_missing")

    def test_non_elsevier_adapter_maps_report_and_options(self) -> None:
        import csv
        from types import SimpleNamespace

        from paper_automation.batch_stages import BatchOptions, run_non_elsevier_stage, write_stage_input

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            valid_pdf = root / "non_elsevier_institutional" / "pdfs" / "institutional.pdf"
            valid_pdf.parent.mkdir(parents=True)
            valid_pdf.write_bytes(b"%PDF-1.7\ninstitutional fixture")
            input_path = write_stage_input(
                [
                    {"task_id": "paper-0001", "doi": "10.1038/a", "title": "A"},
                    {"task_id": "paper-0002", "doi": "", "title": "Unknown"},
                ],
                root / "input.csv",
            )

            def fake_workflow(*args, **kwargs):
                report = root / "non_elsevier_institutional" / "institutional_pdf_download_report.csv"
                report.parent.mkdir(parents=True, exist_ok=True)
                with report.open("w", newline="", encoding="utf-8-sig") as handle:
                    fields = ["row_number", "doi", "title", "journal", "year", "publisher", "adapter", "status", "file", "reason", "landing_url", "final_landing_url", "pdf_url", "metadata_source"]
                    writer = csv.DictWriter(handle, fieldnames=fields)
                    writer.writeheader()
                    writer.writerow({"row_number": "2", "doi": "", "title": "Unknown", "status": "unsupported_publisher", "reason": "no_supported_adapter"})
                    writer.writerow({"row_number": "1", "doi": "10.1038/a", "title": "A", "status": "pdf_downloaded", "file": "institutional.pdf"})
                return SimpleNamespace(report_path=str(report))

            with patch("paper_automation.batch_stages.run_institutional_workflow", side_effect=fake_workflow) as mocked:
                results = run_non_elsevier_stage(
                    input_path,
                    root,
                    BatchOptions(browser_exe="C:/Browser/browser.exe", debug_port=9444, login_wait_seconds=20, throttle_seconds=0.0),
                )

        self.assertEqual([result.task_id for result in results], ["paper-0001", "paper-0002"])
        self.assertEqual([result.status for result in results], ["downloaded", "unsupported_publisher"])
        self.assertEqual(results[0].file, str(valid_pdf.resolve()))
        self.assertEqual(results[1].reason, "no_supported_adapter")
        self.assertEqual(mocked.call_args.kwargs["browser_exe"], "C:/Browser/browser.exe")
        self.assertEqual(mocked.call_args.kwargs["debug_port"], 9444)
        self.assertEqual(mocked.call_args.kwargs["login_wait_seconds"], 20)
        self.assertEqual(mocked.call_args.kwargs["throttle_seconds"], 0.0)

    def test_stage_normalizes_absolute_symlink_to_final_pdf_when_supported(self) -> None:
        import csv

        from paper_automation.batch_stages import BatchOptions, run_sciencedirect_stage, write_stage_input

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            external = root / "external.pdf"
            external.write_bytes(b"%PDF-1.7\nexternal fixture")
            linked = root / "linked.pdf"
            try:
                os.symlink(external, linked)
            except OSError as exc:
                self.skipTest(f"symlink_not_available: {exc}")
            input_path = write_stage_input(
                [{"task_id": "paper-0001", "doi": "10.1016/a", "title": "A"}],
                root / "input.csv",
            )

            def fake_sd_main(argv: list[str]) -> int:
                report_dir = Path(argv[argv.index("--out") + 1]) / "sciencedirect"
                report_dir.mkdir(parents=True, exist_ok=True)
                with (report_dir / "pdf_download_report.csv").open("w", newline="", encoding="utf-8-sig") as handle:
                    fields = ["doi", "pii", "title", "status", "file", "reason", "manual_pdf_url", "manual_status", "manual_reason"]
                    writer = csv.DictWriter(handle, fieldnames=fields)
                    writer.writeheader()
                    writer.writerow({"doi": "10.1016/a", "title": "A", "status": "success", "file": str(linked)})
                return 0

            with patch("paper_automation.batch_stages.sd_main", side_effect=fake_sd_main):
                results = run_sciencedirect_stage(input_path, root, BatchOptions())

        self.assertEqual(results[0].status, "downloaded")
        self.assertEqual(results[0].file, str(external.resolve()))

    def test_sciencedirect_relative_pdf_cannot_escape_pdf_directory(self) -> None:
        import csv

        from paper_automation.batch_stages import BatchOptions, run_sciencedirect_stage, write_stage_input

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            report_dir = root / "sciencedirect"
            pdf_dir = report_dir / "pdfs"
            pdf_dir.mkdir(parents=True)
            escaped_pdf = report_dir / "escaped.pdf"
            escaped_pdf.write_bytes(b"%PDF-1.7\nescaped fixture")
            input_path = write_stage_input(
                [{"task_id": "paper-0001", "doi": "10.1016/a", "title": "A"}],
                root / "input.csv",
            )

            def fake_sd_main(argv: list[str]) -> int:
                with (report_dir / "pdf_download_report.csv").open("w", newline="", encoding="utf-8-sig") as handle:
                    fields = ["doi", "pii", "title", "status", "file", "reason", "manual_pdf_url", "manual_status", "manual_reason"]
                    writer = csv.DictWriter(handle, fieldnames=fields)
                    writer.writeheader()
                    writer.writerow({"doi": "10.1016/a", "title": "A", "status": "success", "file": "../escaped.pdf"})
                return 0

            original_cwd = Path.cwd()
            os.chdir(pdf_dir)
            try:
                with patch("paper_automation.batch_stages.sd_main", side_effect=fake_sd_main):
                    results = run_sciencedirect_stage(input_path, root, BatchOptions())
            finally:
                os.chdir(original_cwd)

        self.assertEqual(results[0].status, "failed")
        self.assertEqual(results[0].reason, "invalid_pdf")

    def test_relative_pdf_symlink_is_rejected_before_resolution(self) -> None:
        from paper_automation.batch_stages import _resolve_report_pdf

        with tempfile.TemporaryDirectory() as tmp:
            pdf_dir = Path(tmp) / "pdfs"
            pdf_dir.mkdir()
            linked = pdf_dir / "linked.pdf"
            target = pdf_dir / "target.pdf"
            target.write_bytes(b"%PDF-1.7\ntarget fixture")
            original_resolve = Path.resolve

            def fake_resolve(path: Path, *args, **kwargs) -> Path:
                if path == linked:
                    return target
                return original_resolve(path, *args, **kwargs)

            def fake_is_symlink(path: Path) -> bool:
                return path == linked

            with patch.object(Path, "resolve", autospec=True, side_effect=fake_resolve), patch.object(
                Path,
                "is_symlink",
                autospec=True,
                side_effect=fake_is_symlink,
            ):
                resolved = _resolve_report_pdf("linked.pdf", pdf_dir)

        self.assertIsNone(resolved)

    def test_sciencedirect_absolute_pdf_path_is_canonicalized(self) -> None:
        import csv

        from paper_automation.batch_stages import BatchOptions, run_sciencedirect_stage, write_stage_input

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            valid_pdf = root / "actual" / "absolute.pdf"
            valid_pdf.parent.mkdir()
            valid_pdf.write_bytes(b"%PDF-1.7\nabsolute fixture")
            (root / "alias").mkdir()
            reported_pdf = root / "alias" / ".." / "actual" / "absolute.pdf"
            input_path = write_stage_input(
                [{"task_id": "paper-0001", "doi": "10.1016/a", "title": "A"}],
                root / "input.csv",
            )

            def fake_sd_main(argv: list[str]) -> int:
                report_dir = root / "sciencedirect"
                report_dir.mkdir()
                with (report_dir / "pdf_download_report.csv").open("w", newline="", encoding="utf-8-sig") as handle:
                    fields = ["doi", "pii", "title", "status", "file", "reason", "manual_pdf_url", "manual_status", "manual_reason"]
                    writer = csv.DictWriter(handle, fieldnames=fields)
                    writer.writeheader()
                    writer.writerow({"doi": "10.1016/a", "title": "A", "status": "success", "file": str(reported_pdf)})
                return 0

            with patch("paper_automation.batch_stages.sd_main", side_effect=fake_sd_main):
                results = run_sciencedirect_stage(input_path, root, BatchOptions())

        self.assertEqual(results[0].status, "downloaded")
        self.assertEqual(results[0].file, str(valid_pdf.resolve()))

    def test_absolute_pdf_resolve_returns_final_reparse_target_semantics(self) -> None:
        from paper_automation.batch_stages import _resolve_report_pdf

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            alias_file = root / "junction-alias" / "paper.pdf"
            final_file = root / "real-target" / "paper.pdf"
            final_file.parent.mkdir()
            final_file.write_bytes(b"%PDF-1.7\nreparse target fixture")
            original_resolve = Path.resolve

            def fake_resolve(path: Path, *args, **kwargs) -> Path:
                if path == alias_file:
                    return final_file
                return original_resolve(path, *args, **kwargs)

            with patch.object(Path, "resolve", autospec=True, side_effect=fake_resolve):
                resolved = _resolve_report_pdf(str(alias_file), root / "unused-base")

        self.assertEqual(resolved, final_file)

    @unittest.skipUnless(os.name == "nt", "Windows junction semantics")
    def test_sciencedirect_absolute_junction_path_resolves_to_final_pdf(self) -> None:
        import csv
        import subprocess

        from paper_automation.batch_stages import BatchOptions, run_sciencedirect_stage, write_stage_input

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target_dir = root / "junction-target"
            target_dir.mkdir()
            final_pdf = target_dir / "paper.pdf"
            final_pdf.write_bytes(b"%PDF-1.7\njunction target fixture")
            junction_dir = root / "junction-alias"
            created = subprocess.run(
                ["cmd.exe", "/d", "/c", "mklink", "/J", str(junction_dir), str(target_dir)],
                capture_output=True,
                text=True,
                check=False,
            )
            if created.returncode != 0:
                self.skipTest("current Windows environment cannot create a directory junction")

            try:
                input_path = write_stage_input(
                    [{"task_id": "paper-0001", "doi": "10.1016/a", "title": "A"}],
                    root / "input.csv",
                )

                def fake_sd_main(args: list[str]) -> int:
                    report = root / "sciencedirect" / "pdf_download_report.csv"
                    report.parent.mkdir(parents=True)
                    with report.open("w", newline="", encoding="utf-8-sig") as handle:
                        fields = ["doi", "pii", "title", "status", "file", "reason", "manual_pdf_url", "manual_status", "manual_reason"]
                        writer = csv.DictWriter(handle, fieldnames=fields)
                        writer.writeheader()
                        writer.writerow(
                            {
                                "doi": "10.1016/a",
                                "title": "A",
                                "status": "success",
                                "file": str(junction_dir / "paper.pdf"),
                            }
                        )
                    return 0

                with patch("paper_automation.batch_stages.sd_main", side_effect=fake_sd_main):
                    results = run_sciencedirect_stage(input_path, root, BatchOptions())
            finally:
                if junction_dir.exists():
                    junction_dir.rmdir()

        self.assertEqual(results[0].status, "downloaded")
        self.assertEqual(results[0].file, str(final_pdf.resolve()))

    def test_non_elsevier_adapter_keeps_missing_blank_rows_in_place(self) -> None:
        import csv
        from types import SimpleNamespace

        from paper_automation.batch_stages import BatchOptions, run_non_elsevier_stage, write_stage_input

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            input_path = write_stage_input(
                [{"task_id": "paper-0001"}, {"task_id": "paper-0002"}],
                root / "input.csv",
            )

            def fake_workflow(*args, **kwargs):
                report = root / "non_elsevier_institutional" / "institutional_pdf_download_report.csv"
                report.parent.mkdir(parents=True, exist_ok=True)
                with report.open("w", newline="", encoding="utf-8-sig") as handle:
                    fields = ["row_number", "doi", "title", "journal", "year", "publisher", "adapter", "status", "file", "reason", "landing_url", "final_landing_url", "pdf_url", "metadata_source"]
                    writer = csv.DictWriter(handle, fieldnames=fields)
                    writer.writeheader()
                    writer.writerow({"row_number": "3", "status": "unsupported_publisher", "reason": "no_supported_adapter"})
                    writer.writerow({"row_number": "1", "status": "failed", "reason": "bogus_row_number"})
                return SimpleNamespace(report_path=str(report))

            with patch("paper_automation.batch_stages.run_institutional_workflow", side_effect=fake_workflow):
                results = run_non_elsevier_stage(input_path, root, BatchOptions())

        self.assertEqual([result.task_id for result in results], ["paper-0001", "paper-0002"])
        self.assertEqual(results[0].reason, "missing_stage_report_row")
        self.assertEqual(results[1].status, "unsupported_publisher")

    def test_non_elsevier_missing_report_path_values_are_safe_failures(self) -> None:
        from types import SimpleNamespace

        from paper_automation.batch_stages import BatchOptions, run_non_elsevier_stage, write_stage_input

        variants = {
            "none": SimpleNamespace(report_path=None),
            "empty": SimpleNamespace(report_path=""),
            "missing_attribute": SimpleNamespace(),
        }
        for name, workflow_result in variants.items():
            with self.subTest(name=name), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                input_path = write_stage_input(
                    [{"task_id": "paper-0001", "doi": "10.1038/a", "title": "A"}],
                    root / "input.csv",
                )
                with patch(
                    "paper_automation.batch_stages.run_institutional_workflow",
                    return_value=workflow_result,
                ):
                    caught = None
                    try:
                        results = run_non_elsevier_stage(input_path, root, BatchOptions())
                    except Exception as exc:
                        caught = exc
                        results = []

                self.assertIsNone(caught, f"unexpected {type(caught).__name__}: {caught}")
                self.assertEqual(results[0].status, "failed")
                self.assertEqual(results[0].reason, "stage_report_missing")

    def test_oa_adapter_marks_normalized_duplicate_doi_without_second_download(self) -> None:
        import csv
        from types import SimpleNamespace

        from paper_automation.batch_stages import BatchOptions, run_oa_stage

        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp) / "oa_run"
            valid_pdf = run_dir / "pdfs" / "owner.pdf"
            valid_pdf.parent.mkdir(parents=True)
            valid_pdf.write_bytes(b"%PDF-1.7\nowner fixture")
            manifest = run_dir / "metadata" / "final_manifest.csv"
            manifest.parent.mkdir(parents=True)
            received_lines: list[str] = []

            def fake_workflow(input_text: str, *args, **kwargs):
                received_lines.extend(input_text.splitlines())
                with manifest.open("w", newline="", encoding="utf-8-sig") as handle:
                    writer = csv.DictWriter(handle, fieldnames=["source_index", "doi", "title", "download_status", "file", "reason"])
                    writer.writeheader()
                    writer.writerow({"source_index": "1", "doi": "10.1000/duplicate", "title": "Owner", "download_status": "downloaded", "file": "owner.pdf"})
                return SimpleNamespace(manifest_csv=str(manifest), output_dir=str(run_dir))

            with patch("paper_automation.batch_stages.run_workflow", side_effect=fake_workflow):
                results = run_oa_stage(
                    [
                        {"task_id": "paper-0001", "doi": "https://doi.org/10.1000/duplicate", "title": "Owner"},
                        {"task_id": "paper-0002", "doi": "10.1000/DUPLICATE", "title": "Duplicate"},
                    ],
                    run_dir.parent,
                    BatchOptions(),
                )

        self.assertEqual(received_lines, ["https://doi.org/10.1000/duplicate"])
        self.assertEqual([result.task_id for result in results], ["paper-0001", "paper-0002"])
        self.assertEqual([result.status for result in results], ["downloaded", "duplicate"])
        self.assertEqual(results[1].reason, "duplicate_stage_input")
        self.assertEqual(results[1].source, "oa")
        self.assertEqual(results[1].file, "")

    def test_oa_adapter_marks_normalized_duplicate_title(self) -> None:
        import csv
        from types import SimpleNamespace

        from paper_automation.batch_stages import BatchOptions, run_oa_stage

        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp) / "oa_run"
            manifest = run_dir / "metadata" / "final_manifest.csv"
            manifest.parent.mkdir(parents=True)
            received_lines: list[str] = []

            def fake_workflow(input_text: str, *args, **kwargs):
                received_lines.extend(input_text.splitlines())
                with manifest.open("w", newline="", encoding="utf-8-sig") as handle:
                    writer = csv.DictWriter(handle, fieldnames=["source_index", "doi", "title", "download_status", "file", "reason"])
                    writer.writeheader()
                    writer.writerow({"source_index": "1", "title": "Normalized Title", "download_status": "failed", "reason": "no_legal_open_pdf"})
                return SimpleNamespace(manifest_csv=str(manifest), output_dir=str(run_dir))

            with patch("paper_automation.batch_stages.run_workflow", side_effect=fake_workflow):
                results = run_oa_stage(
                    [
                        {"task_id": "paper-0001", "doi": "", "title": "Normalized   Title"},
                        {"task_id": "paper-0002", "doi": "", "title": " normalized title "},
                    ],
                    run_dir.parent,
                    BatchOptions(),
                )

        self.assertEqual(received_lines, ["Normalized   Title"])
        self.assertEqual([result.status for result in results], ["failed", "duplicate"])
        self.assertEqual(results[1].reason, "duplicate_stage_input")

    def test_sciencedirect_adapter_marks_normalized_duplicate_doi_without_second_download(self) -> None:
        import csv

        from paper_automation.batch_stages import BatchOptions, run_sciencedirect_stage, write_stage_input

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            valid_pdf = root / "sciencedirect" / "pdfs" / "owner.pdf"
            valid_pdf.parent.mkdir(parents=True)
            valid_pdf.write_bytes(b"%PDF-1.7\nowner fixture")
            input_path = write_stage_input(
                [
                    {"task_id": "paper-0001", "doi": "https://doi.org/10.1016/duplicate", "title": "Owner"},
                    {"task_id": "paper-0002", "doi": "10.1016/DUPLICATE", "title": "Duplicate"},
                ],
                root / "input.csv",
            )
            received_task_ids: list[str] = []

            def fake_sd_main(argv: list[str]) -> int:
                with Path(argv[argv.index("--input") + 1]).open("r", newline="", encoding="utf-8-sig") as handle:
                    received_task_ids.extend(row["task_id"] for row in csv.DictReader(handle))
                report = root / "sciencedirect" / "pdf_download_report.csv"
                with report.open("w", newline="", encoding="utf-8-sig") as handle:
                    fields = ["doi", "pii", "title", "status", "file", "reason", "manual_pdf_url", "manual_status", "manual_reason"]
                    writer = csv.DictWriter(handle, fieldnames=fields)
                    writer.writeheader()
                    writer.writerow({"doi": "10.1016/duplicate", "title": "Owner", "status": "success", "file": "owner.pdf"})
                return 0

            with patch("paper_automation.batch_stages.sd_main", side_effect=fake_sd_main):
                results = run_sciencedirect_stage(input_path, root, BatchOptions())

        self.assertEqual(received_task_ids, ["paper-0001"])
        self.assertEqual([result.task_id for result in results], ["paper-0001", "paper-0002"])
        self.assertEqual([result.status for result in results], ["downloaded", "duplicate"])
        self.assertEqual(results[1].reason, "duplicate_stage_input")
        self.assertEqual(results[1].source, "sciencedirect")
        self.assertEqual(results[1].file, "")

    def test_non_elsevier_adapter_marks_normalized_duplicate_doi_without_second_download(self) -> None:
        import csv
        from types import SimpleNamespace

        from paper_automation.batch_stages import BatchOptions, run_non_elsevier_stage, write_stage_input

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            valid_pdf = root / "non_elsevier_institutional" / "pdfs" / "owner.pdf"
            valid_pdf.parent.mkdir(parents=True)
            valid_pdf.write_bytes(b"%PDF-1.7\nowner fixture")
            input_path = write_stage_input(
                [
                    {"task_id": "paper-0001", "doi": "https://doi.org/10.1038/duplicate", "title": "Owner"},
                    {"task_id": "paper-0002", "doi": "10.1038/DUPLICATE", "title": "Duplicate"},
                ],
                root / "input.csv",
            )
            received_task_ids: list[str] = []

            def fake_workflow(*args, **kwargs):
                with Path(kwargs["input_path"]).open("r", newline="", encoding="utf-8-sig") as handle:
                    received_task_ids.extend(row["task_id"] for row in csv.DictReader(handle))
                report = root / "non_elsevier_institutional" / "institutional_pdf_download_report.csv"
                with report.open("w", newline="", encoding="utf-8-sig") as handle:
                    fields = ["row_number", "doi", "title", "journal", "year", "publisher", "adapter", "status", "file", "reason", "landing_url", "final_landing_url", "pdf_url", "metadata_source"]
                    writer = csv.DictWriter(handle, fieldnames=fields)
                    writer.writeheader()
                    writer.writerow({"row_number": "2", "doi": "10.1038/duplicate", "title": "Owner", "status": "pdf_downloaded", "file": "owner.pdf"})
                return SimpleNamespace(report_path=str(report))

            with patch("paper_automation.batch_stages.run_institutional_workflow", side_effect=fake_workflow):
                results = run_non_elsevier_stage(input_path, root, BatchOptions())

        self.assertEqual(received_task_ids, ["paper-0001"])
        self.assertEqual([result.task_id for result in results], ["paper-0001", "paper-0002"])
        self.assertEqual([result.status for result in results], ["downloaded", "duplicate"])
        self.assertEqual(results[1].reason, "duplicate_stage_input")
        self.assertEqual(results[1].source, "non_elsevier")
        self.assertEqual(results[1].file, "")
