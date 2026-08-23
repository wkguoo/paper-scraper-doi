from __future__ import annotations

import csv
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from paper_automation.elsevier_api import ElsevierXmlResult
from paper_automation.xml_batch import load_xml_catalog, run_xml_batch
from paper_batch import build_parser


def full_xml(title: str, marker: str = "") -> bytes:
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<full-text-retrieval-response xmlns:dc="http://purl.org/dc/elements/1.1/"
 xmlns:prism="http://prismstandard.org/namespaces/basic/2.0/">
 <coredata><dc:title>{title}</dc:title><dc:creator>Zhang Wei</dc:creator>
 <prism:publicationName>Acta Materialia</prism:publicationName>
 <prism:coverDate>2020-01-01</prism:coverDate></coredata><body>{marker}</body>
</full-text-retrieval-response>""".encode("utf-8")


class FakeClient:
    def __init__(self, responses: dict[str, ElsevierXmlResult]) -> None:
        self.api_key = "key"
        self.responses = dict(responses)
        self.calls: list[tuple[str, str]] = []

    def retrieve_article_xml(self, identifier: str, *, identifier_type: str = "doi") -> ElsevierXmlResult:
        self.calls.append((identifier, identifier_type))
        return self.responses[identifier]


class XmlBatchTests(unittest.TestCase):
    def make_catalog(self, root: Path, *, same_titles: bool = False) -> Path:
        result = root / "inputs"
        result.mkdir(parents=True)
        first_title = "Same title" if same_titles else "Alpha paper"
        second_title = "Same title" if same_titles else "Beta conference record"
        rows = [
            {
                "序号": 1,
                "期刊谱系": "Acta Materialia 谱系",
                "期刊名": "Acta Materialia",
                "年份": 2020,
                "标题": first_title,
                "DOI": "10.1016/alpha",
                "Scopus ID": "111",
                "EID": "2-s2.0-111",
            },
            {
                "序号": 2,
                "期刊谱系": "Acta Materialia 谱系",
                "期刊名": "Acta Materialia",
                "年份": 2020,
                "标题": second_title,
                "DOI": "",
                "Scopus ID": "",
                "EID": "2-s2.0-222",
            },
        ]
        source = result / "papers.csv"
        with source.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)
        return source

    def success_result(self, identifier: str, title: str, marker: str = "") -> ElsevierXmlResult:
        return ElsevierXmlResult(
            status="success",
            identifier_type="doi" if identifier.startswith("10.") else "scopus_id",
            identifier=identifier,
            http_status=200,
            content_type="text/xml",
            xml_bytes=full_xml(title, marker),
            title=title,
            authors=("Zhang Wei",),
            journal="Acta Materialia",
            year="2020",
        )

    def test_catalog_reads_doi_and_scopus_routes_without_raw_cache(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            records = load_xml_catalog(self.make_catalog(Path(tmp)))
        self.assertEqual(len(records), 2)
        self.assertEqual((records[0].identifier_type, records[0].identifier), ("doi", "10.1016/alpha"))
        self.assertEqual((records[1].identifier_type, records[1].identifier), ("scopus_id", "222"))

    def test_catalog_accepts_english_columns(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "papers.csv"
            with source.open("w", encoding="utf-8-sig", newline="") as handle:
                writer = csv.DictWriter(
                    handle,
                    fieldnames=["doi", "title", "year", "journal"],
                )
                writer.writeheader()
                writer.writerow(
                    {
                        "doi": "https://doi.org/10.1016/alpha",
                        "title": "Alpha paper",
                        "year": "2020",
                        "journal": "Acta Materialia",
                    }
                )

            records = load_xml_catalog(source)

        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].doi, "10.1016/alpha")
        self.assertEqual(records[0].journal_family, "Acta Materialia")

    def test_success_writes_raw_xml_named_year_author_title_and_no_pdf(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = self.make_catalog(root)
            first = self.success_result("10.1016/alpha", "Alpha paper")
            second = self.success_result("222", "Beta conference record")
            client = FakeClient({"10.1016/alpha": first, "222": second})
            result = run_xml_batch(
                input_path=source,
                output_root=root / "delivery",
                run_name="xml-run",
                workers=1,
                min_free_bytes=0,
                client=client,
                progress=lambda _: None,
            )

            files = sorted((result.run_dir / "xml").rglob("*.xml"))
            self.assertEqual(result.success, 2)
            self.assertEqual(result.failed, 0)
            self.assertEqual(result.pending, 0)
            self.assertEqual(len(files), 2)
            self.assertTrue(any(path.name == "2020-Zhang-Alpha-paper.xml" for path in files))
            self.assertTrue(all(path.parent.parent == result.run_dir / "xml" for path in files))
            self.assertEqual(files[0].read_bytes() in {first.xml_bytes, second.xml_bytes}, True)
            self.assertEqual(list(result.run_dir.rglob("*.pdf")), [])
            self.assertEqual(client.calls, [("10.1016/alpha", "doi"), ("222", "scopus_id")])

    def test_limit_then_same_command_resumes_without_redownloading_success(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = self.make_catalog(root)
            first_client = FakeClient({"10.1016/alpha": self.success_result("10.1016/alpha", "Alpha paper")})
            first = run_xml_batch(
                input_path=source,
                output_root=root / "delivery",
                run_name="xml-run",
                workers=1,
                limit=1,
                min_free_bytes=0,
                client=first_client,
                progress=lambda _: None,
            )
            self.assertEqual((first.success, first.pending), (1, 1))

            second_client = FakeClient({"222": self.success_result("222", "Beta conference record")})
            second = run_xml_batch(
                input_path=source,
                output_root=root / "delivery",
                run_name="xml-run",
                workers=1,
                min_free_bytes=0,
                client=second_client,
                progress=lambda _: None,
            )
            self.assertEqual((second.success, second.pending, second.reused), (2, 0, 1))
            self.assertEqual(second_client.calls, [("222", "scopus_id")])

    def test_404_continues_but_authorization_error_stops(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = self.make_catalog(root)
            not_found = ElsevierXmlResult(
                status="not_found", identifier_type="doi", identifier="10.1016/alpha", http_status=404, reason="http_404"
            )
            continuing = FakeClient(
                {
                    "10.1016/alpha": not_found,
                    "111": ElsevierXmlResult(
                        status="not_found",
                        identifier_type="scopus_id",
                        identifier="111",
                        http_status=404,
                        reason="http_404",
                    ),
                    "222": self.success_result("222", "Beta conference record"),
                }
            )
            result = run_xml_batch(
                input_path=source,
                output_root=root / "continue",
                run_name="xml-run",
                workers=1,
                min_free_bytes=0,
                client=continuing,
                progress=lambda _: None,
            )
            self.assertEqual((result.success, result.failed, result.pending), (1, 1, 0))
            self.assertEqual(
                continuing.calls,
                [("10.1016/alpha", "doi"), ("111", "scopus_id"), ("222", "scopus_id")],
            )
            no_retry = FakeClient({})
            resumed = run_xml_batch(
                input_path=source,
                output_root=root / "continue",
                run_name="xml-run",
                workers=1,
                min_free_bytes=0,
                client=no_retry,
                progress=lambda _: None,
            )
            self.assertEqual((resumed.success, resumed.failed, resumed.pending), (1, 1, 0))
            self.assertEqual(no_retry.calls, [])

            unauthorized = ElsevierXmlResult(
                status="unauthorized", identifier_type="doi", identifier="10.1016/alpha", http_status=401, reason="http_401"
            )
            stopping = FakeClient({"10.1016/alpha": unauthorized})
            stopped = run_xml_batch(
                input_path=source,
                output_root=root / "stop",
                run_name="xml-run",
                workers=1,
                min_free_bytes=0,
                client=stopping,
                progress=lambda _: None,
            )
            self.assertEqual(stopped.stopped_reason, "unauthorized")
            self.assertEqual((stopped.failed, stopped.pending), (1, 1))
            self.assertEqual(stopping.calls, [("10.1016/alpha", "doi")])

    def test_doi_failure_recovers_once_through_scopus_id(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = self.make_catalog(root)
            invalid = ElsevierXmlResult(
                status="invalid_xml",
                identifier_type="doi",
                identifier="10.1016/alpha",
                http_status=200,
                reason="article_response_html",
            )
            recovered = self.success_result("111", "Alpha paper")
            client = FakeClient({"10.1016/alpha": invalid, "111": recovered})
            result = run_xml_batch(
                input_path=source,
                output_root=root / "delivery",
                run_name="xml-run",
                workers=1,
                limit=1,
                min_free_bytes=0,
                client=client,
                progress=lambda _: None,
            )
            self.assertEqual((result.success, result.failed, result.pending), (1, 0, 1))
            self.assertEqual(client.calls, [("10.1016/alpha", "doi"), ("111", "scopus_id")])

    def test_name_collision_adds_identifier_hash_without_overwrite(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = self.make_catalog(root, same_titles=True)
            client = FakeClient(
                {
                    "10.1016/alpha": self.success_result("10.1016/alpha", "Same title", "one"),
                    "222": self.success_result("222", "Same title", "two"),
                }
            )
            result = run_xml_batch(
                input_path=source,
                output_root=root / "delivery",
                run_name="xml-run",
                workers=2,
                min_free_bytes=0,
                client=client,
                progress=lambda _: None,
            )
            names = sorted(path.name for path in (result.run_dir / "xml").rglob("*.xml"))
            self.assertEqual(len(names), 2)
            self.assertEqual(len(set(names)), 2)
            self.assertTrue(any(name == "2020-Zhang-Same-title.xml" for name in names))

    def test_disk_guard_stops_before_api_calls(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = self.make_catalog(root)
            client = FakeClient({})
            usage = shutil_usage(total=100, used=100, free=0)
            with patch("paper_automation.xml_batch.shutil.disk_usage", return_value=usage):
                with self.assertRaisesRegex(RuntimeError, "xml_disk_low"):
                    run_xml_batch(
                        input_path=source,
                        output_root=root / "delivery",
                        run_name="xml-run",
                        workers=1,
                        min_free_bytes=1,
                        client=client,
                        progress=lambda _: None,
                    )
            self.assertEqual(client.calls, [])

    def test_cli_exposes_idempotent_xml_download_command(self) -> None:
        args = build_parser().parse_args(
            [
                "xml-download",
                "--input",
                "papers.csv",
                "--out",
                "E:/archive",
                "--run-name",
                "Elsevier全文XML_20260823",
                "--workers",
                "4",
            ]
        )
        self.assertEqual(args.command, "xml-download")
        self.assertEqual(args.workers, 4)
        self.assertEqual(args.limit, 0)


class shutil_usage(tuple):
    __slots__ = ()

    def __new__(cls, total: int, used: int, free: int):
        return tuple.__new__(cls, (total, used, free))

    total = property(lambda self: self[0])
    used = property(lambda self: self[1])
    free = property(lambda self: self[2])


if __name__ == "__main__":
    unittest.main()
