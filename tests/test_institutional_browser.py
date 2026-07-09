from __future__ import annotations

import tempfile
import sys
import unittest
from pathlib import Path
from unittest.mock import patch


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


class InstitutionalAdapterTests(unittest.TestCase):
    def test_springer_nature_candidates_include_direct_pdf_routes(self) -> None:
        from paper_automation.institutional.adapters.springer_nature import SpringerNatureAdapter
        from paper_automation.institutional.models import InstitutionalPaper, PageSnapshot

        adapter = SpringerNatureAdapter()
        paper = InstitutionalPaper(
            row_number=1,
            input_doi="10.1007/s10853-017-1978-5",
            doi="10.1007/s10853-017-1978-5",
            title="Springer paper",
            publisher="Springer Nature",
            landing_url="https://link.springer.com/article/10.1007/s10853-017-1978-5",
        )
        snapshot = PageSnapshot(
            requested_url=paper.landing_url,
            final_url=paper.landing_url,
            html='<meta name="citation_pdf_url" content="/content/pdf/10.1007/s10853-017-1978-5.pdf">',
            text="Download PDF",
        )

        urls = [candidate.url for candidate in adapter.build_pdf_candidates(paper, snapshot)]

        self.assertIn("https://link.springer.com/content/pdf/10.1007/s10853-017-1978-5.pdf", urls)

    def test_iucr_candidates_include_meta_and_fallback_routes(self) -> None:
        from paper_automation.institutional.adapters.iucr import IucrAdapter
        from paper_automation.institutional.models import InstitutionalPaper, PageSnapshot

        adapter = IucrAdapter()
        paper = InstitutionalPaper(
            row_number=1,
            input_doi="10.1107/s1600576715004306",
            doi="10.1107/s1600576715004306",
            title="IUCr paper",
            publisher="International Union of Crystallography",
            landing_url="https://journals.iucr.org/j/issues/2015/03/00/ab1234/index.html",
        )
        snapshot = PageSnapshot(
            requested_url=paper.landing_url,
            final_url=paper.landing_url,
            html='<meta name="citation_pdf_url" content="/j/issues/2015/03/00/ab1234/ab1234.pdf">',
            text="Access through your institution",
        )

        urls = [candidate.url for candidate in adapter.build_pdf_candidates(paper, snapshot)]

        self.assertIn(
            "https://journals.iucr.org/j/issues/2015/03/00/ab1234/ab1234.pdf",
            urls,
        )
        self.assertIn(f"{paper.landing_url}/pdf", urls)


class InstitutionalRegistryTests(unittest.TestCase):
    def test_registry_routes_supported_and_known_unsupported_publishers(self) -> None:
        from paper_automation.institutional.models import InstitutionalPaper
        from paper_automation.institutional.registry import select_adapter, unsupported_reason

        supported = InstitutionalPaper(
            row_number=1,
            input_doi="10.1038/s41467-020-16791-8",
            doi="10.1038/s41467-020-16791-8",
            title="Nature paper",
            publisher="Springer Nature",
            landing_url="https://www.nature.com/articles/s41467-020-16791-8",
        )
        unsupported = InstitutionalPaper(
            row_number=2,
            input_doi="10.1126/science.aaz0122",
            doi="10.1126/science.aaz0122",
            title="Science paper",
            publisher="AAAS",
        )

        adapter = select_adapter(supported)

        self.assertIsNotNone(adapter)
        self.assertEqual(adapter.name, "springer_nature")
        self.assertIsNone(select_adapter(unsupported))
        self.assertEqual(unsupported_reason(unsupported), "AAAS")


class PdfCheckTests(unittest.TestCase):
    def test_pdf_checks_cover_url_content_type_and_magic_bytes(self) -> None:
        from paper_automation.institutional.pdf_checks import (
            bytes_look_like_pdf,
            content_type_looks_like_pdf,
            url_looks_like_pdf,
        )

        self.assertTrue(url_looks_like_pdf("https://example.org/content/pdf/10.1007/test.pdf"))
        self.assertTrue(content_type_looks_like_pdf("application/pdf; charset=binary"))
        self.assertTrue(bytes_look_like_pdf(b"%PDF-1.7\nbinary"))
        self.assertFalse(bytes_look_like_pdf(b"HTML"))


class BrowserSessionTests(unittest.TestCase):
    def test_load_page_tolerates_transient_receive_timeouts(self) -> None:
        from paper_automation.institutional.browser_session import DebugBrowserSession

        class FakeWebSocket:
            def close(self) -> None:
                return None

        session = DebugBrowserSession(browser_exe="msedge.exe", debug_port=9555)
        with patch.object(session, "_open_tab", return_value={"id": "tab-1", "webSocketDebuggerUrl": "ws://example"}), patch.object(
            session,
            "_open_websocket",
            return_value=FakeWebSocket(),
        ), patch.object(session, "_send"), patch.object(
            session,
            "_receive_json",
            side_effect=[RuntimeError("timeout"), {"method": "Page.loadEventFired"}],
        ), patch.object(
            session,
            "_evaluate",
            side_effect=["https://www.nature.com/articles/test", "<html></html>", "page text"],
        ), patch.object(session, "_close_tab") as close_tab:
            snapshot = session.load_page("https://doi.org/10.1038/example", wait_seconds=0.0)

        self.assertEqual(snapshot.final_url, "https://www.nature.com/articles/test")
        close_tab.assert_called_once_with("tab-1")

    def test_launch_ignores_locked_profile_files_and_still_starts_browser(self) -> None:
        from paper_automation.institutional.browser_session import DebugBrowserSession

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            profile_root = root / "profile"
            profile_default = profile_root / "Default"
            profile_default.mkdir(parents=True, exist_ok=True)
            (profile_default / "Cookies").write_text("locked", encoding="utf-8")
            session = DebugBrowserSession(browser_exe="msedge.exe", debug_port=9555)
            session.debug_profile = str(root / "debug-profile")
            session.log_path = str(root / "debug.log")
            with patch(
                "paper_automation.institutional.browser_session.browser_default_profile",
                return_value=str(profile_default),
            ), patch(
                "paper_automation.institutional.browser_session.shutil.copy2",
                side_effect=PermissionError("locked"),
            ), patch(
                "paper_automation.institutional.browser_session.subprocess.Popen",
            ) as popen:
                session._launch()

        popen.assert_called_once()


if __name__ == "__main__":
    unittest.main()
