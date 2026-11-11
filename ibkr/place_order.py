#!/usr/bin/env python3
"""Place a paper market order via ib_insync, print the fill, and attach a
GTC stop-loss. --stop is required -- there is no path to an unprotected
position through this script.

Usage:
    python3 place_order.py SYMBOL QTY [BUY|SELL] --stop PERCENT

Example:
    python3 place_order.py XLE 1 BUY --stop 5
    (buys 1 share of XLE, then places a GTC stop-sell 5% below the fill price)
"""

import argparse
import sys

from ib_insync import IB, StopOrder, Stock

HOST = "127.0.0.1"
PORT = 4002  # IB Gateway paper trading API port
FILL_TIMEOUT_SECONDS = 30


def parse_args():
    parser = argparse.ArgumentParser(
        description="Place a paper market order with a mandatory stop-loss.",
    )
    parser.add_argument("symbol")
    parser.add_argument("qty", type=float)
    parser.add_argument("side", nargs="?", default="BUY", choices=["BUY", "SELL"])
    parser.add_argument(
        "--stop",
        type=float,
        required=True,
        help="Stop-loss distance from fill price, in percent (e.g. 5 for 5%%). Required.",
    )
    return parser.parse_args()


def main():
    args = parse_args()
    symbol = args.symbol.upper()

    ib = IB()
    ib.connect(HOST, PORT, clientId=4, timeout=15)

    contract = Stock(symbol, "SMART", "USD")
    ib.qualifyContracts(contract)

    from ib_insync import MarketOrder

    order = MarketOrder(args.side, args.qty)
    trade = ib.placeOrder(contract, order)

    for _ in range(FILL_TIMEOUT_SECONDS):
        ib.sleep(1)
        if trade.orderStatus.status == "Filled":
            break

    if trade.orderStatus.status != "Filled":
        print(f"Order not filled after {FILL_TIMEOUT_SECONDS}s -- status: {trade.orderStatus.status}")
        # Cancel the still-working market order. Leaving it live (e.g. when the
        # market is closed) would let it fill later with no stop attached --
        # exactly the unprotected position this script exists to prevent.
        ib.cancelOrder(order)
        for _ in range(10):
            ib.sleep(1)
            if trade.orderStatus.status in ("Cancelled", "ApiCancelled", "Filled"):
                break
        if trade.orderStatus.filled <= 0:
            print(f"Unfilled order cancelled (status: {trade.orderStatus.status}). No position, no stop needed.")
            ib.disconnect()
            sys.exit(1)
        # Fully or partially filled during the cancel window: fall through and
        # attach a stop sized to the shares actually filled.
        print(f"{trade.orderStatus.filled} share(s) filled before cancel -- attaching stop to those.")

    filled_qty = trade.orderStatus.filled
    fill = trade.fills[-1]
    fill_price = trade.orderStatus.avgFillPrice or fill.execution.avgPrice
    print(f"FILLED  {args.side} {args.qty} {symbol}")
    print(f"  price:   {fill_price}")
    print(f"  shares:  {fill.execution.shares}")
    print(f"  time:    {fill.execution.time}")
    print(f"  account: {fill.execution.acctNumber}")

    # A BUY needs a protective SELL stop below the fill; a SELL (short) needs
    # a protective BUY stop above it.
    if args.side == "BUY":
        stop_price = round(fill_price * (1 - args.stop / 100), 2)
        stop_action = "SELL"
    else:
        stop_price = round(fill_price * (1 + args.stop / 100), 2)
        stop_action = "BUY"

    stop_order = StopOrder(stop_action, filled_qty, stop_price)
    stop_order.tif = "GTC"  # explicit -- account presets otherwise silently default to DAY
    stop_trade = ib.placeOrder(contract, stop_order)
    ib.sleep(2)

    print(f"STOP    {stop_action} {filled_qty} {symbol} @ {stop_price} (GTC, {args.stop}% from fill)")
    print(f"  status:  {stop_trade.orderStatus.status}")
    print(f"  orderId: {stop_trade.order.orderId}")

    ib.disconnect()


if __name__ == "__main__":
    main()
