#!/usr/bin/env python3
from __future__ import annotations

import csv
import json
import re
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path

W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
R_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
P_NS = "http://schemas.openxmlformats.org/package/2006/relationships"

NS = {"w": W_NS, "r": R_NS}

DOCX_PATH = Path("Council Research List.docx")
JSON_PATH = Path("council_research_database.json")
CSV_PATH = Path("council_research_database.csv")
JS_PATH = Path("council_research_database.js")

SECTION_MAP = {
    "Community Planning Partnership:": "community_planning_partnership",
    "Planning:": "planning",
    "Participatory Budgeting:": "participatory_budgeting",
    "Statistics:": "statistics",
    "Other Useful Info:": "other_useful_info",
}


def normalize_text(value: str) -> str:
    return " ".join((value or "").replace("\xa0", " ").split()).strip()


def squash(value: str) -> str:
    return re.sub(r"\s+", "", value or "").lower()


def paragraph_to_record(p: ET.Element, rels: dict[str, str]) -> dict:
    text_parts: list[str] = []
    links: list[dict[str, str]] = []

    for child in list(p):
        if child.tag == f"{{{W_NS}}}hyperlink":
            rid = child.attrib.get(f"{{{R_NS}}}id")
            target = rels.get(rid, "") if rid else ""
            link_text = "".join(t.text or "" for t in child.findall(".//w:t", NS))
            if link_text:
                text_parts.append(link_text)
            if target:
                links.append({"text": normalize_text(link_text), "url": target})
        else:
            plain_text = "".join(t.text or "" for t in child.findall(".//w:t", NS))
            if plain_text:
                text_parts.append(plain_text)

    full_text = normalize_text("".join(text_parts))
    is_bullet = p.find("w:pPr/w:numPr", NS) is not None
    return {"text": full_text, "is_bullet": is_bullet, "links": links}


def load_paragraphs(docx_path: Path) -> list[dict]:
    with zipfile.ZipFile(docx_path) as zf:
        rel_root = ET.fromstring(zf.read("word/_rels/document.xml.rels"))
        rels = {
            rel.attrib["Id"]: rel.attrib.get("Target", "")
            for rel in rel_root.findall(f"{{{P_NS}}}Relationship")
        }
        doc_root = ET.fromstring(zf.read("word/document.xml"))

    paragraphs: list[dict] = []
    for p in doc_root.findall(".//w:p", NS):
        rec = paragraph_to_record(p, rels)
        if rec["text"]:
            paragraphs.append(rec)
    return paragraphs


def extract_council_names(paragraphs: list[dict]) -> list[str]:
    contents_idx = next(i for i, p in enumerate(paragraphs) if squash(p["text"]) == "contents")
    council_area_idx = next(
        i for i, p in enumerate(paragraphs) if squash(p["text"]) in {"councilarea", "council area"}
    )
    names: list[str] = []

    for p in paragraphs[contents_idx + 1 : council_area_idx]:
        text = p["text"]
        match = re.match(r"^(.*?)(\d+)$", text)
        if match:
            name = normalize_text(match.group(1))
            if name:
                names.append(name)

    if len(names) != 32:
        raise ValueError(f"Expected 32 councils from contents, got {len(names)}")
    return names


def build_item(para: dict) -> dict:
    urls = [link["url"] for link in para["links"] if link.get("url")]
    unique_urls = []
    for u in urls:
        if u not in unique_urls:
            unique_urls.append(u)

    item = {"text": para["text"], "url": unique_urls[0] if unique_urls else None}
    if len(unique_urls) > 1:
        item["links"] = unique_urls
    return item


