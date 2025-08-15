# utils_bip.py
# ---------------------------------------------------------------
# Utilities for OTBI-convention extraction/structuring.
# - Safe names/paths
# - ZIP-like extraction
# - Scanning by extensions
# - Parsing *_datamodel.xdm → datasets & valueSets SQL
# - Writing SQL files (datasets/*.sql and lv_*.sql)
# - Zipping a folder
# - Unique-folder creation with _1, _2... suffixes
# ---------------------------------------------------------------

from __future__ import annotations

import io
import os
import re
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Tuple

from lxml import etree


# ---------- naming & paths ----------

def safe_name(name: str) -> str:
    name = (name or "").strip()
    name = re.sub(r"[^\w\-.]+", "_", name, flags=re.UNICODE)
    name = re.sub(r"_+", "_", name)
    return name.strip("._") or "unnamed"


def safe_path_from_rel(rel_dir: Path) -> Path:
    """Sanitize each part of a relative path to be filesystem-safe."""
    parts: List[str] = []
    for part in rel_dir.parts:
        if part in (".", ""):
            continue
        parts.append(safe_name(part))
    return Path(*parts) if parts else Path(".")


def unique_subdir(parent: Path, name: str) -> Path:
    """Create a unique subdirectory (name, name_1, name_2, ...)."""
    base = safe_name(name)
    target = parent / base
    i = 1
    while target.exists():
        target = parent / f"{base}_{i}"
        i += 1
    target.mkdir(parents=True, exist_ok=True)
    return target


# ---------- extraction / search ----------

def extract_ziplike(file_obj, dest_dir: Path) -> None:
    """Extract a ziplike (.xdmz/.xdrz/.xdoz/.zip) into dest_dir."""
    dest_dir.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(file_obj) as zf:
        zf.extractall(dest_dir)


def find_by_ext(base_dir: Path, exts: tuple[str, ...]) -> List[Path]:
    """Recursively find files with the given extensions (case-insensitive)."""
    results: List[Path] = []
    loexts = tuple(e.lower() for e in exts)
    for root, _, files in os.walk(base_dir):
        for f in files:
            if f.lower().endswith(loexts):
                results.append(Path(root) / f)
    results.sort(key=lambda p: p.as_posix())
    return results


def find_datamodel_files(base_dir: Path) -> List[Path]:
    """Find *_datamodel.xdm files (case-insensitive)."""
    out: List[Path] = []
    for root, _, files in os.walk(base_dir):
        for f in files:
            if f.lower().endswith("_datamodel.xdm"):
                out.append(Path(root) / f)
    out.sort(key=lambda p: p.as_posix())
    return out


# ---------- parsing ----------

def parse_datamodel_xdm(xdm_path: Path) -> Tuple[List[Tuple[str, str]], List[Tuple[str, str]]]:
    """
    Returns:
      - datasets:  [(dataset_name, sql_text), ...]
      - valuesets: [(valueset_id, sql_text), ...]
    Uses local-name() to ignore namespaces.
    """
    parser = etree.XMLParser(remove_blank_text=False, recover=True)
    tree = etree.parse(str(xdm_path), parser)
    root = tree.getroot()

    datasets: List[Tuple[str, str]] = []
    for ds in root.xpath(".//*[local-name()='dataSets']/*[local-name()='dataSet']"):
        ds_name = safe_name(ds.get("name") or "Dataset")
        sql_nodes = ds.xpath("./*[local-name()='sql']")
        sql_texts = [(sn.text or "").strip() for sn in sql_nodes if (sn.text or "").strip()]
        if sql_texts:
            datasets.append((ds_name, "\n\n".join(sql_texts)))

    valuesets: List[Tuple[str, str]] = []
    for vs in root.xpath(".//*[local-name()='valueSets']/*[local-name()='valueSet']"):
        vs_id = safe_name(vs.get("id") or "ValueSet")
        sql_nodes = vs.xpath("./*[local-name()='sql']")
        sql_texts = [(sn.text or "").strip() for sn in sql_nodes if (sn.text or "").strip()]
        if sql_texts:
            valuesets.append((vs_id, "\n\n".join(sql_texts)))

    return datasets, valuesets


# ---------- writing ----------

def write_sql_otbi(out_dir: Path,
                   datasets: List[Tuple[str, str]],
                   valuesets: List[Tuple[str, str]],
                   header_title: str | None = None) -> List[Path]:
    """
    OTBI convention:
      out_dir/
        <DATASET>.sql
        lv_<VALUESET>.sql
    (no nested datasets/valuesets folders)
    """
    created: List[Path] = []
    out_dir.mkdir(parents=True, exist_ok=True)

    header = ""
    if header_title:
        header = (
            f"-- {header_title}\n" 
        )

    for name, sql in datasets:
        p = out_dir / f"{name}.sql"
        p.write_text(header + sql.strip() + "\n", encoding="utf-8")
        created.append(p)

    for vid, sql in valuesets:
        p = out_dir / f"lv_{vid}.sql"
        p.write_text(header + sql.strip() + "\n", encoding="utf-8")
        created.append(p)

    return created


# ---------- packaging ----------

def zip_folder(folder: Path) -> bytes:
    """Zip the given folder (return bytes in-memory)."""
    bio = io.BytesIO()
    with zipfile.ZipFile(bio, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for root, _, files in os.walk(folder):
            for fn in files:
                full = Path(root) / fn
                zf.write(full, full.relative_to(folder))
    bio.seek(0)
    return bio.read()
