# spread_trade_pl_calculator.py
"""Calculate total P/L for a paired long‑cash / short‑general‑credit trade on a TSE stock.

New in v0.3 (2025‑06‑28)
------------------------
* **Interactive mode** for user-friendly input prompts
* **Enhanced error handling** and input validation
* **Configurable settings** with default values
* **Auto‑fetch bid / ask** from Yahoo! Finance Japan (free, delayed).
* `--auto` CLI switch (or leave `--ask / --bid` blank) to enable live scraping.
* Logic unchanged for loan fee, management fee, consumption tax, dividend, spread.

⚠️  Disclaimer
--------------
Yahoo! Finance の気配値は 20 分遅れ・スクレイピング非公認です。実売買に用いる際は証券会社のリアルタイム板で必ず再確認してください。
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import date, datetime
import re
import sys
from typing import Optional

from dateutil.relativedelta import relativedelta

# -----------------------------
# Optional free data‑scraping
# -----------------------------
try:
    import requests
    from bs4 import BeautifulSoup  # type: ignore
except ImportError:  # library not installed → auto mode disabled
    requests = None  # type: ignore
    BeautifulSoup = None  # type: ignore


###############################################################################
# Configuration
###############################################################################

# 日興証券オンライン取引ベース
@dataclass
class DefaultConfig:
    LOAN_RATE: float = 0.014
    CONSUMPTION_TAX_RATE: float = 0.10
    MANAGEMENT_FEE_PER_CYCLE: float = 0
    WITHHOLDING_TAX_RATE: float = 0.20315


###############################################################################
# Helper functions
###############################################################################

def _days_inclusive(start: date, end: date) -> int:
    return (end - start).days + 1


def _count_passed_months(start: date, end: date) -> int:
    cnt = 0
    ann = start + relativedelta(months=+1)
    while ann <= end:
        cnt += 1
        ann += relativedelta(months=+1)
    return cnt


# ---------------------------------------------------------------------------
# Scraper: Yahoo! Finance Japan (free, delayed)
# ---------------------------------------------------------------------------

def fetch_bid_ask_yahoo(ticker: str) -> tuple[float, float]:
    """Return (ask, bid) as floats.

    ticker must be a 4‑digit string, e.g. "4751".
    Raises RuntimeError if value cannot be scraped.
    """

    if requests is None or BeautifulSoup is None:
        raise RuntimeError("requests / BeautifulSoup not installed – run `pip install requests bs4`." )

    url = f"https://finance.yahoo.co.jp/quote/{ticker}.T"
    headers = {"User-Agent": "Mozilla/5.0"}
    
    try:
        r = requests.get(url, headers=headers, timeout=10)
        if r.status_code != 200:
            raise RuntimeError(f"Failed to fetch Yahoo Finance page: HTTP {r.status_code}")

        soup = BeautifulSoup(r.text, "html.parser")

        # Search table rows containing the words "買気配" (bid) and "売気配" (ask)
        def _extract(label: str) -> float:
            tag = soup.find("th", string=re.compile(label))
            if tag and tag.find_next("td"):
                text = tag.find_next("td").get_text(strip=True).replace(",", "")
                return float(text)
            raise RuntimeError(f"Could not locate {label} on Yahoo page")

        bid = _extract("買気配")
        ask = _extract("売気配")
        return ask, bid
    except (requests.RequestException, ValueError, AttributeError) as e:
        raise RuntimeError(f"Failed to fetch bid/ask for {ticker}: {e}")


###############################################################################
# Core dataclasses
###############################################################################

@dataclass
class TradeParams:
    ticker: str
    qty: int
    start: date
    end: date
    ask_price: float  # long entry
    bid_price: float  # short entry
    dividend: float   # gross, per share
    loan_rate: float = DefaultConfig.LOAN_RATE
    consumption_tax_rate: float = DefaultConfig.CONSUMPTION_TAX_RATE
    management_fee_per_cycle: float = DefaultConfig.MANAGEMENT_FEE_PER_CYCLE
    withholding_tax_rate: float = DefaultConfig.WITHHOLDING_TAX_RATE
    spread_on_exit: bool = False  # pay spread again on exit?


@dataclass
class TradeResult:
    loan_fee: float
    consumption_tax: float
    management_fee: float
    dividend_received: float
    dividend_adjustment_paid: float
    entry_spread_cost: float
    exit_spread_cost: float

    def total_pre_tax(self) -> float:  # property style avoided for clarity
        return (
            self.dividend_received
            - self.dividend_adjustment_paid
            - self.loan_fee
            - self.consumption_tax
            - self.management_fee
            - self.entry_spread_cost
            - self.exit_spread_cost
        )

    def total_post_tax(self, withholding: float) -> float:
        return (
            self.dividend_received * (1 - withholding)
            - self.dividend_adjustment_paid
            - self.loan_fee
            - self.consumption_tax
            - self.management_fee
            - self.entry_spread_cost
            - self.exit_spread_cost
        )


###############################################################################
# Calculation engine
###############################################################################

def calc_trade(p: TradeParams) -> TradeResult:
    days = _days_inclusive(p.start, p.end)
    months_passed = _count_passed_months(p.start, p.end)

    notional = p.bid_price * p.qty
    loan_fee = notional * p.loan_rate * days / 365.0
    consumption_tax = loan_fee * p.consumption_tax_rate
    management_fee = p.management_fee_per_cycle * months_passed

    dividend_received = p.dividend * p.qty
    dividend_paid = p.dividend * p.qty

    entry_spread = (p.ask_price - p.bid_price) * p.qty
    exit_spread = entry_spread if p.spread_on_exit else 0.0

    return TradeResult(
        loan_fee=round(loan_fee, 2),
        consumption_tax=round(consumption_tax, 2),
        management_fee=round(management_fee, 2),
        dividend_received=round(dividend_received, 2),
        dividend_adjustment_paid=round(dividend_paid, 2),
        entry_spread_cost=round(entry_spread, 2),
        exit_spread_cost=round(exit_spread, 2),
    )


###############################################################################
# CLI
###############################################################################

def _parse_args():
    p = argparse.ArgumentParser(description="Cash‑and‑carry P/L calculator (auto‑quote capable)")

    p.add_argument("--interactive", "-i", action="store_true", 
                   help="Interactive mode with prompts")
    p.add_argument("ticker", nargs="?", help="TSE 4‑digit code, e.g. 4751")
    p.add_argument("qty", type=int, nargs="?", help="Shares (e.g. 100)")
    p.add_argument("start", nargs="?", help="Start date YYYY‑MM‑DD")
    p.add_argument("end", nargs="?", help="End date YYYY‑MM‑DD")
    p.add_argument("dividend", type=float, nargs="?", help="Gross dividend per share, JPY")

    p.add_argument("--ask", type=float, default=None, help="Ask price (optional if --auto)")
    p.add_argument("--bid", type=float, default=None, help="Bid price (optional if --auto)")
    p.add_argument("--auto", action="store_true", help="Fetch bid/ask from Yahoo! Finance")

    p.add_argument("--loan-rate", type=float, default=DefaultConfig.LOAN_RATE)
    p.add_argument("--mgmt-fee", type=float, default=DefaultConfig.MANAGEMENT_FEE_PER_CYCLE)
    p.add_argument("--spread-exit", action="store_true")

    return p.parse_args()


def main() -> None:
    ns = _parse_args()

    # Interactive mode
    if ns.interactive or (ns.ticker is None):
        params = interactive_input()
    else:
        # CLI mode with validation
        if ns.start >= ns.end:
            raise SystemExit("Start date must be before end date")
        
        if ns.qty <= 0:
            raise SystemExit("Quantity must be positive")

        if ns.auto:
            try:
                ask, bid = fetch_bid_ask_yahoo(ns.ticker)
            except RuntimeError as e:
                raise SystemExit(f"Failed to fetch prices: {e}")
        else:
            if ns.ask is None or ns.bid is None:
                raise SystemExit("Either --auto or both --ask and --bid must be supplied.")
            ask, bid = ns.ask, ns.bid

        params = TradeParams(
            ticker=ns.ticker,
            qty=ns.qty,
            start=datetime.strptime(ns.start, "%Y-%m-%d").date(),
            end=datetime.strptime(ns.end, "%Y-%m-%d").date(),
            ask_price=ask,
            bid_price=bid,
            dividend=ns.dividend,
            loan_rate=ns.loan_rate,
            management_fee_per_cycle=ns.mgmt_fee,
            spread_on_exit=ns.spread_exit,
        )

    res = calc_trade(params)

    print("================  P/L SUMMARY  ================")
    print(f"Ticker            : {params.ticker}")
    print(f"Qty               : {params.qty}")
    print(f"Period            : {params.start} → {params.end}")
    print("-----------------------------------------------")
    print(f"Bid / Ask         : {params.bid_price:,.2f} / {params.ask_price:,.2f}")
    print(f"Loan fee          : {res.loan_fee:,.0f} JPY")
    print(f"Consumption tax   : {res.consumption_tax:,.0f} JPY")
    print(f"Management fee    : {res.management_fee:,.0f} JPY")
    print(f"Dividend received : {res.dividend_received:,.0f} JPY (gross)")
    print(f"Dividend paid     : {res.dividend_adjustment_paid:,.0f} JPY")
    print(f"Entry spread cost : {res.entry_spread_cost:,.0f} JPY")
    if params.spread_on_exit:
        print(f"Exit spread cost  : {res.exit_spread_cost:,.0f} JPY")
    print("-----------------------------------------------")
    print(f"TOTAL (pre‑tax)   : {res.total_pre_tax():,.0f} JPY")
    print(f"TOTAL (post‑tax)  : {res.total_post_tax(params.withholding_tax_rate):,.0f} JPY (with w/h)")


###############################################################################
# Interactive mode functions
###############################################################################

def get_input_with_validation(prompt: str, validator=None, error_msg: str = "無効な入力です。") -> str:
    """Get user input with optional validation."""
    while True:
        try:
            value = input(prompt).strip()
            if validator is None:
                return value
            if validator(value):
                return value
            print(error_msg)
        except KeyboardInterrupt:
            print("\n操作がキャンセルされました。")
            sys.exit(0)
        except EOFError:
            print("\n入力が終了しました。")
            sys.exit(0)


def validate_ticker(ticker: str) -> bool:
    """Validate ticker format (4 digits)."""
    return re.match(r'^\d{4}$', ticker) is not None


def validate_date(date_str: str) -> bool:
    """Validate date format (YYYY-MM-DD)."""
    try:
        datetime.strptime(date_str, "%Y-%m-%d")
        return True
    except ValueError:
        return False


def validate_positive_int(value: str) -> bool:
    """Validate positive integer."""
    try:
        return int(value) > 0
    except ValueError:
        return False


def validate_positive_float(value: str) -> bool:
    """Validate positive float."""
    try:
        return float(value) >= 0
    except ValueError:
        return False


def validate_yes_no(value: str) -> bool:
    """Validate yes/no input."""
    return value.lower() in ['y', 'yes', 'n', 'no', 'はい', 'いいえ']


def interactive_input() -> TradeParams:
    """対話形式でトレードパラメータを入力する"""
    print("================  スプレッド取引P/L計算器  ================")
    print("対話形式でトレード情報を入力してください。")
    print("（Ctrl+C で終了）")
    print()
    
    # Ticker
    ticker = get_input_with_validation(
        "銘柄コード（4桁）: ",
        validate_ticker,
        "4桁の数字を入力してください（例：4751）"
    )
    
    # Quantity
    qty_str = get_input_with_validation(
        "株数: ",
        validate_positive_int,
        "正の整数を入力してください（例：100）"
    )
    qty = int(qty_str)
    
    # Start date
    start_str = get_input_with_validation(
        "開始日（YYYY-MM-DD）: ",
        validate_date,
        "YYYY-MM-DD形式で入力してください（例：2025-01-01）"
    )
    start = datetime.strptime(start_str, "%Y-%m-%d").date()
    
    # End date
    while True:
        end_str = get_input_with_validation(
            "終了日（YYYY-MM-DD）: ",
            validate_date,
            "YYYY-MM-DD形式で入力してください（例：2025-03-31）"
        )
        end = datetime.strptime(end_str, "%Y-%m-%d").date()
        if end > start:
            break
        print("終了日は開始日より後の日付を入力してください。")
    
    # Dividend
    dividend_str = get_input_with_validation(
        "1株当たり配当金（円）: ",
        validate_positive_float,
        "0以上の数値を入力してください（例：50.0）"
    )
    dividend = float(dividend_str)
    
    # Auto fetch or manual input
    auto_fetch = get_input_with_validation(
        "Yahoo! Financeから自動取得しますか？ (y/n): ",
        validate_yes_no,
        "y（はい）またはn（いいえ）を入力してください"
    ).lower() in ['y', 'yes', 'はい']
    
    if auto_fetch:
        try:
            print(f"Yahoo! Financeから{ticker}の気配値を取得中...")
            ask, bid = fetch_bid_ask_yahoo(ticker)
            print(f"取得完了: 売気配={ask:,.2f}円, 買気配={bid:,.2f}円")
        except RuntimeError as e:
            print(f"自動取得に失敗しました: {e}")
            print("手動で入力してください。")
            auto_fetch = False
    
    if not auto_fetch:
        ask_str = get_input_with_validation(
            "売気配（Ask価格）: ",
            validate_positive_float,
            "正の数値を入力してください"
        )
        ask = float(ask_str)
        
        bid_str = get_input_with_validation(
            "買気配（Bid価格）: ",
            validate_positive_float,
            "正の数値を入力してください"
        )
        bid = float(bid_str)
    
    # Optional parameters with defaults
    print("\n--- オプション設定（Enterでデフォルト値使用）---")
    
    loan_rate_input = input(f"貸株料率 (デフォルト: {DefaultConfig.LOAN_RATE}): ").strip()
    loan_rate = float(loan_rate_input) if loan_rate_input else DefaultConfig.LOAN_RATE
    
    mgmt_fee_input = input(f"管理手数料/月 (デフォルト: {DefaultConfig.MANAGEMENT_FEE_PER_CYCLE}円): ").strip()
    mgmt_fee = float(mgmt_fee_input) if mgmt_fee_input else DefaultConfig.MANAGEMENT_FEE_PER_CYCLE
    
    spread_exit_input = input("決済時もスプレッドコストを考慮しますか？ (y/n, デフォルト: n): ").strip()
    spread_exit = spread_exit_input.lower() in ['y', 'yes', 'はい'] if spread_exit_input else False
    
    return TradeParams(
        ticker=ticker,
        qty=qty,
        start=start,
        end=end,
        ask_price=ask,
        bid_price=bid,
        dividend=dividend,
        loan_rate=loan_rate,
        management_fee_per_cycle=mgmt_fee,
        spread_on_exit=spread_exit,
    )


if __name__ == "__main__":
    main()
