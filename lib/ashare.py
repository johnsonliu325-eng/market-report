#!/usr/bin/env python3
"""A股数据取数：关键指数 + 行业ETF + 思源电气。用 akshare。
仅在本地运行（akshare 不适合 GitHub 云端），输出 ashare_data.json 供 build_site 读取。
"""
import json, os, datetime, urllib.request

# 关注的指数（新浪名称）
INDEX_NAMES = ["上证指数", "深证成指", "创业板指", "沪深300", "科创50", "中证500", "北证50"]

# 关注的行业 ETF（关键词 -> 显示名），取每类成交额最大的主流ETF
ETF_KEYWORDS = [
    ("电力", "电力"), ("光伏", "光伏"), ("新能源车", "新能源车"),
    ("半导体", "半导体"), ("芯片", "芯片"), ("机器人", "机器人"),
    ("创新药", "创新药"), ("证券", "证券"), ("银行", "银行"),
    ("医药", "医药"), ("军工", "军工"), ("人工智能", "AI/人工智能"),
]

# 重点跟踪个股
FOCUS_STOCK = ("002028", "思源电气")

OUT = os.path.join(os.path.dirname(__file__), "..", "ashare_data.json")


# 指数 -> 新浪日线代码，用于盘前竞价窗口指数被清零时回补上一交易日
INDEX_SINA_CODE = {
    "上证指数": "sh000001", "深证成指": "sz399001", "创业板指": "sz399006",
    "沪深300": "sh000300", "科创50": "sh000688", "中证500": "sh000905",
    "北证50": "bj899050",
}


