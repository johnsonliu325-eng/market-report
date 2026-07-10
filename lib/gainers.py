#!/usr/bin/env python3
"""Top gainers 取数：拉 Nasdaq + NYSE 大中盘股，本地按涨跌幅排序。
只保留有市值意义的公司（过滤仙股），返回涨幅榜。
"""
import urllib.request, json, ssl

UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"


def _ssl_ctx():
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except Exception:
        return ssl.create_default_context()


def _get(url, retries=3):
    import time
    ctx = _ssl_ctx()
    last = None
    for i in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
            with urllib.request.urlopen(req, timeout=20, context=ctx) as r:
                return json.loads(r.read().decode("utf-8", "ignore"))
        except Exception as e:
            last = e
            time.sleep(1.5 * (i + 1))
    raise last


def _pct(r):
    try:
        return float(str(r.get("pctchange", "")).replace("%", "").replace(",", ""))
    except (ValueError, TypeError):
        return None


def top_gainers(n=8, exchanges=("NASDAQ", "NYSE"), caps="mega|large"):
    """返回涨幅前 n 只大中盘股: [{symbol,name,pct,last,marketCap,sector}]"""
    rows = []
    for ex in exchanges:
        url = (f"https://api.nasdaq.com/api/screener/stocks?tableonly=true"
               f"&limit=3000&exchange={ex}&marketcap={caps}")
        try:
            d = _get(url)
            rows += d.get("data", {}).get("table", {}).get("rows") or []
        except Exception:
            continue
    seen, cleaned = set(), []
    for r in rows:
        p = _pct(r)
        sym = r.get("symbol")
        if p is None or not sym or sym in seen:
            continue
        seen.add(sym)
        cleaned.append({
            "symbol": sym,
            "name": r.get("name", "").replace(" Common Stock", "").replace(" Class A", "").strip(),
            "pct": p,
            "last": r.get("lastsale", ""),
            "marketCap": r.get("marketCap", ""),
            "sector": r.get("sector", ""),
        })
    cleaned.sort(key=lambda x: x["pct"], reverse=True)
    return cleaned[:n]


if __name__ == "__main__":
    for g in top_gainers():
        print(f"{g['symbol']:6} {g['name'][:30]:30} +{g['pct']:.2f}%  {g['marketCap']}")
