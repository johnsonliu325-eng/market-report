#!/usr/bin/env python3
"""A股数据取数：关键指数 + 行业ETF + 思源电气。用 akshare。
仅在本地运行（akshare 不适合 GitHub 云端），输出 ashare_data.json 供 build_site 读取。
"""
import json, os, datetime

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
            return out, "sina"
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


def get_etfs(ak):
    """行业ETF：东财为主源，失败切新浪。返回 (list, src)。"""
    try:
        df = ak.fund_etf_spot_em()
        out = _pick_etfs(df)
        if out:
            return out, "东财"
        raise ValueError("em empty")
    except Exception:
        df = ak.fund_etf_category_sina(symbol="ETF基金")
        return _pick_etfs(df, strip_prefix=True), "sina"


def get_focus(ak):
    code, name = FOCUS_STOCK
    # 主接口：东财历史（字段全）；失败则回退新浪（sz/sh 前缀）
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
        result["_src"] = "东财"
    except Exception:
        result = _get_focus_sina(ak, code, name)
        result["_src"] = "sina"
    # 估值补充（失败不影响主流程）
    try:
        v = ak.stock_value_em(symbol=code).iloc[-1]
        result.update({
            "mktcap": float(v["总市值"]), "pe_ttm": float(v["PE(TTM)"]),
            "pb": float(v["市净率"]), "ps": float(v["市销率"]), "peg": float(v["PEG值"]),
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
