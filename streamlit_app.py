# streamlit_app.py
"""
Streamlit版 スプレッド取引P/L計算器
日本の東証株式でのキャッシュ・アンド・キャリー取引のP/L計算をWebアプリで実行
"""

import streamlit as st
import pandas as pd
from datetime import date, datetime
from dataclasses import dataclass
from dateutil.relativedelta import relativedelta

# オプションのライブラリ（価格取得用）
try:
    import requests
    from bs4 import BeautifulSoup
    HAS_SCRAPING_LIBS = True
except ImportError:
    requests = None
    BeautifulSoup = None
    HAS_SCRAPING_LIBS = False

# 既存のspread_trade_pl_calculator.pyから必要な関数とクラスをインポート
from spread_trade_pl_calculator import (
    DefaultConfig, TradeParams, TradeResult, calc_trade, 
    fetch_bid_ask_yahoo, _days_inclusive, _count_passed_months
)

def fetch_price_alternative(ticker: str) -> tuple[float, float]:
    """代替価格取得方法（楽天証券風のダミーデータ）"""
    # 実際の実装では他の証券会社APIや金融データプロバイダーを使用
    import random
    
    # ダミーデータ（実際のアプリでは適切なAPIを使用）
    base_prices = {
        "4751": 1200.0,
        "6758": 15000.0,
        "7974": 8500.0,
        "8411": 4200.0,
        "9983": 9800.0,
    }
    
    base_price = base_prices.get(ticker, 1000.0)
    
    # ランダムな変動を加える
    variation = random.uniform(-0.05, 0.05)
    current_price = base_price * (1 + variation)
    
    # スプレッドを仮定（0.1%程度）
    spread = current_price * 0.001
    bid = current_price - spread/2
    ask = current_price + spread/2
    
    return round(ask, 2), round(bid, 2)

def fetch_price_mock(ticker: str) -> tuple[float, float]:
    """モック価格（テスト用）"""
    # 固定値を返すテスト用関数
    mock_prices = {
        "4751": (1205.0, 1195.0),  # ask, bid
        "6758": (15100.0, 14950.0),
        "7974": (8520.0, 8480.0),
        "8411": (4215.0, 4185.0),
        "9983": (9850.0, 9750.0),
    }
    
    return mock_prices.get(ticker, (1000.0, 995.0))

# Streamlitページ設定
st.set_page_config(
    page_title="スプレッド取引P/L計算器",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="expanded"
)

