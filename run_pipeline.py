"""Run the whole pipeline: download -> clean and check -> load into the database.

It handles three files: the deaths per country and year, the same deaths
split by type of violence, and the region each country is in.

Usage:
    python run_pipeline.py                     download the latest data, then build
    python run_pipeline.py --skip-download     rebuild from the files already in data/raw/
    python run_pipeline.py --source totals.csv --type-source by_type.csv --region-source regions.csv
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
        "--region-source", help="Path to a local CSV of UCDP regions (needed with --source)."
    )
    parser.add_argument(
        "--skip-download",
        action="store_true",
        help="Reuse the raw files already in data/raw/.",
    )
    args = parser.parse_args()
    # All files must come from the same place, or the database could mix releases.
    given = [bool(args.source), bool(args.type_source), bool(args.region_source)]
    if any(given) and not all(given):
        parser.error("--source, --type-source and --region-source must be used together.")

    # 1. Ingest
    if args.source:
        raw_file = ingest.use_local_file(args.source)
        raw_type_file = ingest.use_local_file(
            args.type_source,
            dest=config.RAW_TYPE_FILE,
            metadata_file=config.RAW_TYPE_METADATA_FILE,
            source_page=config.TYPE_SOURCE_PAGE,
        )
        raw_region_file = ingest.use_local_file(
            args.region_source,
            dest=config.RAW_REGION_FILE,
            metadata_file=config.RAW_REGION_METADATA_FILE,
            source_page=config.REGION_SOURCE_PAGE,
        )
        print(
            f"[1/3] Using local files: {args.source}, {args.type_source} and {args.region_source}"
        )
    elif args.skip_download:
        raw_file, raw_type_file = config.RAW_FILE, config.RAW_TYPE_FILE
        raw_region_file = config.RAW_REGION_FILE
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
        raw_region_file = ingest.download(
            url=config.REGION_DATA_URL,
            dest=config.RAW_REGION_FILE,
            metadata_file=config.RAW_REGION_METADATA_FILE,
            source_page=config.REGION_SOURCE_PAGE,
        )
        print(f"      Saved to {raw_file},")
        print(f"      {raw_type_file}")
        print(f"      and {raw_region_file}")

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

    raw_regions = transform.load_raw(raw_region_file)
    regions = transform.clean_regions(raw_regions)
    transform.check_every_place_has_region(clean, regions)  # stops here if a place is missing
    print(
        f"      Regions: {len(regions):,} places in {regions['region'].nunique()} regions, "
        f"including {len(regions) - len(raw_regions)} placed by hand "
        "(see EXTRA_REGIONS in config.py)."
    )

    # 3. Load
    rows = transform.load_to_sqlite(clean)
    type_rows = transform.load_to_sqlite(clean_by_type, table=transform.TYPE_TABLE)
    transform.load_to_sqlite(regions, table=transform.REGION_TABLE)
    print(
        f"[3/3] Loaded {rows:,} rows, {type_rows:,} rows by type and the region list "
        f"into {config.DB_PATH}"
    )

    # Cross-checks.
    con = analysis.connect()
    try:
        check = analysis.reconciliation(con)
        type_check = analysis.type_check(con)
        region_check = analysis.region_check(con)
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

    # Do our country totals per region match UCDP's own region figures?
    # Small gaps are expected (see analysis.region_check), so this only reports them.
    if region_check.empty:
        print("Check: WARNING, no region figures in the source to compare with.")
    else:
        gaps = region_check[region_check["difference"] != 0]
        if gaps.empty:
            print("Check: country totals match UCDP's region figures in every region and year.")
        else:
            worst = gaps.loc[gaps["difference"].abs().idxmax()]
            print(
                f"Check: country totals match UCDP's region figures in "
                f"{len(region_check) - len(gaps):,} of {len(region_check):,} region-years. "
                f"Largest gap is {int(worst['difference']):,} deaths "
                f"({worst['region']}, {int(worst['year'])}); UCDP files a few conflicts "
                "under a neighbouring region."
            )

    print("\nDone. Start the dashboard with:  streamlit run app.py")


if __name__ == "__main__":
    main()
