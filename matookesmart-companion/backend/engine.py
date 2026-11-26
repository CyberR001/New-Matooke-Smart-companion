"""Decision logic for MatookeSmart: price forecasting, advice, disease support, matching, product economics."""
import statistics
import datetime as dt

BUNCH_KG = 15
FEE = 0.04
ADJ = {"Masaka": ["Mpigi", "Bushenyi", "Kampala"], "Mpigi": ["Masaka", "Kampala", "Kiboga"],
       "Kampala": ["Mpigi", "Jinja", "Kiboga", "Masaka"], "Jinja": ["Kampala"],
       "Mbarara": ["Bushenyi", "Isingiro", "Masaka"], "Bushenyi": ["Mbarara", "Masaka"],
       "Isingiro": ["Mbarara"], "Kiboga": ["Mpigi", "Kampala"]}


def proximity(a, b):
    return 1.0 if a == b else 0.6 if b in ADJ.get(a, []) else 0.2


# ---------- price forecasting ----------
def _ols(y):
    n = len(y); mx = (n - 1) / 2; my = sum(y) / n
    sxx = sum((i - mx) ** 2 for i in range(n)) or 1
    b = sum((i - mx) * (v - my) for i, v in enumerate(y)) / sxx
    return my - b * mx, b


def _week(d):
    return dt.date.fromisoformat(d).isocalendar()[1]


def seasonal_index(rows):
    """Week-of-year index = price / centred 13-week moving average, smoothed over +-1 week."""
    p = [r[1] for r in rows]
    if len(p) < 60:
        return {}
    ratio = {}
    for i in range(6, len(p) - 6):
        ratio.setdefault(_week(rows[i][0]), []).append(p[i] / (sum(p[i - 6:i + 7]) / 13))
    idx = {w: sum(v) / len(v) for w, v in ratio.items()}
    out = {}
    for w in range(1, 54):
        near = [idx[x] for x in (w - 1, w, w + 1) if x in idx]
        out[w] = sum(near) / len(near) if near else 1.0
    m = sum(out.values()) / len(out)
    return {w: v / m for w, v in out.items()}


def forecast(rows, weeks=8):
    """rows: [(iso_date, price)] weekly, ascending. Seasonal-adjusted linear trend with an 80% band."""
    n = len(rows)
    if n < 8:
        return None
    S = seasonal_index(rows)
    g = lambda d: S.get(_week(d), 1.0)
    p = [r[1] for r in rows]
    d = [v / g(r[0]) for r, v in zip(rows, p)]
    k = min(26, n)
    a, b = _ols(d[-k:])
    res = [x - (a + b * i) for i, x in enumerate(d[-k:])]
    sd = statistics.pstdev(res)
    mean_k = sum(d[-k:]) / k
    ss = sum((x - mean_k) ** 2 for x in d[-k:]) or 1
    r2 = max(0.0, 1 - sum(e * e for e in res) / ss)
    last = dt.date.fromisoformat(rows[-1][0])
    pts = []
    for j in range(1, weeks + 1):
        day = last + dt.timedelta(weeks=j)
        base = a + b * (k - 1 + j); s = g(day.isoformat())
        pts.append({"date": day.isoformat(), "price": round(base * s, -2),
                    "low": round((base - 1.28 * sd) * s, -2), "high": round((base + 1.28 * sd) * s, -2)})
    mean52 = sum(p[-52:]) / len(p[-52:])
    chg = (pts[3]["price"] - p[-1]) / p[-1] * 100
    conf = "High" if n >= 60 and sd / mean_k < 0.06 else "Medium" if n >= 20 else "Low"
    return {"last": p[-1], "last_date": rows[-1][0], "mean52": round(mean52), "points": pts,
            "change4w": round(chg, 1), "direction": "Falling" if chg < -4 else "Rising" if chg > 4 else "Steady",
            "confidence": conf, "r2": round(r2, 2), "seasonal": bool(S), "weeks_of_data": n}


