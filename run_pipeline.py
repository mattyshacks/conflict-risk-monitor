"""Run the whole pipeline: download -> clean and check -> load into the database.

Usage:
    python run_pipeline.py                       download the latest data, then build
    python run_pipeline.py --skip-download       rebuild from the file already in data/raw/
    python run_pipeline.py --source my_file.csv  use a CSV you downloaded by hand
"""

import argparse

from conflict_monitor import analysis, config, ingest, transform


def main() -> None:
    parser = argparse.ArgumentParser(description="Build the conflict deaths database.")
    parser.add_argument("--source", help="Path to a local CSV to use instead of downloading.")
    parser.add_argument(
        "--skip-download",
        action="store_true",
        help="Reuse the raw file already in data/raw/.",
    )
    args = parser.parse_args()

    # 1. Ingest
    if args.source:
        raw_file = ingest.use_local_file(args.source)
        print(f"[1/3] Using local file: {args.source}")
    elif args.skip_download:
        raw_file = config.RAW_FILE
        print(f"[1/3] Reusing raw file: {raw_file}")
    else:
        print("[1/3] Downloading from Our World in Data ...")
        raw_file = ingest.download()
        print(f"      Saved to {raw_file}")

    # 2. Clean and check
    raw = transform.load_raw(raw_file)
    clean = transform.clean(raw)
    countries = clean[clean["entity_type"] == "country"]
    print(
        f"[2/3] Cleaned {len(raw):,} raw rows into {len(clean):,} rows: "
        f"{countries['entity'].nunique()} countries, "
        f"{clean['year'].min()}-{clean['year'].max()}."
    )
    preliminary_years = sorted(
        int(y) for y in clean.loc[clean["is_preliminary"] == 1, "year"].unique()
    )
    if preliminary_years:
        print(f"      Preliminary (part-year) data flagged for: {preliminary_years}")

    # 3. Load
    rows = transform.load_to_sqlite(clean)
    print(f"[3/3] Loaded {rows:,} rows into {config.DB_PATH}")

    # Cross-check: do our country totals match the source's own World figure?
    con = analysis.connect()
    try:
        check = analysis.reconciliation(con)
    finally:
        con.close()
    if check.empty:
        print("Check: no World row in the source, so no cross-check was possible.")
    elif (check["difference"] == 0).all():
        print("Check: country totals match the source's World figure in every year.")
    else:
        worst = check.loc[check["difference"].abs().idxmax()]
        print(
            "Check: country totals vs the source's World figure. "
            f"Largest gap is {int(worst['difference']):,} deaths in {int(worst['year'])} "
            f"(World figure {int(worst['world_figure']):,})."
        )

    print("\nDone. Start the dashboard with:  streamlit run app.py")


if __name__ == "__main__":
    main()
