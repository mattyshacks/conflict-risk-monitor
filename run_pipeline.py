"""Run the whole pipeline: download -> clean and check -> load into the database.

It handles two files: the deaths per country and year, and the same deaths
split by type of violence.

Usage:
    python run_pipeline.py                     download the latest data, then build
    python run_pipeline.py --skip-download     rebuild from the files already in data/raw/
    python run_pipeline.py --source totals.csv --type-source by_type.csv
                                               use CSVs you downloaded by hand
"""

import argparse

from conflict_monitor import analysis, config, ingest, transform


def main() -> None:
    parser = argparse.ArgumentParser(description="Build the conflict deaths database.")
    parser.add_argument("--source", help="Path to a local CSV of totals to use instead of downloading.")
    parser.add_argument(
        "--type-source", help="Path to a local CSV split by type of violence (needed with --source)."
    )
    parser.add_argument(
        "--skip-download",
        action="store_true",
        help="Reuse the raw files already in data/raw/.",
    )
    args = parser.parse_args()
    # Both files must come from the same place, or the database could mix two releases.
    if bool(args.source) != bool(args.type_source):
        parser.error("--source and --type-source must be used together.")

    # 1. Ingest
    if args.source:
        raw_file = ingest.use_local_file(args.source)
        raw_type_file = ingest.use_local_file(
            args.type_source,
            dest=config.RAW_TYPE_FILE,
            metadata_file=config.RAW_TYPE_METADATA_FILE,
            source_page=config.TYPE_SOURCE_PAGE,
        )
        print(f"[1/3] Using local files: {args.source} and {args.type_source}")
    elif args.skip_download:
        raw_file, raw_type_file = config.RAW_FILE, config.RAW_TYPE_FILE
        print(f"[1/3] Reusing raw files in {config.RAW_DIR}")
    else:
        print("[1/3] Downloading from Our World in Data ...")
        raw_file = ingest.download()
        raw_type_file = ingest.download(
            url=config.TYPE_DATA_URL,
            dest=config.RAW_TYPE_FILE,
            metadata_file=config.RAW_TYPE_METADATA_FILE,
            source_page=config.TYPE_SOURCE_PAGE,
        )
        print(f"      Saved to {raw_file}")
        print(f"      and {raw_type_file}")

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

    raw_by_type = transform.load_raw(raw_type_file)
    clean_by_type = transform.clean_by_type(raw_by_type)
    print(
        f"      Split by type of violence: {len(clean_by_type):,} rows, "
        f"{clean_by_type['year'].min()}-{clean_by_type['year'].max()}."
    )

    # 3. Load
    rows = transform.load_to_sqlite(clean)
    type_rows = transform.load_to_sqlite(clean_by_type, table=transform.TYPE_TABLE)
    print(f"[3/3] Loaded {rows:,} rows and {type_rows:,} rows by type into {config.DB_PATH}")

    # Cross-checks.
    con = analysis.connect()
    try:
        check = analysis.reconciliation(con)
        type_check = analysis.type_check(con)
    finally:
        con.close()

    # Do our country totals match the source's own World figure?
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

    # Do the types add up to the totals?
    if type_check.empty:
        print("Check: WARNING, the two files have no place and year in common.")
    elif (type_check["difference"] == 0).all():
        print(f"Check: the types add up to the total in all {len(type_check):,} places and years.")
    else:
        gaps = type_check[type_check["difference"] != 0]
        worst = gaps.loc[gaps["difference"].abs().idxmax()]
        print(
            f"Check: WARNING, the types do not add up to the total in {len(gaps):,} places and years. "
            f"Largest gap is {int(worst['difference']):,} deaths for {worst['entity']} in {int(worst['year'])}."
        )

    print("\nDone. Start the dashboard with:  streamlit run app.py")


if __name__ == "__main__":
    main()