def advise(u, fc, demands, notice):
    """Ranks routes to market for a farmer's expected harvest and builds a split plan."""
    qty = u.get("bunches") or 0
    if not qty or not u.get("harvest") or not fc:
        return None
    days = (dt.date.fromisoformat(u["harvest"]) - dt.date.today()).days
    wk = max(0, min(len(fc["points"]) - 1, days // 7))
    pt = fc["points"][wk]
    glut = pt["price"] < 0.92 * fc["mean52"]
    scarce = pt["price"] > 1.08 * fc["mean52"]
    fresh = {"key": "fresh", "title": "Sell fresh at harvest", "per_bunch": pt["price"], "cons": pt["low"],
             "note": f"Expected UGX {pt['price']:,.0f} a bunch (range {pt['low']:,.0f} to {pt['high']:,.0f})."}
    options = [fresh]
    best = None
    for d in demands:
        if d["qty_left"] > 0 and proximity(u["district"], d["district"]) >= 0.6:
            net = d["price"] * (1 - FEE) * 0.97
            if not best or net > best[0]:
                best = (net, d)
    if best:
        options.append({"key": "early", "title": "Early order with advance", "per_bunch": round(best[0], -2),
                        "cons": round(best[0], -2), "buyer": best[1]["buyer"], "demand_id": best[1]["id"],
                        "note": f"{best[1]['buyer']} in {best[1]['district']} wants {best[1]['qty_left']} bunches at UGX {best[1]['price']:,.0f}, "
                                f"deposit {best[1]['deposit_pct']}%. Net after fee and delivery risk about UGX {best[0]:,.0f}."})
    hub = None
    if notice:
        hub = notice["raw_price"] * BUNCH_KG
        options.append({"key": "hub", "title": "Offer surplus to the Hub", "per_bunch": hub, "cons": hub,
                        "note": f"Hub buying {notice['product']} raw matooke at UGX {notice['raw_price']:,.0f} a kg (about UGX {hub:,.0f} a bunch)."})
    left, plan, total = qty, [], 0
    if best and (glut or best[0] >= pt["low"]):
        fill = min(left, best[1]["qty_left"]); left -= fill; total += fill * best[0]
        plan.append(f"Place {fill} bunches on an early order with {best[1]['buyer']}.")
    if hub and glut and hub >= pt["low"] and left > 0:
        sur = min(left, max(1, int(qty * 0.25))); left -= sur; total += sur * hub
        plan.append(f"Offer {sur} bunches as surplus to the Hub.")
    if left > 0:
        total += left * pt["price"]
        plan.append(f"Sell the remaining {left} bunches fresh near harvest.")
    head = ("Glut likely around your harvest. Spread your sales across routes." if glut else
            "Prices should be firm around your harvest. Selling fresh is attractive." if scarce else
            "Prices look steady around your harvest.")
    return {"days": days, "glut": glut, "headline": head, "price_at_harvest": pt, "options": options,
            "plan": plan, "expected_total": round(total, -3)}


# ---------- disease support (weighted symptom rules) ----------
SYMPTOMS = {
    "bud_wilt": "Male bud wilts or dries early", "ooze": "Yellow sticky ooze when plant is cut",
    "uneven_ripe": "Bunch ripens unevenly or rots inside", "top_wilt": "Leaves yellow and wilt from the top",
    "skirt": "Older leaves yellow, then hang down like a skirt", "split_base": "Pseudostem splits at the base",
    "streaks_stem": "Brown or reddish streaks inside the stem", "leaf_streaks": "Dark streaks or spots on leaves",
    "leaf_dry": "Leaves dry out early", "falls": "Plants fall over easily", "corm_tunnel": "Tunnels or rot in the corm",
    "narrow": "Narrow, upright leaves with dark green streaks on veins", "stunt": "Stunted plant, tiny or no bunch",
    "scorch": "Leaf edges yellow or scorched", "poor_fill": "Small bunches with poor filling",
    "root_lesion": "Few roots, dark lesions on roots"}
CONDITIONS = [
    {"name": "Banana Xanthomonas Wilt (BXW)", "notify": True,
     "w": {"bud_wilt": 3, "ooze": 3, "uneven_ripe": 2, "top_wilt": 1},
     "act": "Cut the plant at ground level and bury or burn it. Clean tools with fire or bleach between plants. Remove male buds with a forked stick. Do not move suckers from affected gardens. Report to your district agricultural officer."},
    {"name": "Fusarium wilt (Panama disease)", "notify": True,
     "w": {"skirt": 3, "split_base": 2, "streaks_stem": 3, "top_wilt": 1},
     "act": "Isolate affected plants, avoid moving soil or suckers, use clean planting material and ask an extension worker to confirm."},
    {"name": "Black Sigatoka", "notify": False, "w": {"leaf_streaks": 3, "leaf_dry": 2, "poor_fill": 1},
     "act": "Remove badly affected leaves, improve spacing and drainage, and ask your extension worker about suitable management."},
    {"name": "Banana weevil", "notify": False, "w": {"falls": 2, "corm_tunnel": 3, "stunt": 1, "poor_fill": 1},
     "act": "Plant clean suckers, trap and remove weevils, clear old stumps and mulch properly."},
    {"name": "Banana bunchy top virus", "notify": True, "w": {"narrow": 3, "stunt": 2, "poor_fill": 1},
     "act": "Remove and destroy infected plants, control aphids and use clean planting material. Report to your extension worker."},
    {"name": "Nematode damage", "notify": False, "w": {"root_lesion": 3, "falls": 2, "stunt": 1, "top_wilt": 1},
     "act": "Use clean suckers, add mulch and organic matter, and ask for advice on soil testing."},
    {"name": "Potassium deficiency", "notify": False, "w": {"scorch": 3, "poor_fill": 2, "stunt": 1},
     "act": "Add compost or manure and mulch. Ask an extension worker about a soil test before using fertiliser."}]


def diagnose(ids):
    ids = [i for i in ids if i in SYMPTOMS]
    res = []
    for c in CONDITIONS:
        tot = sum(c["w"].values()); hit = sum(w for s, w in c["w"].items() if s in ids)
        if hit:
            res.append({"name": c["name"], "confidence": round(hit / tot, 2), "matched": [SYMPTOMS[s] for s in c["w"] if s in ids],
                        "action": c["act"], "notifiable": c["notify"]})
    res.sort(key=lambda r: -r["confidence"])
    nxt = None
    if res:
        top = next(c for c in CONDITIONS if c["name"] == res[0]["name"])
        rest = [s for s, w in sorted(top["w"].items(), key=lambda x: -x[1]) if s not in ids]
        nxt = SYMPTOMS[rest[0]] if rest else None
    refer = (not res) or res[0]["confidence"] < 0.5 or res[0]["notifiable"]
    return {"results": res[:3], "next_question": nxt, "refer": refer}


# ---------- buyer-farmer matching ----------
def pair_score(l, d):
    prox = proximity(l["district"], d["district"])
    ratio = d["price"] / l["price"]
    if ratio < 0.85:
        return None
    price = 1.0 if ratio >= 1 else max(0.0, 1 - (1 - ratio) * 6)
    gap = abs((dt.date.fromisoformat(l["harvest_date"]) - dt.date.fromisoformat(d["deliver_date"])).days)
    timing = 1.0 if gap <= 7 else max(0.0, 1 - (gap - 7) / 28)
    fit = min(l["qty_left"], d["qty_left"]) / max(l["qty_left"], d["qty_left"])
    s = 0.35 * prox + 0.30 * price + 0.20 * timing + 0.15 * fit
    return {"score": round(s * 100), "proximity": prox, "price": round(price, 2), "timing": round(timing, 2), "fit": round(fit, 2)}


def rank(one, others, one_is_listing):
    out = []
    for o in others:
        l, d = (one, o) if one_is_listing else (o, one)
        if l["qty_left"] <= 0 or d["qty_left"] <= 0:
            continue
        s = pair_score(l, d)
        if s:
            out.append({**o, "match": s})
    return sorted(out, key=lambda x: -x["match"]["score"])[:8]


# ---------- product economics ----------
def economics(p, raw_price=600):
    rev = p["yield_pct"] / 100 * p["price_kg"]
    cost = raw_price + p["proc_cost"] + p["yield_pct"] / 100 * p["pack_cost"]
    m = rev - cost
    return {**p, "revenue_per_kg": round(rev), "cost_per_kg": round(cost), "margin_per_kg": round(m),
            "margin_pct": round(m / rev * 100) if rev else 0,
            "breakeven_price": round(cost / (p["yield_pct"] / 100)) if p["yield_pct"] else 0}
