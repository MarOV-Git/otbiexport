# app.py
# ---------------------------------------------------------------
# Streamlit UI organizer for BI Publisher bundles:
# - .xdmz (data model bundle)
# - .xdoz (report bundle)
# - .xdrz (container with multiple .xdmz/.xdoz)
#
# XDRZ behavior (preserves original tree):
#   <OUT>/<RELATIVE_PATH_INSIDE_XDRZ>/
#     <MODEL_NAME>/                 (created for each .xdmz)
#       *.sql
#       Catalog/<original .xdmz>
#     _Orphan/                      (only if some .xdoz has no match here/ancestors/global)
#       Catalog/<orphan .xdoz>
#       report_templates/<templates>
#
# XDMZ direct upload:
#   <OUT>/<BASE_NAME>/
#     *.sql
#     Catalog/<original .xdmz>
#
# XDOZ direct upload:
#   <OUT>/<BASE_NAME>/
#     Catalog/<original .xdoz>
#     report_templates/<templates>
#
# Download button is above the preview.
# ---------------------------------------------------------------

from __future__ import annotations

import logging
import shutil
import zipfile
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Dict, List, Optional

import streamlit as st
from lxml import etree

from utils_bip import (
    safe_name,
    extract_ziplike,
    find_by_ext,
    find_datamodel_files,
    parse_datamodel_xdm,
    write_sql_otbi,
    zip_folder,
    safe_path_from_rel,
    unique_subdir,
)

LOG_FORMAT = "[%(levelname)s] %(message)s"
logging.basicConfig(level=logging.INFO, format=LOG_FORMAT)
log = logging.getLogger("app")


# ---------- small helpers ----------

def ensure_dir(p: Path) -> Path:
    p.mkdir(parents=True, exist_ok=True)
    return p


def read_report_datamodel_url(xdo_file: Path) -> Optional[str]:
    """
    Open report definition inside a .xdoz (zip) and get <dataModel url="...">.
    Tries common names: report.xdo, *_report.xdo, or any *.xdo as fallback.
    """
    try:
        with zipfile.ZipFile(xdo_file) as zf:
            names = zf.namelist()
            candidates = [n for n in names if n.lower().endswith("report.xdo") or n.lower().endswith("_report.xdo")]
            if not candidates:
                candidates = [n for n in names if n.lower().endswith(".xdo")]
            if not candidates:
                return None
            candidates.sort(key=lambda s: (s.count("/"), len(s)))  # prefer root/shorter
            with zf.open(candidates[0]) as f:
                data = f.read()
        parser = etree.XMLParser(remove_blank_text=True, recover=True)
        root = etree.fromstring(data, parser=parser)
        dm_nodes = root.xpath(".//*[local-name()='dataModel']/@url")
        return dm_nodes[0] if dm_nodes else None
    except Exception as e:
        log.warning(f"Failed to parse report.xdo in {xdo_file.name}: {e}")
        return None


def extract_templates_from_xdoz(xdo_file: Path, dest_dir: Path) -> List[Path]:
    """
    Extract known template files from a .xdoz into dest_dir/report_templates.
    Returns the list of created files.
    """
    created: List[Path] = []
    tpl_dir = ensure_dir(dest_dir / "report_templates")
    template_exts = (
        ".rtf", ".xsl", ".xlsx", ".xls", ".xpt", ".xltx", ".xlsm", ".pptx", ".etext", ".html", ".xhtml"
    )
    try:
        with zipfile.ZipFile(xdo_file) as zf:
            names = zf.namelist()
            # 1) by extension
            for n in names:
                if n.endswith("/") or n.startswith("__MACOSX/"):
                    continue
                if any(n.lower().endswith(ext) for ext in template_exts):
                    out = tpl_dir / Path(n).name
                    base, suf = out.stem, out.suffix
                    i = 1
                    while out.exists():
                        out = tpl_dir / f"{base}_{i}{suf}"
                        i += 1
                    with zf.open(n) as f_in, open(out, "wb") as f_out:
                        shutil.copyfileobj(f_in, f_out)
                    created.append(out)
            # 2) by <templates><template url="...">
            #    Read the report definition file again
            candidates = [n for n in names if n.lower().endswith("report.xdo") or n.lower().endswith("_report.xdo")]
            if not candidates:
                candidates = [n for n in names if n.lower().endswith(".xdo")]
            if candidates:
                candidates.sort(key=lambda s: (s.count("/"), len(s)))
                with zf.open(candidates[0]) as f:
                    data = f.read()
                parser = etree.XMLParser(remove_blank_text=True, recover=True)
                root = etree.fromstring(data, parser=parser)
                refs = root.xpath(".//*[local-name()='templates']/*[local-name()='template']/@url")
                for ref in refs:
                    src = None
                    if ref in names:
                        src = ref
                    else:
                        # basename fallback
                        bn = Path(ref).name.lower()
                        for n in names:
                            if Path(n).name.lower() == bn:
                                src = n
                                break
                    if src:
                        out = tpl_dir / Path(src).name
                        base, suf = out.stem, out.suffix
                        i = 1
                        while out.exists():
                            out = tpl_dir / f"{base}_{i}{suf}"
                            i += 1
                        with zf.open(src) as f_in, open(out, "wb") as f_out:
                            shutil.copyfileobj(f_in, f_out)
                        if out not in created:
                            created.append(out)
    except Exception as e:
        log.warning(f"Failed to extract templates from {xdo_file.name}: {e}")
    return created


