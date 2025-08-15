# BI Publisher Extractor (XDMZ / XDRZ / XDOZ)

**Features**
- **XDMZ** → extract SQL from `dataSets` and `valueSets` found in `*_datamodel.xdm`.
- **XDRZ** → process all inner `.xdmz` (SQL) and extract templates from all inner `.xdoz`.
- **XDOZ** → copy `.rtf`, `.xsl`, `.xlsx`, `.xls`, `.xlsm`, `.csv` into `templates/`.
- Everything runs in a **temporary directory**, zipped for download, and **auto-cleaned**.

**Output Layout**
