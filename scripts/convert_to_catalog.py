#!/usr/bin/env python3
"""Convert .npy or .dbn bar data to NautilusTrader ParquetDataCatalog format.

Usage:
    python scripts/convert_to_catalog.py --input data/ --output data/catalog/
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent.parent))

from flof_matrix.nautilus.backtest_runner import BAR_DTYPE


def parse_args():
    parser = argparse.ArgumentParser(description="Convert data to NautilusTrader catalog")
    parser.add_argument("--input", type=str, default="data/",
                        help="Input directory containing .npy or .dbn files")
    parser.add_argument("--output", type=str, default="data/catalog/",
                        help="Output catalog directory")
    parser.add_argument("--instrument", type=str, default="ESH5",
                        help="Instrument symbol (e.g. ESH5, NQH5)")
    parser.add_argument("--venue", type=str, default="CME",
                        help="Venue name")
    return parser.parse_args()


def convert_npy_to_catalog(
    npy_path: Path,
    catalog_path: Path,
    instrument_str: str,
    venue_str: str,
) -> int:
    """Convert a .npy bar file to ParquetDataCatalog.

    Returns number of bars written.
    """
    import pandas as pd
    from nautilus_trader.persistence.catalog import ParquetDataCatalog
    from nautilus_trader.model.data import Bar, BarType, BarSpecification
    from nautilus_trader.model.enums import BarAggregation, PriceType, AggregationSource
    from nautilus_trader.model.identifiers import InstrumentId, Symbol, Venue
    from nautilus_trader.model.objects import Price, Quantity

    bars = np.load(str(npy_path))
    if len(bars) == 0:
        logging.warning("Empty file: %s", npy_path)
        return 0

    instrument_id = InstrumentId(Symbol(instrument_str), Venue(venue_str))
    bar_type = BarType(
        instrument_id,
        BarSpecification(1, BarAggregation.MINUTE, PriceType.LAST),
        AggregationSource.EXTERNAL,
    )

    nt_bars = []
    for i in range(len(bars)):
        ts = int(bars[i]["timestamp_ns"])
        o = float(bars[i]["open"])
        h = float(bars[i]["high"])
        l = float(bars[i]["low"])
        c = float(bars[i]["close"])
        v = max(float(bars[i]["volume"]), 1.0)

        h = max(h, o, c)
        l = min(l, o, c)

        nt_bar = Bar(
            bar_type=bar_type,
            open=Price.from_str(f"{o:.2f}"),
            high=Price.from_str(f"{h:.2f}"),
            low=Price.from_str(f"{l:.2f}"),
            close=Price.from_str(f"{c:.2f}"),
            volume=Quantity.from_str(f"{v:.0f}"),
            ts_event=ts,
            ts_init=ts,
        )
        nt_bars.append(nt_bar)

    catalog = ParquetDataCatalog(str(catalog_path))
    catalog.write_data(nt_bars)

    logging.info("Wrote %d bars to catalog at %s", len(nt_bars), catalog_path)
    return len(nt_bars)


def convert_dbn_to_catalog(
    dbn_path: Path,
    catalog_path: Path,
    instrument_str: str,
    venue_str: str,
) -> int:
    """Convert a .dbn file to ParquetDataCatalog via intermediate numpy conversion."""
    from flof_matrix.data.databento_adapter import DataBentoAdapter

    adapter = DataBentoAdapter()
    dbn_store = adapter.load_dbn(dbn_path)
    if dbn_store is None:
        return 0

    bars = adapter.dbn_to_bars(dbn_store)
    if len(bars) == 0:
        return 0

    # Save as temp npy then convert
    temp_path = dbn_path.with_suffix(".npy")
    np.save(str(temp_path), bars)
    count = convert_npy_to_catalog(temp_path, catalog_path, instrument_str, venue_str)
    temp_path.unlink(missing_ok=True)
    return count


def main():
    args = parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )

    input_dir = Path(args.input)
    catalog_path = Path(args.output)
    catalog_path.mkdir(parents=True, exist_ok=True)

    total = 0

    # Process .npy files
    for npy_file in sorted(input_dir.glob("*.npy")):
        logging.info("Converting %s ...", npy_file.name)
        count = convert_npy_to_catalog(npy_file, catalog_path, args.instrument, args.venue)
        total += count

    # Process .dbn files
    for dbn_file in sorted(input_dir.glob("*.dbn*")):
        logging.info("Converting %s ...", dbn_file.name)
        count = convert_dbn_to_catalog(dbn_file, catalog_path, args.instrument, args.venue)
        total += count

    logging.info("Total bars written to catalog: %d", total)
    logging.info("Catalog location: %s", catalog_path)


if __name__ == "__main__":
    main()