def walk_up_rel_paths(rel_path: Path):
    """
    Yield POSIX relative paths from the current folder up to root.
    E.g. 'a/b/c' -> 'a/b/c', 'a/b', 'a', '.'
    """
    cur = rel_path
    while True:
        yield cur.as_posix()
        if cur == Path("."):
            break
        cur = cur.parent if cur.parent != cur else Path(".")


# ---------- UI ----------

st.set_page_config(page_title="OTBI Export Organizer", page_icon="🗂️", layout="centered")

st.markdown(
    """
    <div style="text-align:center; margin-bottom: 0.5rem;">
      <h1 style="margin-bottom:0;">🗂️ OTBI Export Organizer</h1>
      <p style="color:#666; margin-top:0.25rem;">
        Upload <b>.xdmz</b>, <b>.xdrz</b>, or <b>.xdoz</b> — output keeps folder structure for XDRZ and matches reports to data models.
      </p>
    </div>
    """,
    unsafe_allow_html=True,
)

uploaded = st.file_uploader("Drop an .xdmz, .xdrz, or .xdoz file", type=["xdmz", "xdrz", "xdoz"])
show_preview = st.checkbox("Show SQL preview", value=True)
limit_preview = st.number_input("Preview lines per file", 5, 200, 25, step=5)


# ---------- main ----------