def _backfill_indices(ak, indices):
    """盘前竞价窗口 sina 把指数现价/涨跌幅清零。用新浪日线上一交易日收盘补齐。
    判定盘前：现价为 0，或多数指数涨跌幅≈0（当日尚未成交）——两种都补齐为上一完整交易日。
    """
    import time
    if not indices:
        return False
    near_zero = sum(1 for i in indices if abs(i.get("pct") or 0) < 0.01)
    pre_open = near_zero >= max(2, len(indices) // 2)
    filled = False
    for idx in indices:
        if idx["last"] > 0 and not pre_open:
            continue
        sym = INDEX_SINA_CODE.get(idx["name"])
        if not sym:
            continue
        for attempt in range(4):
            try:
                h = ak.stock_zh_index_daily(symbol=sym)
                if h is not None and len(h) >= 2:
                    c1 = float(h.iloc[-1]["close"]); c0 = float(h.iloc[-2]["close"])
                    idx["last"] = round(c1, 2)
                    idx["pct"] = round((c1 / c0 - 1) * 100, 2) if c0 else 0.0
                    filled = True
                break
            except Exception:
                time.sleep(0.8 * (attempt + 1))
    return filled


def get_indices(ak):
    """指数：新浪为主源，失败切东财。返回 (list, src)。"""
    try:
        df = ak.stock_zh_index_spot_sina()
        out = []
        for name in INDEX_NAMES:
            row = df[df["名称"] == name]
            if not row.empty:
                r = row.iloc[0]
                out.append({"name": name, "last": float(r["最新价"]), "pct": float(r["涨跌幅"])})
        if out:
            src = "sina"
            if _backfill_indices(ak, out):
                src = "sina(盘前用上一交易日收盘)"
            return out, src
        raise ValueError("sina empty")
    except Exception:
        return _indices_em(ak), "东财"


def _indices_em(ak):
    """东财指数备源。字段：名称/最新价/涨跌幅(百分数)。"""
    df = ak.stock_zh_index_spot_em(symbol="沪深重要指数")
    out = []
    for name in INDEX_NAMES:
        row = df[df["名称"] == name]
        if not row.empty:
            r = row.iloc[0]
            out.append({"name": name, "last": float(r["最新价"]), "pct": float(r["涨跌幅"])})
    return out


def _pick_etfs(df, code_key="代码", strip_prefix=False):
    """从 ETF 快照 df 中按关键词挑成交额最大的主流 ETF。"""
    out, used = [], set()
    for kw, label in ETF_KEYWORDS:
        hit = df[df["名称"].str.contains(kw, na=False)]
        if hit.empty:
            continue
        hit = hit.sort_values("成交额", ascending=False)
        for _, r in hit.iterrows():
            code = str(r[code_key])
            if strip_prefix:
                code = code[2:] if code[:2] in ("sh", "sz") else code
            if code in used:
                continue
            used.add(code)
            out.append({"label": label, "code": code, "name": r["名称"],
                        "last": float(r["最新价"]), "pct": float(r["涨跌幅"])})
            break
    return out


def _sina_etf_code(code):
    """把纯数字 ETF 代码转成新浪带市场前缀格式。5x/6x=沪，1x=深。"""
    c = str(code)
    return ("sh" if c[:1] in ("5", "6", "9") else "sz") + c


def _backfill_etfs(ak, etfs):
    """盘前东财快照的最新价/涨跌幅为 NaN 时，用新浪日线上一交易日收盘价补齐（自算涨跌幅）。"""
    import math, time
    filled = False
    for e in etfs:
        bad = (isinstance(e.get("last"), float) and math.isnan(e["last"])) or \
              (isinstance(e.get("pct"), float) and math.isnan(e["pct"]))
        if not bad:
            continue
        for attempt in range(4):
            try:
                h = ak.fund_etf_hist_sina(symbol=_sina_etf_code(e["code"]))
                if h is not None and len(h) >= 2:
                    c1 = float(h.iloc[-1]["close"])
                    c0 = float(h.iloc[-2]["close"])
                    e["last"] = round(c1, 3)
                    e["pct"] = round((c1 / c0 - 1) * 100, 2) if c0 else 0.0
                    filled = True
                break
            except Exception:
                time.sleep(0.8 * (attempt + 1))
    return filled


def get_etfs(ak):
    """行业ETF：东财为主源，失败切新浪。返回 (list, src)。"""
    try:
        df = ak.fund_etf_spot_em()
        out = _pick_etfs(df)
        if out:
            src = "东财"
            if _backfill_etfs(ak, out):
                src = "东财(盘前用上一交易日收盘)"
            return out, src
        raise ValueError("em empty")
    except Exception:
        df = ak.fund_etf_category_sina(symbol="ETF基金")
        return _pick_etfs(df, strip_prefix=True), "sina"


def get_focus(ak):
    code, name = FOCUS_STOCK
    prefix = "sh" if code.startswith(("6", "9")) else "sz"
    # 主源：新浪实时 HTTP（盘中拿当日实时价，避免日线接口盘中只给上一交易日收盘）
    try:
        result = _sina_realtime(code, prefix, name)
        result["_src"] = "sina实时"
    except Exception:
        # 退路一：东财日线历史（盘中会滞后到上一交易日）
        try:
            df = ak.stock_zh_a_hist(symbol=code, period="daily", adjust="")
            last = df.iloc[-1]
            recent = df.tail(250)
            result = {
                "code": code, "name": name,
                "last": float(last["收盘"]), "pct": float(last["涨跌幅"]),
                "open": float(last["开盘"]), "high": float(last["最高"]), "low": float(last["最低"]),
                "turnover": float(last["换手率"]), "amount": float(last["成交额"]),
                "yr_high": float(recent["最高"].max()), "yr_low": float(recent["最低"].min()),
                "date": str(last["日期"]),
            }
            result["_src"] = "东财日线"
        except Exception:
            # 退路二：新浪日线
            result = _get_focus_sina(ak, code, name)
            result["_src"] = "sina日线"
    # 年内高低：实时源没有 52 周区间，用日线补（失败不影响）
    if not result.get("yr_high"):
        try:
            hs = ak.stock_zh_a_daily(symbol=prefix + code, adjust="").tail(250)
            result["yr_high"] = round(float(hs["high"].max()), 2)
            result["yr_low"] = round(float(hs["low"].min()), 2)
        except Exception:
            pass
    # 估值补充（失败不影响主流程）
    try:
        v = ak.stock_value_em(symbol=code).iloc[-1]
        mktcap = float(v["总市值"])
        pe, pb, ps = float(v["PE(TTM)"]), float(v["市净率"]), float(v["市销率"])
        val_date = str(v.get("数据日期", ""))[:10]
        # 东财估值按估值日收盘价算；盘中实时价不同则等比缩放，保持与现价一致
        if result.get("_src", "").startswith("sina实时") and val_date and val_date != result.get("date"):
            close_v = _last_close_for_val(ak, prefix, code, val_date)
            if close_v and close_v > 0:
                k = result["last"] / close_v
                mktcap, pe, pb, ps = mktcap * k, pe * k, pb * k, ps * k
        result.update({
            "mktcap": mktcap, "pe_ttm": round(pe, 2), "pb": round(pb, 2),
            "ps": round(ps, 2), "peg": float(v["PEG值"]),
        })
    except Exception:
        # 估值也失败时，用新浪流通股*收盘价兜底市值
        if "mktcap" not in result:
            try:
                sh = float(result.get("_shares") or 0)
                if sh:
                    result["mktcap"] = result["last"] * sh
            except Exception:
                pass
    result.pop("_shares", None)
    return result


def _sina_realtime(code, prefix, name):
    """新浪实时行情 HTTP（hq.sinajs.cn），盘中拿当日实时价。
    返回字段：现价/涨跌幅/开高低/成交额/日期(当日)。"""
    url = f"https://hq.sinajs.cn/list={prefix}{code}"
    req = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0", "Referer": "https://finance.sina.com.cn"})
    txt = urllib.request.urlopen(req, timeout=10).read().decode("gbk", "ignore")
    p = txt.split('"')[1].split(",")
    if len(p) < 32 or not p[0]:
        raise ValueError("sina realtime empty")
    last, prev = float(p[3]), float(p[2])
    # 盘前(9:15-9:30)集合竞价前：sina 已把日期滚到当日但成交额为 0，
    # 现价=昨收、涨跌幅=0。此时应抛出，让上层回退到日线取上一完整交易日。
    if float(p[9] or 0) <= 0:
        raise ValueError("sina realtime pre-open (amount=0)")
    if last <= 0:  # 停牌时现价为 0，回退昨收
        last = prev
    pct = (last / prev - 1) * 100 if prev else 0.0
    return {
        "code": code, "name": name,
        "last": round(last, 2), "pct": round(pct, 2),
        "open": round(float(p[1]), 2), "high": round(float(p[4]), 2), "low": round(float(p[5]), 2),
        "amount": float(p[9]), "turnover": None,
        "yr_high": None, "yr_low": None,
        "date": p[30],
    }


def _last_close_for_val(ak, prefix, code, val_date):
    """取估值日(val_date)的收盘价，用于把东财估值缩放到实时价。"""
    try:
        df = ak.stock_zh_a_daily(symbol=prefix + code, adjust="")
        row = df[df["date"].astype(str) == val_date]
        if not row.empty:
            return float(row.iloc[-1]["close"])
        return float(df.iloc[-1]["close"])  # 找不到就用最新收盘
    except Exception:
        return None


def _get_focus_sina(ak, code, name):
    """新浪回退：东财断连时用 stock_zh_a_daily 取数并自算涨跌幅。"""
    prefix = "sh" if code.startswith(("6", "9")) else "sz"
    df = ak.stock_zh_a_daily(symbol=prefix + code, adjust="")
    tail = df.tail(2).to_dict("records")
    last = tail[-1]
    prev_close = tail[0]["close"] if len(tail) == 2 else last["open"]
    pct = (last["close"] / prev_close - 1) * 100 if prev_close else 0.0
    recent = df.tail(250)
    return {
        "code": code, "name": name,
        "last": round(float(last["close"]), 2), "pct": round(float(pct), 2),
        "open": round(float(last["open"]), 2), "high": round(float(last["high"]), 2),
        "low": round(float(last["low"]), 2),
        "turnover": round(float(last["turnover"]) * 100, 2), "amount": float(last["amount"]),
        "yr_high": round(float(recent["high"].max()), 2),
        "yr_low": round(float(recent["low"].min()), 2),
        "date": str(last["date"]),
        "_shares": float(last.get("outstanding_share") or 0),
    }


def main():
    import akshare as ak
    data = {"generated_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M")}
    src = {}
    try:
        data["indices"], src["indices"] = get_indices(ak)
    except Exception as e:
        data["indices"], data["index_err"] = [], str(e)[:80]
    try:
        data["etfs"], src["etfs"] = get_etfs(ak)
    except Exception as e:
        data["etfs"], data["etf_err"] = [], str(e)[:80]
    try:
        data["focus"] = get_focus(ak)
        src["focus"] = data["focus"].get("_src", "东财") if data["focus"] else None
    except Exception as e:
        data["focus"], data["focus_err"] = None, str(e)[:80]
    data["_src"] = src

    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    print("wrote", os.path.abspath(OUT))
    print(json.dumps(data, ensure_ascii=False, indent=1)[:600])


if __name__ == "__main__":
    main()
