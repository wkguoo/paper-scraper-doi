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

    def test_iucr_candidates_include_article_code_pdf_route_without_meta(self) -> None:
        from paper_automation.institutional.adapters.iucr import IucrAdapter
        from paper_automation.institutional.models import InstitutionalPaper, PageSnapshot

        adapter = IucrAdapter()
        paper = InstitutionalPaper(
            row_number=1,
            input_doi="10.1107/s1600577522008232",
            doi="10.1107/s1600577522008232",
            title="IUCr MatFRAIA paper",
            publisher="International Union of Crystallography",
            landing_url="https://journals.iucr.org/j/issues/2022/05/00/gj5272/index.html",
        )
        snapshot = PageSnapshot(
            requested_url=paper.landing_url,
            final_url=paper.landing_url,
            html="<html><body>Download PDF</body></html>",
            text="Download PDF",
        )

        urls = [candidate.url for candidate in adapter.build_pdf_candidates(paper, snapshot)]

        self.assertIn(
            "https://journals.iucr.org/j/issues/2022/05/00/gj5272/gj5272.pdf",
            urls,
        )

    def test_iucr_candidates_preserve_scripts_paper_query(self) -> None:
        from paper_automation.institutional.adapters.iucr import IucrAdapter
        from paper_automation.institutional.models import InstitutionalPaper, PageSnapshot

        adapter = IucrAdapter()
        paper = InstitutionalPaper(
            row_number=1,
            input_doi="10.1107/s0021889886089999",
            doi="10.1107/s0021889886089999",
            title="IUCr legacy paper",
            publisher="International Union of Crystallography",
            landing_url="https://scripts.iucr.org/cgi-bin/paper?S0021889886089999",
        )
        snapshot = PageSnapshot(
            requested_url=paper.landing_url,
            final_url=paper.landing_url,
            html="<html><body>Download PDF</body></html>",
            text="Download PDF",
        )

        urls = [candidate.url for candidate in adapter.build_pdf_candidates(paper, snapshot)]

        self.assertIn(
            "https://scripts.iucr.org/cgi-bin/paper?S0021889886089999&download=pdf",
            urls,
        )

    def test_common_publisher_adapters_build_direct_pdf_routes(self) -> None:
        from paper_automation.institutional.adapters.common_publishers import (
            AaasAdapter,
            AcsAdapter,
            AipAdapter,
            IeeeAdapter,
            IopAdapter,
            RscAdapter,
            TaylorFrancisAdapter,
            WileyAdapter,
        )
        from paper_automation.institutional.models import InstitutionalPaper, PageSnapshot

        cases = [
            (
                AaasAdapter(),
                InstitutionalPaper(
                    row_number=1,
                    input_doi="10.1126/science.aaz0122",
                    doi="10.1126/science.aaz0122",
                    title="Science paper",
                    publisher="AAAS",
                    landing_url="https://www.science.org/doi/10.1126/science.aaz0122",
                ),
                "https://www.science.org/doi/pdf/10.1126/science.aaz0122",
            ),
            (
                TaylorFrancisAdapter(),
                InstitutionalPaper(
                    row_number=2,
                    input_doi="10.1080/21663831.2018.1553212",
                    doi="10.1080/21663831.2018.1553212",
                    title="Materials Research Letters paper",
                    publisher="Taylor & Francis",
                    landing_url="https://www.tandfonline.com/doi/full/10.1080/21663831.2018.1553212",
                ),
                "https://www.tandfonline.com/doi/pdf/10.1080/21663831.2018.1553212?download=true",
            ),
            (
                AcsAdapter(),
                InstitutionalPaper(
                    row_number=3,
                    input_doi="10.1021/jp106036v",
                    doi="10.1021/jp106036v",
                    title="ACS paper",
                    publisher="American Chemical Society",
                    landing_url="https://pubs.acs.org/doi/10.1021/jp106036v",
                ),
                "https://pubs.acs.org/doi/pdf/10.1021/jp106036v",
            ),
            (
                AipAdapter(),
                InstitutionalPaper(
                    row_number=4,
                    input_doi="10.1063/1.1569662",
                    doi="10.1063/1.1569662",
                    title="AIP paper",
                    publisher="AIP Publishing",
                    landing_url="https://pubs.aip.org/aip/jap/article/93/10/10000/1.1569662",
                ),
                "https://pubs.aip.org/aip/jap/article-pdf/doi/10.1063/1.1569662",
            ),
            (
                WileyAdapter(),
                InstitutionalPaper(
                    row_number=5,
                    input_doi="10.1111/j.1234.2020.001",
                    doi="10.1111/j.1234.2020.001",
                    title="Wiley paper",
                    publisher="Wiley",
                    landing_url="https://onlinelibrary.wiley.com/doi/10.1111/j.1234.2020.001",
                ),
                "https://onlinelibrary.wiley.com/doi/pdf/10.1111/j.1234.2020.001",
            ),
            (
                IeeeAdapter(),
                InstitutionalPaper(
                    row_number=6,
                    input_doi="10.1109/TPAMI.2020.1234567",
                    doi="10.1109/TPAMI.2020.1234567",
                    title="IEEE paper",
                    publisher="IEEE",
                    landing_url="https://ieeexplore.ieee.org/document/9123456",
                ),
                "https://ieeexplore.ieee.org/stamp/stamp.jsp?tp=&arnumber=9123456",
            ),
            (
                RscAdapter(),
                InstitutionalPaper(
                    row_number=7,
                    input_doi="10.1039/d0cc01234a",
                    doi="10.1039/d0cc01234a",
                    title="RSC paper",
                    publisher="Royal Society of Chemistry",
                    landing_url="https://pubs.rsc.org/en/content/articlelanding/2020/cc/d0cc01234a",
                ),
                "https://pubs.rsc.org/en/content/articlepdf/10.1039/d0cc01234a",
            ),
            (
                IopAdapter(),
                InstitutionalPaper(
                    row_number=8,
                    input_doi="10.1088/1361-6463/ab1234",
                    doi="10.1088/1361-6463/ab1234",
                    title="IOP paper",
                    publisher="IOP Publishing",
                    landing_url="https://iopscience.iop.org/article/10.1088/1361-6463/ab1234",
                ),
                "https://iopscience.iop.org/article/10.1088/1361-6463/ab1234/pdf",
            ),
        ]

        for adapter, paper, expected_url in cases:
            with self.subTest(adapter=adapter.name):
                snapshot = PageSnapshot(
                    requested_url=paper.landing_url,
                    final_url=paper.landing_url,
                    html="<html><body>PDF</body></html>",
                    text="PDF",
                )

                urls = [candidate.url for candidate in adapter.build_pdf_candidates(paper, snapshot)]

                self.assertIn(expected_url, urls)


