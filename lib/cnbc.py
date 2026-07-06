#!/usr/bin/env python3
"""CNBC quote engine — 免费、不限流、返回干净 JSON。所有盯盘脚本共用。"""
import urllib.request, urllib.parse, json, time

UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"
BASE = "https://quote.cnbc.com/quote-html-webservice/restQuote/symbolType/symbol"


def _get(url, retries=3):
    last = None
    for i in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=15) as r:
                return json.loads(r.read().decode("utf-8", "ignore"))
        except Exception as e:
            last = e
            time.sleep(1.5 * (i + 1))
    raise last


YBASE = "https://query1.finance.yahoo.com/v8/finance/chart/"
YUA = "Mozilla/5.0"  # Yahoo 对完整 Chrome UA 会 429，用简短 UA


def _yget(url, retries=3):
    last = None
    for i in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": YUA})
            with urllib.request.urlopen(req, timeout=15) as r:
                return json.loads(r.read().decode("utf-8", "ignore"))
        except Exception as e:
            last = e
            time.sleep(1.5 * (i + 1))
    raise last


def _yahoo_quote(ticker):
    """Yahoo chart 备源：返回与 CNBC 兼容的 {last, change, change_pct, name}。
    仅用于普通美股 ticker（个股/ETF），指数（. 前缀）不走此源。"""
    url = f"{YBASE}{urllib.parse.quote(ticker)}?interval=1d&range=1d"
    d = _yget(url)
    m = d["chart"]["result"][0]["meta"]
    last = m.get("regularMarketPrice")
    prev = m.get("previousClose") or m.get("chartPreviousClose")
    if last is None:
        raise ValueError("no price")
    chg = (last - prev) if prev else None
    pct = (chg / prev * 100) if (chg is not None and prev) else None
    return {
        "symbol": ticker,
        "name": m.get("shortName") or m.get("longName") or ticker,
        "last": f"{last:,.2f}",
        "change": f"{chg:+.2f}" if chg is not None else "",
        "change_pct": f"{pct:+.2f}%" if pct is not None else "",
        "_src": "yahoo",
    }


def quotes(symbols):
    """symbols: list of CNBC symbols. 返回 dict{symbol: {name,last,change,change_pct,...}}
    CNBC 为主源；普通美股 ticker 若 CNBC 缺失/报错，自动回退 Yahoo。"""
    out = {}
    # CNBC 一次能拉很多，但分批更稳（每批 20）
    for i in range(0, len(symbols), 20):
        batch = symbols[i:i + 20]
        q = urllib.parse.quote("|".join(batch))
        url = f"{BASE}?symbols={q}&requestMethod=itv&noform=1&fund=1&exthrs=1&output=json"
        try:
            d = _get(url)
            items = d.get("FormattedQuoteResult", {}).get("FormattedQuote", [])
            if isinstance(items, dict):
                items = [items]
            for it in items:
                sym = it.get("symbol")
                if sym:
                    out[sym] = it
        except Exception as e:
            for s in batch:
                out[s] = {"symbol": s, "error": str(e)[:60]}
        time.sleep(0.4)
    # Yahoo 备源：补齐 CNBC 缺失或报错的普通美股 ticker（跳过 . 前缀指数与含特殊符号的商品符号）
    for s in symbols:
        got = out.get(s)
        need = got is None or got.get("error") or (got.get("last") in (None, "", "N/A"))
        if need and s and s[0].isalnum() and all(ch not in s for ch in ".@=|"):
            try:
                out[s] = _yahoo_quote(s)
                time.sleep(0.3)
            except Exception:
                pass
    return out


def num(q, key):
    """把 '7,499.36' / '+0.79%' 这类字符串转成 float，取不到返回 None"""
    v = q.get(key)
    if v is None:
        return None
    try:
        return float(str(v).replace(",", "").replace("%", "").replace("+", ""))
    except ValueError:
        return None


if __name__ == "__main__":
    r = quotes([".SPX", ".IXIC", "AMZN"])
    for s, q in r.items():
        print(s, q.get("name"), q.get("last"), q.get("change_pct"))