if uploaded is not None:
    base_name = safe_name(Path(uploaded.name).stem)
    ext = Path(uploaded.name).suffix.lower()

    progress = st.progress(0, text="Starting…")

    with TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        src = ensure_dir(tmp / "__src")                  # extracted content
        out_root = ensure_dir(tmp / f"{base_name}_OUT")  # final output

        created_paths: List[Path] = []

        # Extract uploaded file into src
        progress.progress(10, text="Extracting…")
        try:
            extract_ziplike(uploaded, src)
        except zipfile.BadZipFile:
            st.error("The file is not a valid ZIP (corrupted?).")
            st.stop()

        try:
            # -------------------- XDMZ (single model bundle) --------------------
            if ext == ".xdmz":
                progress.progress(25, text="Searching for *_datamodel.xdm…")
                dm_files = find_datamodel_files(src)
                if not dm_files:
                    st.error("No *_datamodel.xdm found inside the .xdmz.")
                else:
                    model_root = unique_subdir(out_root, base_name)
                    catalog_dir = ensure_dir(model_root / "Catalog")
                    # Copy original uploaded into Catalog/
                    (catalog_dir / uploaded.name).write_bytes(uploaded.getvalue())

                    total = max(len(dm_files), 1)
                    for i, dm in enumerate(dm_files, start=1):
                        pct = 25 + int(55 * (i / total))
                        progress.progress(min(pct, 80), text=f"Parsing {dm.name} ({i}/{len(dm_files)})…")
                        try:
                            datasets, valuesets = parse_datamodel_xdm(dm)
                        except Exception as e:
                            st.warning(f"Failed to parse {dm.name}: {e}")
                            continue
                        created_paths += write_sql_otbi(
                            model_root,
                            datasets,
                            valuesets,
                            header_title=f"",
                        )

            # -------------------- XDOZ (single report bundle) --------------------
            elif ext == ".xdoz":
                progress.progress(25, text="Organizing report bundle…")

                report_root = unique_subdir(out_root, base_name)
                catalog_dir = ensure_dir(report_root / "Catalog")
                # Copy original uploaded .xdoz into Catalog/
                (catalog_dir / uploaded.name).write_bytes(uploaded.getvalue())
                created_paths.append(catalog_dir / uploaded.name)

                # Extract templates
                progress.progress(45, text="Extracting templates…")
                temp_xdoz = src / uploaded.name
                temp_xdoz.write_bytes(uploaded.getvalue())
                created_paths += extract_templates_from_xdoz(temp_xdoz, report_root)

            # -------------------- XDRZ (container: preserve tree) --------------------
            elif ext == ".xdrz":
                progress.progress(20, text="Scanning container…")

                # Discover files keeping their relative parents
                xdmz_list = find_by_ext(src, (".xdmz",))
                xdoz_list = find_by_ext(src, (".xdoz",))

                # Maps to find a target model folder:
                # - scoped: (parent_posix, xdm_stem_lower) -> Path(model_root)
                # - global: xdm_stem_lower -> Path(model_root)
                scoped_map: Dict[tuple[str, str], Path] = {}
                global_map: Dict[str, Path] = {}

                # 1) Process all XDMZ first (preserve tree in out_root/<rel_parent>/)
                total_xdmz = max(len(xdmz_list), 1)
                for i, xdmz_file in enumerate(xdmz_list, start=1):
                    pct = 20 + int(35 * (i / total_xdmz))  # 20→55
                    progress.progress(min(pct, 55), text=f"Data model: {xdmz_file.name}")

                    # Extract just this model to read its *_datamodel.xdm
                    sub_tmp = ensure_dir(tmp / f"__xdmz_{xdmz_file.stem}")
                    with zipfile.ZipFile(xdmz_file) as zf:
                        zf.extractall(sub_tmp)

                    dm_files = find_datamodel_files(sub_tmp)

                    rel_parent = xdmz_file.relative_to(src).parent  # keep original tree
                    otbi_root = ensure_dir(out_root / safe_path_from_rel(rel_parent))
                    model_root = unique_subdir(otbi_root, xdmz_file.stem)
                    catalog_dir = ensure_dir(model_root / "Catalog")
                    shutil.copy2(xdmz_file, catalog_dir / xdmz_file.name)

                    key = (rel_parent.as_posix(), xdmz_file.stem.lower())
                    scoped_map[key] = model_root
                    global_map[xdmz_file.stem.lower()] = model_root

                    for dm in dm_files:
                        try:
                            datasets, valuesets = parse_datamodel_xdm(dm)
                        except Exception as e:
                            st.warning(f"Failed to parse {dm.name}: {e}")
                            continue
                        created_paths += write_sql_otbi(
                            model_root,
                            datasets,
                            valuesets,
                            header_title=f"",
                        )

                # 2) Process all XDOZ next (preserve tree + scoped matching)
                total_xdoz = max(len(xdoz_list), 1)
                for j, xdoz_file in enumerate(xdoz_list, start=1):
                    pct = 55 + int(25 * (j / total_xdoz))  # 55→80
                    progress.progress(min(pct, 80), text=f"Report: {xdoz_file.name}")

                    rel_parent = xdoz_file.relative_to(src).parent
                    otbi_root = ensure_dir(out_root / safe_path_from_rel(rel_parent))

                    # Parse dataModel url from the report
                    dm_url = read_report_datamodel_url(xdoz_file)
                    target_model_root: Optional[Path] = None

                    if dm_url:
                        dm_stem = Path(dm_url).stem.lower()
                        # 2.1 try current folder scope, then walk up ancestors
                        found = False
                        for scope in walk_up_rel_paths(rel_parent):
                            key = (scope, dm_stem)
                            if key in scoped_map:
                                target_model_root = scoped_map[key]
                                found = True
                                break
                        # 2.2 fallback to global map
                        if not found and dm_stem in global_map:
                            target_model_root = global_map[dm_stem]

                    # 2.3 no match → put under this folder's _Orphan
                    if target_model_root is None:
                        target_model_root = ensure_dir(otbi_root / "_Orphan")

                    # Copy xdoz to Catalog of the chosen target
                    catalog_dir = ensure_dir(target_model_root / "Catalog")
                    dest = catalog_dir / xdoz_file.name
                    i = 1
                    while dest.exists():
                        dest = catalog_dir / f"{xdoz_file.stem}_{i}{xdoz_file.suffix}"
                        i += 1
                    shutil.copy2(xdoz_file, dest)
                    created_paths.append(dest)

                    # Extract templates beside it
                    created_paths += extract_templates_from_xdoz(xdoz_file, target_model_root)

                if not xdmz_list and not xdoz_list:
                    st.warning("No .xdmz or .xdoz found inside the .xdrz.")

            else:
                st.error("Unsupported file type.")

            # ---- pack + show ----
            if created_paths:
                progress.progress(90, text="Packing ZIP…")
                zip_bytes = zip_folder(out_root)
                progress.progress(100, text="Done ✅")

                # Download button ABOVE preview
                st.download_button(
                    label="⬇️ Download ZIP",
                    data=zip_bytes,
                    file_name=f"{out_root.name}.zip",
                    mime="application/zip",
                    use_container_width=True,
                )

                with st.container(border=True):
             
                    st.subheader("Summary")
                    st.write(f"**Uploaded:** {uploaded.name}")
                    st.write(f"**Type:** {ext}")
                    st.write(f"**Items created/copied:** {len(created_paths)}")
                    st.write(f"**Top-level folder in ZIP:** `{out_root.name}`")


                # SQL preview
                if show_preview:
                    sql_files = [p for p in created_paths if p.suffix.lower() == ".sql"]
                    if sql_files:
                        st.divider()
                        st.subheader("SQL Preview")
                        for p in sorted(sql_files)[:20]:
                            pretty = p.relative_to(out_root).as_posix()
                            with st.expander(pretty):
                                try:
                                    lines = p.read_text(encoding="utf-8").splitlines()
                                except UnicodeDecodeError:
                                    lines = p.read_text(encoding="latin-1").splitlines()
                                st.code("\n".join(lines[:int(limit_preview)]) or "-- (empty)", language="sql")
                    else:
                        st.caption("No .sql files to preview.")
            else:
                st.warning("No outputs were generated.")

        except Exception as e:
            st.error("Unexpected error.")
            st.exception(e)

else:
    with st.container(border=True):
        st.write("💡 Drop an `.xdmz`, `.xdrz`, or `.xdoz` to begin.")