class InstitutionalRegistryTests(unittest.TestCase):
    def test_registry_routes_supported_publishers(self) -> None:
        from paper_automation.institutional.models import InstitutionalPaper
        from paper_automation.institutional.registry import select_adapter, unsupported_reason

        cases = [
            (
                InstitutionalPaper(
                    row_number=1,
                    input_doi="10.1038/s41467-020-16791-8",
                    doi="10.1038/s41467-020-16791-8",
                    title="Nature paper",
                    publisher="Springer Nature",
                    landing_url="https://www.nature.com/articles/s41467-020-16791-8",
                ),
                "springer_nature",
            ),
            (
                InstitutionalPaper(
                    row_number=2,
                    input_doi="10.1126/science.aaz0122",
                    doi="10.1126/science.aaz0122",
                    title="Science paper",
                    publisher="AAAS",
                ),
                "aaas",
            ),
            (
                InstitutionalPaper(
                    row_number=3,
                    input_doi="10.1080/21663831.2018.1553212",
                    doi="10.1080/21663831.2018.1553212",
                    title="Taylor paper",
                    publisher="Taylor & Francis",
                ),
                "taylor_francis",
            ),
            (
                InstitutionalPaper(
                    row_number=4,
                    input_doi="10.1021/jp106036v",
                    doi="10.1021/jp106036v",
                    title="ACS paper",
                    publisher="American Chemical Society",
                ),
                "acs",
            ),
            (
                InstitutionalPaper(
                    row_number=5,
                    input_doi="10.1063/1.1569662",
                    doi="10.1063/1.1569662",
                    title="AIP paper",
                    publisher="AIP Publishing",
                ),
                "aip",
            ),
            (
                InstitutionalPaper(
                    row_number=6,
                    input_doi="10.1111/j.1234.2020.001",
                    doi="10.1111/j.1234.2020.001",
                    title="Wiley paper",
                    publisher="Wiley",
                ),
                "wiley",
            ),
            (
                InstitutionalPaper(
                    row_number=7,
                    input_doi="10.1109/TPAMI.2020.1234567",
                    doi="10.1109/TPAMI.2020.1234567",
                    title="IEEE paper",
                    publisher="IEEE",
                ),
                "ieee",
            ),
            (
                InstitutionalPaper(
                    row_number=8,
                    input_doi="10.1039/d0cc01234a",
                    doi="10.1039/d0cc01234a",
                    title="RSC paper",
                    publisher="Royal Society of Chemistry",
                ),
                "rsc",
            ),
            (
                InstitutionalPaper(
                    row_number=9,
                    input_doi="10.1088/1361-6463/ab1234",
                    doi="10.1088/1361-6463/ab1234",
                    title="IOP paper",
                    publisher="IOP Publishing",
                ),
                "iop",
            ),
        ]

        for paper, expected_adapter in cases:
            with self.subTest(doi=paper.doi):
                adapter = select_adapter(paper)

                self.assertIsNotNone(adapter)
                self.assertEqual(adapter.name, expected_adapter)

        unknown = InstitutionalPaper(
            row_number=99,
            input_doi="10.9999/example",
            doi="10.9999/example",
            title="Unknown paper",
            publisher="Unknown",
        )
        self.assertIsNone(select_adapter(unknown))
        self.assertEqual(unsupported_reason(unknown), "unknown_publisher")


class PdfCheckTests(unittest.TestCase):
    def test_pdf_checks_cover_url_content_type_and_magic_bytes(self) -> None:
        from paper_automation.institutional.pdf_checks import (
            bytes_look_like_pdf,
            content_type_looks_like_pdf,
            url_looks_like_pdf,
        )

        self.assertTrue(url_looks_like_pdf("https://example.org/content/pdf/10.1007/test.pdf"))
        self.assertTrue(url_looks_like_pdf("https://pubs.aip.org/aip/jap/article-pdf/doi/10.1063/1.1569662"))
        self.assertTrue(content_type_looks_like_pdf("application/pdf; charset=binary"))
        self.assertTrue(bytes_look_like_pdf(b"%PDF-1.7\nbinary\n%%EOF\n"))
        self.assertFalse(bytes_look_like_pdf(b"HTML"))
        self.assertFalse(bytes_look_like_pdf(b"%PDF-1.7\nmissing-eof"))


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
        launch_cmd = popen.call_args.args[0]
        self.assertIn("--disable-extensions", launch_cmd)
        self.assertIn(f"--user-data-dir={session.debug_profile}", launch_cmd)


if __name__ == "__main__":
    unittest.main()