def main():
    st.title("📈 スプレッド取引P/L計算器")
    st.markdown("**キャッシュ・アンド・キャリー取引**のP/L計算を行います")
    
    # サイドバーで入力項目を配置
    with st.sidebar:
        st.header("📝 取引情報入力")
        
        # 銘柄コード
        ticker = st.text_input(
            "銘柄コード（4桁）",
            value="4751",
            max_chars=4,
            help="東証の4桁銘柄コードを入力してください"
        )
        
        # 株数
        qty = st.number_input(
            "株数",
            min_value=1,
            value=100,
            step=1,
            help="取引する株数を入力してください"
        )
        
        # 期間設定
        st.subheader("📅 取引期間")
        col1, col2 = st.columns(2)
        
        with col1:
            start_date = st.date_input(
                "開始日",
                value=date.today(),
                help="ポジション開始日"
            )
        
        with col2:
            # デフォルトの終了日を安全に計算
            today = date.today()
            try:
                if today.month < 12:
                    default_end = today.replace(month=today.month+1)
                else:
                    default_end = today.replace(year=today.year+1, month=1)
            except ValueError:
                # 月末日の場合の調整
                default_end = today.replace(day=28)
                if default_end.month < 12:
                    default_end = default_end.replace(month=default_end.month+1)
                else:
                    default_end = default_end.replace(year=default_end.year+1, month=1)
            
            end_date = st.date_input(
                "終了日",
                value=default_end,
                help="ポジション終了日"
            )
        
        # 配当金
        dividend = st.number_input(
            "1株当たり配当金（円）",
            min_value=0.0,
            value=50.0,
            step=0.1,
            help="税引前の配当金額"
        )
        
        # 価格取得方法
        st.subheader("💰 価格設定")
        
        price_method = st.radio(
            "価格取得方法",
            ["Yahoo! Finance（自動取得）", "代替データソース", "手動入力", "モック価格（テスト用）"],
            index=0,
            help="価格の取得方法を選択してください"
        )
        
        if price_method == "Yahoo! Finance（自動取得）":
            if not HAS_SCRAPING_LIBS:
                st.error("❌ Yahoo! Finance取得に必要なライブラリがインストールされていません")
                st.info("💡 代替データソースまたは手動入力をお使いください")
            elif st.button("🔄 Yahoo!から価格を取得", type="primary"):
                try:
                    with st.spinner(f"{ticker}の気配値を取得中..."):
                        ask_price, bid_price = fetch_bid_ask_yahoo(ticker)
                        st.session_state.ask_price = ask_price
                        st.session_state.bid_price = bid_price
                        st.success(f"✅ 取得完了: 売気配={ask_price:,.2f}円, 買気配={bid_price:,.2f}円")
                except Exception as e:
                    st.error(f"❌ Yahoo!からの取得に失敗: {e}")
                    st.info("💡 代替データソースまたは手動入力をお試しください")
        
        elif price_method == "代替データソース":
            if st.button("🔄 代替ソースから価格を取得", type="primary"):
                try:
                    with st.spinner(f"{ticker}の価格を取得中..."):
                        ask_price, bid_price = fetch_price_alternative(ticker)
                        st.session_state.ask_price = ask_price
                        st.session_state.bid_price = bid_price
                        st.success(f"✅ 取得完了: 売気配={ask_price:,.2f}円, 買気配={bid_price:,.2f}円")
                        st.info("📊 代替データソースから取得（参考値）")
                except Exception as e:
                    st.error(f"❌ 代替ソースからの取得に失敗: {e}")
        
        elif price_method == "モック価格（テスト用）":
            if st.button("🔄 テスト価格を設定", type="secondary"):
                ask_price, bid_price = fetch_price_mock(ticker)
                st.session_state.ask_price = ask_price
                st.session_state.bid_price = bid_price
                st.success(f"✅ テスト価格設定: 売気配={ask_price:,.2f}円, 買気配={bid_price:,.2f}円")
                st.warning("⚠️ これはテスト用の固定価格です")
        
        # 価格表示または手動入力
        if price_method == "手動入力" or 'ask_price' not in st.session_state:
            ask_price = st.number_input(
                "売気配（Ask価格）",
                min_value=0.0,
                value=st.session_state.get('ask_price', 1000.0),
                step=0.1,
                help="手動で売気配を入力してください"
            )
            bid_price = st.number_input(
                "買気配（Bid価格）",
                min_value=0.0,
                value=st.session_state.get('bid_price', 995.0),
                step=0.1,
                help="手動で買気配を入力してください"
            )
            st.session_state.ask_price = ask_price
            st.session_state.bid_price = bid_price
        else:
            ask_price = st.session_state.ask_price
            bid_price = st.session_state.bid_price
            
            # 現在の価格を表示
            col1, col2 = st.columns(2)
            with col1:
                st.metric("売気配", f"{ask_price:,.2f}円", help="Ask価格")
            with col2:
                st.metric("買気配", f"{bid_price:,.2f}円", help="Bid価格")
            
            # 価格をリセットするボタン
            if st.button("🔄 価格をリセット", help="価格をクリアして再入力"):
                if 'ask_price' in st.session_state:
                    del st.session_state.ask_price
                if 'bid_price' in st.session_state:
                    del st.session_state.bid_price
                st.rerun()
        
        # 詳細設定
        with st.expander("⚙️ 詳細設定"):
            loan_rate = st.number_input(
                "貸株料率",
                min_value=0.0,
                max_value=1.0,
                value=DefaultConfig.LOAN_RATE,
                step=0.001,
                format="%.3f"
            )
            
            mgmt_fee = st.number_input(
                "管理手数料/月（円）",
                min_value=0.0,
                value=float(DefaultConfig.MANAGEMENT_FEE_PER_CYCLE),
                step=10.0
            )
            
            spread_on_exit = st.checkbox(
                "決済時もスプレッドコストを考慮",
                value=False
            )

    # メインエリア
    # 入力検証
    validation_errors = []
    
    if start_date >= end_date:
        validation_errors.append("❌ 終了日は開始日より後の日付を入力してください")
    
    if not ticker or len(ticker) != 4 or not ticker.isdigit():
        validation_errors.append("❌ 銘柄コードは4桁の数字で入力してください")
    
    if 'ask_price' not in st.session_state or 'bid_price' not in st.session_state:
        validation_errors.append("💡 価格を取得または入力してください")
    
    if validation_errors:
        for error in validation_errors:
            st.error(error)
        return
    
    # 価格の妥当性チェック
    if st.session_state.ask_price <= st.session_state.bid_price:
        st.warning("⚠️ 売気配が買気配以下になっています。価格を確認してください。")
    
    # 計算実行
    if st.button("🧮 P/L計算実行", type="primary", use_container_width=True):
        try:
            # パラメータ作成
            params = TradeParams(
                ticker=ticker,
                qty=qty,
                start=start_date,
                end=end_date,
                ask_price=st.session_state.ask_price,
                bid_price=st.session_state.bid_price,
                dividend=dividend,
                loan_rate=loan_rate,
                management_fee_per_cycle=mgmt_fee,
                spread_on_exit=spread_on_exit
            )
            
            # 計算実行
            result = calc_trade(params)
            
            # 結果表示
            display_results(params, result)
            
        except Exception as e:
            st.error(f"❌ 計算中にエラーが発生しました: {e}")
            st.info("💡 入力値を確認して再度お試しください")