def parse_records(paragraphs: list[dict], councils: list[str]) -> list[dict]:
    council_area_idx = next(
        i for i, p in enumerate(paragraphs) if squash(p["text"]) in {"councilarea", "council area"}
    )
    data_start = council_area_idx + 1

    # Find starts of each council section in the main data table.
    start_indices: list[int] = []
    cursor = data_start
    for council in councils:
        found = None
        for i in range(cursor, len(paragraphs)):
            if paragraphs[i]["text"] == council:
                found = i
                break
        if found is None:
            raise ValueError(f"Could not locate council section for: {council}")
        start_indices.append(found)
        cursor = found + 1

    records: list[dict] = []
    for idx, council in enumerate(councils):
        start = start_indices[idx]
        end = start_indices[idx + 1] if idx + 1 < len(councils) else len(paragraphs)
        block = paragraphs[start:end]

        record = {
            "local_authority": council,
            "estimated_population_2023": None,
            "population_rank_2023": None,
            "area_rank": None,
            "community_planning_partnership": [],
            "planning": [],
            "participatory_budgeting": [],
            "statistics": [],
            "other_useful_info": [],
            "source": DOCX_PATH.name,
        }

        current_section = None
        for para in block[1:]:
            text = para["text"]
            if text in SECTION_MAP:
                current_section = SECTION_MAP[text]
                continue

            if text == "Estimated Population 2023 (NRS):":
                continue

            if record["estimated_population_2023"] is None and re.match(r"^[\d,]+$", text):
                record["estimated_population_2023"] = text
                continue

            if record["population_rank_2023"] is None and "highest population in 2023" in text.lower():
                record["population_rank_2023"] = text
                continue

            if record["area_rank"] is None and "largest by area" in text.lower():
                record["area_rank"] = text
                continue

            if current_section:
                record[current_section].append(build_item(para))

        search_text_parts = [
            record["local_authority"],
            record["estimated_population_2023"] or "",
            record["population_rank_2023"] or "",
            record["area_rank"] or "",
        ]
        for key in [
            "community_planning_partnership",
            "planning",
            "participatory_budgeting",
            "statistics",
            "other_useful_info",
        ]:
            for item in record[key]:
                search_text_parts.append(item["text"])
                if item.get("url"):
                    search_text_parts.append(item["url"])
                for extra in item.get("links", []):
                    search_text_parts.append(extra)

        record["search_text"] = normalize_text(" ".join(search_text_parts)).lower()
        records.append(record)

    return records


def extract_useful_links(paragraphs: list[dict]) -> list[dict]:
    result: list[dict] = []
    for p in paragraphs:
        if squash(p["text"]) == "contents":
            break
        if p["links"]:
            for link in p["links"]:
                if link.get("url"):
                    result.append({"text": p["text"], "url": link["url"]})
    return result


def item_to_csv_text(item: dict) -> str:
    text = item.get("text", "")
    url = item.get("url")
    if url:
        return f"{text} [{url}]"
    return text


def write_outputs(records: list[dict], useful_links: list[dict]) -> None:
    payload = {
        "title": "Council Research Aug 2025",
        "source_file": DOCX_PATH.name,
        "authority_count": len(records),
        "useful_links": useful_links,
        "authorities": records,
    }

    JSON_PATH.write_text(json.dumps(payload, indent=2, ensure_ascii=False))
    JS_PATH.write_text("window.COUNCIL_DB = " + json.dumps(payload, ensure_ascii=False) + ";\n")

    fieldnames = [
        "local_authority",
        "estimated_population_2023",
        "population_rank_2023",
        "area_rank",
        "community_planning_partnership",
        "planning",
        "participatory_budgeting",
        "statistics",
        "other_useful_info",
        "search_text",
    ]
    with CSV_PATH.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for rec in records:
            row = {
                "local_authority": rec["local_authority"],
                "estimated_population_2023": rec["estimated_population_2023"],
                "population_rank_2023": rec["population_rank_2023"],
                "area_rank": rec["area_rank"],
                "search_text": rec["search_text"],
            }
            for key in [
                "community_planning_partnership",
                "planning",
                "participatory_budgeting",
                "statistics",
                "other_useful_info",
            ]:
                row[key] = " | ".join(item_to_csv_text(i) for i in rec[key])
            writer.writerow(row)


def main() -> None:
    paragraphs = load_paragraphs(DOCX_PATH)
    councils = extract_council_names(paragraphs)
    useful_links = extract_useful_links(paragraphs)
    records = parse_records(paragraphs, councils)
    write_outputs(records, useful_links)
    print(f"Wrote {JSON_PATH}")
    print(f"Wrote {CSV_PATH}")
    print(f"Wrote {JS_PATH}")
    print(f"Authorities: {len(records)}")


if __name__ == "__main__":
    main()
