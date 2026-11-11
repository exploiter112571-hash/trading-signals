#!/usr/bin/env python3
"""Place a paper market order via ib_insync, print the fill, and attach a
GTC stop-loss. --stop is required -- there is no path to an unprotected
position through this script.

Usage:
    python3 place_order.py SYMBOL QTY [BUY|SELL] --stop PERCENT [--exchange EX --currency CUR]

Example:
    python3 place_order.py XLE 1 BUY --stop 5
    (buys 1 share of XLE, then places a GTC stop-sell 5% below the fill price)

    python3 place_order.py SHEL 1 BUY --stop 5 --exchange LSE --currency GBP
    (non-US listing: route to the home exchange in its local currency)
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
    parser.add_argument("--exchange", default="SMART",
                        help="Primary listing exchange (default SMART for US; e.g. LSE, SBF, BVME, IBIS). Orders are always SMART-routed.")
    parser.add_argument("--currency", default="USD",
                        help="Listing currency (default USD; e.g. GBP, EUR).")
    return parser.parse_args()


def tick_for(ib, contract, price):
    """Price increment the exchange accepts at this price level (from IB's
    market rules). Falls back to 0.01 if the rule can't be read."""
    try:
        details = ib.reqContractDetails(contract)[0]
        rule_id = int(details.marketRuleIds.split(",")[0])
        increment = 0.01
        for rule in ib.reqMarketRule(rule_id):
            if price >= rule.lowEdge:
                increment = rule.increment
        return increment
    except Exception as exc:
        print(f"  (could not read market rule, using 0.01 tick: {exc})")
        return 0.01


def round_to_tick(price, tick):
    return round(round(price / tick) * tick, 10)


def main():
    args = parse_args()
    symbol = args.symbol.upper()

    ib = IB()
    ib.connect(HOST, PORT, clientId=4, timeout=15)

    # Always SMART-route; a named exchange is passed as the primary listing.
    # Direct-routing to e.g. LSE is rejected by the Gateway's precautionary
    # settings (Error 10311 -> "Order was discarded").
    exchange = args.exchange.upper()
    if exchange == "SMART":
        contract = Stock(symbol, "SMART", args.currency.upper())
    else:
        contract = Stock(symbol, "SMART", args.currency.upper(), primaryExchange=exchange)
    if not ib.qualifyContracts(contract):
        print(f"Unknown contract: {symbol} on {args.exchange} in {args.currency}")
        ib.disconnect()
        sys.exit(1)

    from ib_insync import MarketOrder

    order = MarketOrder(args.side, args.qty)
    order.tif = "DAY"  # explicit -- avoids the 10349 "TIF set by preset" warning
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
    print(f"FILLED  {args.side} {args.qty} {symbol} ({contract.primaryExchange or contract.exchange}, {contract.currency})")
    print(f"  price:   {fill_price}")
    print(f"  shares:  {fill.execution.shares}")
    print(f"  time:    {fill.execution.time}")
    print(f"  account: {fill.execution.acctNumber}")

    # A BUY needs a protective SELL stop below the fill; a SELL (short) needs
    # a protective BUY stop above it.
    # Round to the exchange's tick for this price level -- e.g. LSE uses
    # 0.2p steps between 200p and 500p, so a plain 2-decimal round (258.78p)
    # gets the stop rejected and leaves the position unprotected.
    if args.side == "BUY":
        raw_stop = fill_price * (1 - args.stop / 100)
        stop_action = "SELL"
    else:
        raw_stop = fill_price * (1 + args.stop / 100)
        stop_action = "BUY"
    stop_price = round_to_tick(raw_stop, tick_for(ib, contract, raw_stop))

    stop_order = StopOrder(stop_action, filled_qty, stop_price)
    stop_order.tif = "GTC"  # explicit -- account presets otherwise silently default to DAY
    stop_trade = ib.placeOrder(contract, stop_order)
    for _ in range(10):
        ib.sleep(1)
        if stop_trade.orderStatus.status in ("PreSubmitted", "Submitted", "Cancelled", "Inactive", "ApiCancelled"):
            break

    print(f"STOP    {stop_action} {filled_qty} {symbol} @ {stop_price} (GTC, {args.stop}% from fill)")
    print(f"  status:  {stop_trade.orderStatus.status}")
    print(f"  orderId: {stop_trade.order.orderId}")

    if stop_trade.orderStatus.status not in ("PreSubmitted", "Submitted"):
        reasons = "; ".join(l.message for l in stop_trade.log if l.message)
        print(f"!!! STOP NOT ACCEPTED ({stop_trade.orderStatus.status}) -- POSITION IS UNPROTECTED. {reasons}")
        ib.disconnect()
        sys.exit(3)

    ib.disconnect()


if __name__ == "__main__":
    main()