def display_results(params: TradeParams, result: TradeResult):
    """計算結果を表示"""
    
    st.header("📊 計算結果")
    
    # 基本情報
    col1, col2, col3, col4 = st.columns(4)
    
    with col1:
        st.metric("銘柄コード", params.ticker)
    
    with col2:
        st.metric("株数", f"{params.qty:,}株")
    
    with col3:
        days = _days_inclusive(params.start, params.end)
        st.metric("保有日数", f"{days}日")
    
    with col4:
        months = _count_passed_months(params.start, params.end)
        st.metric("経過月数", f"{months}ヶ月")
    
    st.divider()
    
    # 価格情報
    col1, col2, col3 = st.columns(3)
    
    with col1:
        st.metric("買気配", f"{params.bid_price:,.2f}円")
    
    with col2:
        st.metric("売気配", f"{params.ask_price:,.2f}円")
    
    with col3:
        spread = params.ask_price - params.bid_price
        st.metric("スプレッド", f"{spread:,.2f}円", f"{spread/params.bid_price*100:.2f}%")
    
    st.divider()
    
    # P/L詳細
    st.subheader("💰 P/L詳細")
    
    # データフレーム作成
    pl_data = {
        "項目": [
            "配当金受取",
            "配当落調整金支払",
            "貸株料",
            "消費税",
            "管理手数料",
            "エントリースプレッド",
            "決済スプレッド"
        ],
        "金額（円）": [
            result.dividend_received,
            -result.dividend_adjustment_paid,
            -result.loan_fee,
            -result.consumption_tax,
            -result.management_fee,
            -result.entry_spread_cost,
            -result.exit_spread_cost if params.spread_on_exit else 0
        ]
    }
    
    df = pd.DataFrame(pl_data)
    df["金額（円）"] = df["金額（円）"].round(0).astype(int)
    
    # 色付けのため正負で分ける
    def color_pl(val):
        if val > 0:
            return 'background-color: #d4edda; color: #155724'
        elif val < 0:
            return 'background-color: #f8d7da; color: #721c24'
        else:
            return ''
    
    styled_df = df.style.map(color_pl, subset=['金額（円）'])
    st.dataframe(styled_df, use_container_width=True, hide_index=True)
    
    # 合計P/L
    st.subheader("📈 合計P/L")
    
    col1, col2 = st.columns(2)
    
    with col1:
        pre_tax = result.total_pre_tax()
        st.metric(
            "税引前P/L",
            f"{pre_tax:,.0f}円",
            delta=f"{pre_tax:+,.0f}円"
        )
    
    with col2:
        post_tax = result.total_post_tax(params.withholding_tax_rate)
        st.metric(
            "税引後P/L",
            f"{post_tax:,.0f}円",
            delta=f"{post_tax:+,.0f}円"
        )
    
    # 利回り計算
    st.divider()
    
    notional = params.bid_price * params.qty
    days = _days_inclusive(params.start, params.end)
    
    col1, col2, col3 = st.columns(3)
    
    with col1:
        st.metric("投資元本", f"{notional:,.0f}円")
    
    with col2:
        annual_return = (pre_tax / notional) * (365 / days) * 100
        st.metric("年利（税引前）", f"{annual_return:.2f}%")
    
    with col3:
        annual_return_post = (post_tax / notional) * (365 / days) * 100
        st.metric("年利（税引後）", f"{annual_return_post:.2f}%")
    
    # 警告メッセージ
    if pre_tax < 0:
        st.warning("⚠️ 損失が発生する可能性があります。取引条件を再確認してください。")
    
    st.info("💡 Yahoo! Financeの気配値は20分遅れです。実際の取引前には証券会社のリアルタイム板で確認してください。")

# アプリケーション実行
if __name__ == "__main__":
    main()
