#!/usr/bin/env python3
"""生成美股晨报 HTML 页面 —— 带样式、涨跌标红绿、板块热力。
数据来自 CNBC 引擎。用法: python3 build_html.py
输出: reports/晨报_YYYYMMDD.html 和 reports/latest.html
"""
import sys, os, json, datetime
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "lib"))
from cnbc import quotes, num
from symbols import INDICES, SECTOR_ETF, FOCUS
from gainers import top_gainers

SITE_DIR = os.path.join(os.path.dirname(__file__), "site")
CONTENT_FILE = os.path.join(os.path.dirname(__file__), "content.json")
ASHARE_FILE = os.path.join(os.path.dirname(__file__), "ashare_data.json")


def load_ashare():
    """读取本地生成的 A 股数据（akshare 云端拉不到，必须本地生成后推送）。"""
    try:
        with open(ASHARE_FILE, encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def load_content():
    """读取 Claude 在终端生成的 AI 内容（新闻精选/公司简介/Amazon点评）。
    没有文件时返回空 dict，网站照常出纯数据版。"""
    try:
        with open(CONTENT_FILE, encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def bj_now():
    """北京时间（GitHub Actions 服务器为 UTC，须 +8）"""
    return datetime.datetime.utcnow() + datetime.timedelta(hours=8)


def color(pct):
    """美股惯例：涨绿跌红。返回 CSS 颜色。"""
    if pct is None:
        return "#888"
    if pct > 0:
        return "#16a34a"   # green
    if pct < 0:
        return "#dc2626"   # red
    return "#888"


def cell_pct(q):
    p = num(q, "change_pct")
    raw = q.get("change_pct", "N/A")
    return f'<span style="color:{color(p)};font-weight:600">{raw}</span>'


def table(title, pairs, q):
    rows = []
    for sym, cn in pairs:
        d = q.get(sym, {})
        last = d.get("last", "N/A")
        rows.append(
            f'<tr><td class="sym">{sym}</td><td>{cn}</td>'
            f'<td class="num">{last}</td><td class="num">{cell_pct(d)}</td></tr>'
        )
    return (
        f'<h2>{title}</h2><table><thead><tr>'
        f'<th>代码</th><th>名称</th><th>现价</th><th>涨跌%</th>'
        f'</tr></thead><tbody>{"".join(rows)}</tbody></table>'
    )


def heatmap(pairs, q):
    """板块热力条：按涨跌幅排序，用背景色深浅表示强弱。"""
    rows = []
    for sym, cn in pairs:
        p = num(q.get(sym, {}), "change_pct")
        if p is not None:
            rows.append((cn, sym, p))
    rows.sort(key=lambda x: x[2], reverse=True)
    cells = []
    for cn, sym, p in rows:
        # 透明度按幅度，0~3% 映射到 0.15~0.9
        alpha = min(0.9, 0.15 + abs(p) / 3 * 0.75)
        bg = f"rgba(22,163,74,{alpha})" if p > 0 else f"rgba(220,38,38,{alpha})"
        cells.append(
            f'<div class="heat" style="background:{bg}">'
            f'<div class="hn">{cn}</div><div class="hp">{p:+.2f}%</div></div>'
        )
    return f'<h2>板块热力（按涨跌%排序）</h2><div class="heatgrid">{"".join(cells)}</div>'


def amazon_card(q):
    d = q.get("AMZN", {})
    if not d.get("last"):
        return ""
    p = num(d, "change_pct")
    last = num(d, "last")
    hi, lo = num(d, "yrhiprice"), num(d, "yrloprice")
    pos = (last - lo) / (hi - lo) * 100 if (last and hi and lo and hi > lo) else None
    posbar = ""
    if pos is not None:
        posbar = (f'<div class="posbar"><div class="posfill" style="left:{pos:.0f}%"></div></div>'
                  f'<div class="poslbl"><span>{d.get("yrloprice")}</span>'
                  f'<span>52周区间 {pos:.0f}%</span><span>{d.get("yrhiprice")}</span></div>')
    stats = [
        ("市值", d.get("mktcapView")), ("PE", d.get("pe")), ("前瞻PE", d.get("fpe")),
        ("PS", d.get("psales")), ("EPS", d.get("eps")), ("ROE", d.get("ROETTM")),
        ("毛利率", d.get("GROSMGNTTM")), ("净利率", d.get("NETPROFTTM")), ("Beta", d.get("beta")),
    ]
    grid = "".join(f'<div class="stat"><div class="sl">{k}</div><div class="sv">{v}</div></div>'
                   for k, v in stats)
    return (
        f'<h2>重点个股 · Amazon</h2>'
        f'<div class="amzn"><div class="amzntop">'
        f'<span class="price">{d.get("last")}</span>'
        f'<span class="chg" style="color:{color(p)}">{d.get("change_pct")} ({d.get("change")})</span>'
        f'<span class="mktstatus">{d.get("curmktstatus","")}</span></div>'
        f'{posbar}<div class="statgrid">{grid}</div></div>'
    )


def fmt_cap(v):
    """市值字符串 '38,055,975,066' -> '380.6亿' / '1.56万亿'"""
    try:
        n = float(str(v).replace(",", "").replace("$", ""))
    except (ValueError, TypeError):
        return v or "N/A"
    if n >= 1e12:
        return f"{n/1e12:.2f}万亿"
    if n >= 1e8:
        return f"{n/1e8:.0f}亿"
    return f"{n/1e6:.0f}百万"


def gainers_table(n=8, intros=None):
    intros = intros or {}
    try:
        gs = top_gainers(n=n)
    except Exception as e:
        return f'<h2>Top Gainers</h2><div class="note">榜单获取失败: {str(e)[:60]}</div>'
    if not gs:
        return '<h2>Top Gainers</h2><div class="note">暂无数据</div>'
    rows = []
    for g in gs:
        intro = intros.get(g["symbol"], "")
        intro_html = f'<div class="intro">{intro}</div>' if intro else ""
        rows.append(
            f'<tr><td class="sym">{g["symbol"]}</td>'
            f'<td>{g["name"]}{intro_html}</td>'
            f'<td class="num" style="color:#16a34a;font-weight:600">+{g["pct"]:.2f}%</td>'
            f'<td class="num">{g["last"]}</td><td class="num">{fmt_cap(g["marketCap"])}</td>'
            f'<td>{g.get("sector","") or "—"}</td></tr>'
        )
    return (
        '<h2>Top Gainers（大中盘涨幅榜）</h2>'
        '<table><thead><tr><th>代码</th><th>公司</th><th>涨幅</th>'
        '<th>现价</th><th>市值</th><th>行业</th></tr></thead>'
        f'<tbody>{"".join(rows)}</tbody></table>'
    )


def news_section(news, title="精选新闻"):
    """精选新闻: news = [{title, source, url, note}]"""
    if not news:
        return ""
    items = []
    for it in news:
        note = f'<div class="intro">{it["note"]}</div>' if it.get("note") else ""
        src = f' · <span class="nsrc">{it["source"]}</span>' if it.get("source") else ""
        link = it.get("url", "#")
        items.append(
            f'<div class="newsitem"><a href="{link}" target="_blank">{it.get("title","")}</a>'
            f'{src}{note}</div>'
        )
    return f'<h2>{title}</h2><div class="newslist">{"".join(items)}</div>'


def amazon_commentary(text):
    """Amazon 追踪点评（Claude 写的 markdown-ish 文本，简单换行处理）"""
    if not text:
        return ""
    paras = "".join(f"<p>{line}</p>" for line in text.split("\n") if line.strip())
    return f'<h2>Amazon 追踪 · 观点</h2><div class="commentary">{paras}</div>'


def ashare_section(a, commentary="", with_header=True):
    """A股板块：指数 + 行业ETF + 思源电气。a = ashare_data.json 内容"""
    if not a or not a.get("indices"):
        return ""
    def pctspan(p):
        # A股惯例：涨红跌绿（与美股相反）
        c = "#dc2626" if p > 0 else ("#16a34a" if p < 0 else "#888")
        return f'<span style="color:{c};font-weight:600">{p:+.2f}%</span>'

    # 指数表
    irows = "".join(
        f'<tr><td>{i["name"]}</td><td class="num">{i["last"]:.2f}</td>'
        f'<td class="num">{pctspan(i["pct"])}</td></tr>' for i in a["indices"])
    idx = ('<table><thead><tr><th>指数</th><th>点位</th><th>涨跌%</th></tr></thead>'
           f'<tbody>{irows}</tbody></table>')

    # 行业ETF表
    erows = "".join(
        f'<tr><td class="sym">{e["code"]}</td><td>{e["label"]}</td>'
        f'<td class="num">{e["last"]:.3f}</td><td class="num">{pctspan(e["pct"])}</td></tr>'
        for e in a.get("etfs", []))
    etf = ('<table><thead><tr><th>代码</th><th>行业</th><th>净值</th><th>涨跌%</th></tr></thead>'
           f'<tbody>{erows}</tbody></table>') if erows else ""

    # 思源电气卡片
    f = a.get("focus")
    focus_html = ""
    if f:
        pos = None
        if f.get("yr_high") and f.get("yr_low") and f["yr_high"] > f["yr_low"]:
            pos = (f["last"] - f["yr_low"]) / (f["yr_high"] - f["yr_low"]) * 100
        stats = [("总市值", f'{f.get("mktcap",0)/1e8:.0f}亿' if f.get("mktcap") else "N/A"),
                 ("PE(TTM)", f.get("pe_ttm")), ("PB", f.get("pb")),
                 ("PS", f.get("ps")), ("PEG", f.get("peg")), ("换手率", f'{f.get("turnover")}%')]
        grid = "".join(f'<div class="stat"><div class="sl">{k}</div>'
                       f'<div class="sv">{round(v,2) if isinstance(v,float) else v}</div></div>'
                       for k, v in stats)
        pctc = "#dc2626" if f["pct"] > 0 else "#16a34a"
        posbar = ""
        if pos is not None:
            posbar = (f'<div class="posbar"><div class="posfill" style="left:{pos:.0f}%"></div></div>'
                      f'<div class="poslbl"><span>{f["yr_low"]:.1f}</span>'
                      f'<span>52周区间 {pos:.0f}%</span><span>{f["yr_high"]:.1f}</span></div>')
        comm = f'<div class="commentary" style="margin-top:14px">{"".join(f"<p>{l}</p>" for l in commentary.split(chr(10)) if l.strip())}</div>' if commentary else ""
        focus_html = (
            f'<h3 style="margin-top:20px">重点个股 · 思源电气 ({f["code"]})</h3>'
            f'<div class="amzn"><div class="amzntop">'
            f'<span class="price">{f["last"]:.2f}</span>'
            f'<span class="chg" style="color:{pctc}">{f["pct"]:+.2f}%</span>'
            f'<span class="mktstatus">{f.get("date","")}</span></div>'
            f'{posbar}<div class="statgrid">{grid}</div>{comm}</div>')

    hdr = '<h2>🇨🇳 A股</h2>' if with_header else ''
    return (f'<div class="ashare-block">{hdr}'
            f'<h3>关键指数</h3>{idx}'
            f'{"<h3>行业 ETF</h3>" + etf if etf else ""}'
            f'{focus_html}</div>')


CSS = """
body{font-family:-apple-system,'PingFang SC',sans-serif;max-width:1000px;margin:0 auto;
padding:24px;background:#0f1115;color:#e6e6e6;line-height:1.5}
h1{font-size:24px;border-bottom:2px solid #2a2f3a;padding-bottom:12px}
h2{font-size:17px;margin-top:28px;color:#9ca3af}
.ts{color:#6b7280;font-size:13px}
table{width:100%;border-collapse:collapse;font-size:14px;margin-top:8px}
th{text-align:left;color:#6b7280;font-weight:500;padding:6px 10px;border-bottom:1px solid #2a2f3a;font-size:12px}
td{padding:6px 10px;border-bottom:1px solid #1a1e26}
td.num{text-align:right;font-variant-numeric:tabular-nums}
td.sym{color:#60a5fa;font-family:monospace}
tr:hover{background:#161a22}
.heatgrid{display:grid;grid-template-columns:repeat(auto-fill,minmax(110px,1fr));gap:6px;margin-top:8px}
.heat{padding:10px 8px;border-radius:6px;text-align:center}
.hn{font-size:12px;opacity:.95}.hp{font-size:15px;font-weight:700;font-variant-numeric:tabular-nums}
.amzn{background:#161a22;border-radius:10px;padding:18px;margin-top:8px}
.amzntop{display:flex;align-items:baseline;gap:14px}
.price{font-size:28px;font-weight:700}.chg{font-size:16px;font-weight:600}
.mktstatus{margin-left:auto;font-size:11px;color:#6b7280;background:#0f1115;padding:3px 8px;border-radius:4px}
.posbar{position:relative;height:6px;background:#2a2f3a;border-radius:3px;margin:20px 0 6px}
.posfill{position:absolute;top:-3px;width:12px;height:12px;background:#60a5fa;border-radius:50%;transform:translateX(-50%)}
.poslbl{display:flex;justify-content:space-between;font-size:11px;color:#6b7280}
.statgrid{display:grid;grid-template-columns:repeat(3,1fr);gap:10px;margin-top:16px}
.stat{background:#0f1115;padding:10px;border-radius:6px}
.sl{font-size:11px;color:#6b7280}.sv{font-size:15px;font-weight:600;margin-top:2px}
.note{background:#1e293b;border-left:3px solid #60a5fa;padding:10px 14px;border-radius:4px;font-size:13px;color:#94a3b8;margin-top:16px}
.intro{font-size:12px;color:#8b96a5;margin-top:3px;line-height:1.4}
.newslist{margin-top:8px}
.newsitem{padding:10px 0;border-bottom:1px solid #1a1e26}
.newsitem a{color:#e6e6e6;text-decoration:none;font-weight:600;font-size:15px}
.newsitem a:hover{color:#60a5fa}
.nsrc{color:#6b7280;font-size:12px}
.commentary{background:#161a22;border-radius:10px;padding:16px 18px;margin-top:8px}
.commentary p{margin:8px 0;font-size:14px;color:#cbd5e1}
.updated{color:#6b7280;font-size:12px;margin-top:4px}
"""


def main():
    all_syms = [s for s, _ in INDICES + SECTOR_ETF + FOCUS]
    q = quotes(all_syms)
    now = bj_now().strftime("%Y-%m-%d %H:%M")
    c = load_content()
    a = load_ashare()
    c_time = c.get("generated_at", "")
    updated = f'<div class="updated">AI 内容更新于 {c_time}</div>' if c_time else ""

    body = [
        f'<h1>每日晨报 <span class="ts">{now} 北京时间</span></h1>',
        updated,
        '<h2 style="border-top:1px solid #2a2f3a;padding-top:20px">🇺🇸 美股</h2>',
        news_section(c.get("news"), title="美股精选新闻"),
        amazon_card(q),
        amazon_commentary(c.get("amazon_commentary")),
        gainers_table(8, intros=c.get("gainer_intros")),
        heatmap(SECTOR_ETF, q),
        table("大盘指数", INDICES, q),
        table("板块 ETF", SECTOR_ETF, q),
        '<h2 style="border-top:1px solid #2a2f3a;padding-top:20px">🇨🇳 A股</h2>',
        news_section(c.get("ashare_news"), title="A股精选新闻"),
        ashare_section(a, commentary=c.get("siyuan_commentary", ""), with_header=False),
        '<div class="note">美股行情 CNBC/Nasdaq，A股行情 akshare。新闻精选、公司简介与个股观点由 Claude 在终端生成后同步。</div>',
    ]
    html = (f'<!DOCTYPE html><html lang="zh"><head><meta charset="utf-8">'
            f'<meta name="viewport" content="width=device-width,initial-scale=1">'
            f'<title>每日晨报 {now}</title><style>{CSS}</style></head>'
            f'<body>{"".join(body)}</body></html>')

    os.makedirs(SITE_DIR, exist_ok=True)
    with open(os.path.join(SITE_DIR, "index.html"), "w", encoding="utf-8") as f:
        f.write(html)
    print("wrote", os.path.join(SITE_DIR, "index.html"))


if __name__ == "__main__":
    main()
