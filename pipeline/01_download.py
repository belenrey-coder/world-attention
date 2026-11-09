"""Step 1: download aurman/GoogleTrendArchive (configs trending_queries + locations).

Writes the original CSVs to data/raw/ and a parquet copy of the main table
(data/raw/trending_queries.parquet, all columns as strings) for fast reloads.
"""
import shutil
import sys
import warnings
from pathlib import Path

warnings.filterwarnings("ignore")

import pandas as pd
import yaml  # installed with huggingface_hub
from huggingface_hub import HfApi, hf_hub_download

REPO = "aurman/GoogleTrendArchive"
ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"
RAW.mkdir(parents=True, exist_ok=True)


def config_files():
    """Read the dataset card's `configs` to find which file each config uses."""
    readme = hf_hub_download(REPO, "README.md", repo_type="dataset", local_dir=RAW)
    text = Path(readme).read_text()
    meta = yaml.safe_load(text.split("---")[1])
    return {c["config_name"]: c["data_files"] for c in meta["configs"]}


def main():
    files = config_files()
    wanted = {k: files[k] for k in ("trending_queries", "locations")}
    info = HfApi().dataset_info(REPO, files_metadata=True)
    sizes = {s.rfilename: s.size or 0 for s in info.siblings}
    need = sum(sizes[f] for f in wanted.values())
    free = shutil.disk_usage(RAW).free
    # CSV + parquet copy + interim outputs: require 4x the download size free.
    print(f"Download size: {need/1e9:.2f} GB; free disk: {free/1e9:.1f} GB")
    if free < 4 * need:
        sys.exit("Not enough free disk space (need ~4x the download). Aborting.")

    paths = {}
    for cfg, fname in wanted.items():
        print(f"Downloading {cfg}: {fname}")
        paths[cfg] = Path(hf_hub_download(REPO, fname, repo_type="dataset", local_dir=RAW))

    locs = pd.read_csv(paths["locations"], dtype=str, keep_default_na=False)
    print(f"\n[locations] rows={len(locs):,} columns={list(locs.columns)}")

    df = pd.read_csv(paths["trending_queries"], dtype=str, keep_default_na=False)
    print(f"\n[trending_queries] rows={len(df):,}")
    print(f"columns={list(df.columns)}")
    print(df.head(3).T.to_string())
    for col in ("start_time", "end_time", "collection_date"):
        if col in df.columns:
            s = df[col][df[col] != ""]
            print(f"{col}: min={s.min()}  max={s.max()}  (as stored, string sort)")
    df.to_parquet(RAW / "trending_queries.parquet", index=False)
    print(f"\nWrote {RAW/'trending_queries.parquet'}")


if __name__ == "__main__":
    main()
