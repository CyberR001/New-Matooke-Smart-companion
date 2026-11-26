"""MatookeSmart Companion API (FastAPI + SQLite)."""
import os, sqlite3, secrets, datetime as dt
from typing import Optional, List
from fastapi import FastAPI, Depends, HTTPException, Header
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
import engine, seed

HERE = os.path.dirname(os.path.abspath(__file__))
DB = os.environ.get("DB_PATH", os.path.join(HERE, "matookesmart.db"))
app = FastAPI(title="MatookeSmart Companion")


def rows(sql, a=()):
    c = sqlite3.connect(DB); c.row_factory = sqlite3.Row
    r = [dict(x) for x in c.execute(sql, a).fetchall()]; c.close(); return r


def one(sql, a=()):
    r = rows(sql, a); return r[0] if r else None


def run(sql, a=()):
    c = sqlite3.connect(DB); cur = c.execute(sql, a); c.commit(); i = cur.lastrowid; c.close(); return i


@app.on_event("startup")
def start():
    if not os.path.exists(DB) or not one("select name from sqlite_master where name='users'"):
        seed.build(DB)


def me(authorization: str = Header(None)):
    t = (authorization or "").replace("Bearer ", "")
    u = one("select u.* from users u join sessions s on s.user_id=u.id where s.token=?", (t,))
    if not u:
        raise HTTPException(401, "Please sign in")
    return u


def pub(u):
    return {k: u[k] for k in ("id", "name", "phone", "role", "district", "plan", "acres", "harvest", "bunches")}


class Login(BaseModel): phone: str; pin: str
class Reg(BaseModel): name: str; phone: str; pin: str; role: str = "farmer"; district: str = "Masaka"
class Farm(BaseModel): harvest: Optional[str] = None; bunches: Optional[int] = None; district: Optional[str] = None; acres: Optional[float] = None
class PriceIn(BaseModel): market: str; price: int
class Lst(BaseModel): district: str; qty: int; price: int; harvest_date: str; advance_pct: int = 25
class Dem(BaseModel): district: str; qty: int; price: int; deliver_date: str; deposit_pct: int = 25
class OrderIn(BaseModel): listing_id: int; demand_id: int; qty: Optional[int] = None
class Diag(BaseModel): symptoms: List[str]
class Offer(BaseModel): notice_id: int; kg: int
class Plan(BaseModel): plan: str


# ---------- accounts ----------
@app.post("/api/login")
def login(b: Login):
    u = one("select * from users where phone=?", (b.phone.strip(),))
    if not u or u["pin_hash"] != seed.hp(b.pin, u["salt"]):
        raise HTTPException(401, "Wrong phone number or PIN")
    t = secrets.token_hex(16); run("insert into sessions values(?,?)", (t, u["id"]))
    return {"token": t, "user": pub(u)}


@app.post("/api/register")
def register(b: Reg):
    if b.role not in ("farmer", "buyer") or len(b.pin) < 4 or len(b.phone.strip()) < 9:
        raise HTTPException(400, "Enter a valid phone number, a PIN of at least 4 digits and a role")
    if one("select id from users where phone=?", (b.phone.strip(),)):
        raise HTTPException(400, "That phone number is already registered")
    salt = secrets.token_hex(4)
    run("insert into users(name,phone,pin_hash,salt,role,district,plan,created) values(?,?,?,?,?,?,?,?)",
        (b.name.strip(), b.phone.strip(), seed.hp(b.pin, salt), salt, b.role, b.district, "Basic Farmer" if b.role == "farmer" else "Buyer Basic", dt.date.today().isoformat()))
    return login(Login(phone=b.phone, pin=b.pin))


@app.get("/api/me")
def get_me(u=Depends(me)): return pub(u)


@app.put("/api/me/farm")
def farm(b: Farm, u=Depends(me)):
    for k, v in b.dict().items():
        if v is not None:
            col = "harvest" if k == "harvest" else k
            run(f"update users set {col}=? where id=?", (v, u["id"]))
    return pub(one("select * from users where id=?", (u["id"],)))


@app.post("/api/me/plan")
def set_plan(b: Plan, u=Depends(me)):
    p = one("select * from plans where name=?", (b.plan,))
    if not p or p["audience"] != ("farmer" if u["role"] == "farmer" else "buyer"):
        raise HTTPException(400, "That plan is not available for your account")
    run("update users set plan=? where id=?", (b.plan, u["id"])); return {"ok": True}


# ---------- prices and forecast ----------
def series(m):
    r = rows("select min(date) date, cast(round(avg(price),-2) as integer) price from prices where market=? group by strftime('%Y-%W',date) order by 1", (m,))
    return [(x["date"], x["price"]) for x in r]


@app.get("/api/markets")
def markets(u=Depends(me)): return list(seed.MARKETS)


@app.post("/api/prices")
def add_price(b: PriceIn, u=Depends(me)):
    if b.market not in seed.MARKETS or not 1000 <= b.price <= 100000:
        raise HTTPException(400, "Choose a market and enter a realistic price per bunch")
    run("insert into prices(market,date,price,source) values(?,?,?,?)", (b.market, dt.date.today().isoformat(), b.price, "Farmer report"))
    return {"ok": True}


@app.get("/api/forecast")
def fc(market: str, u=Depends(me)):
    s = series(market); f = engine.forecast(s)
    if not f:
        raise HTTPException(404, "Not enough price records for this market yet")
    return {**f, "market": market, "history": [{"date": d, "price": p} for d, p in s[-40:]]}


def open_demands():
    return rows("select d.*, u.name buyer from demands d join users u on u.id=d.user_id where d.qty_left>0")


@app.get("/api/dashboard")
def dash(u=Depends(me)):
    f = engine.forecast(series(u["district"]))
    notice = one("select * from notices order by raw_price desc limit 1")
    my = rows("select status,count(*) n from orders where farmer_id=? or buyer_id=? group by status", (u["id"], u["id"]))
    opps = [o for o in rows("select * from opportunities order by deadline") if "All" in o["districts"] or u["district"] in o["districts"]][:3]
    return {"user": pub(u), "forecast": f, "advice": engine.advise(u, f, open_demands(), notice) if u["role"] == "farmer" else None,
            "orders": {x["status"]: x["n"] for x in my}, "opportunities": opps,
            "nearby_buyers": len([d for d in open_demands() if engine.proximity(u["district"], d["district"]) >= 0.6])}


# ---------- disease support ----------
@app.get("/api/doctor/symptoms")
def syms(u=Depends(me)): return engine.SYMPTOMS


@app.post("/api/doctor/diagnose")
def diag(b: Diag, u=Depends(me)):
    r = engine.diagnose(b.symptoms)
    if r["results"]:
        run("insert into cases(user_id,symptoms,top,confidence,created) values(?,?,?,?,?)", (u["id"], ",".join(b.symptoms), r["results"][0]["name"], r["results"][0]["confidence"], dt.date.today().isoformat()))
    return r


@app.get("/api/doctor/cases")
def cases(u=Depends(me)): return rows("select * from cases where user_id=? order by id desc limit 5", (u["id"],))


# ---------- marketplace ----------
@app.get("/api/listings")
def listings(mine: bool = False, u=Depends(me)):
    q = "select l.*, u.name farmer from listings l join users u on u.id=l.user_id where l.qty_left>0"
    if mine: return rows(q.replace("l.qty_left>0", "l.user_id=?") + " order by l.id desc", (u["id"],))
    return rows(q + " order by l.harvest_date limit 60")


@app.post("/api/listings")
def mk_listing(b: Lst, u=Depends(me)):
    if u["role"] != "farmer": raise HTTPException(403, "Only farmers can list a harvest")
    if b.qty <= 0 or b.price <= 0: raise HTTPException(400, "Enter a quantity and price")
    return {"id": run("insert into listings(user_id,district,qty,qty_left,price,harvest_date,advance_pct,created) values(?,?,?,?,?,?,?,?)",
                      (u["id"], b.district, b.qty, b.qty, b.price, b.harvest_date, b.advance_pct, dt.date.today().isoformat()))}


@app.get("/api/demands")
def demands(mine: bool = False, u=Depends(me)):
    q = "select d.*, u.name buyer from demands d join users u on u.id=d.user_id where d.qty_left>0"
    if mine: return rows(q.replace("d.qty_left>0", "d.user_id=?") + " order by d.id desc", (u["id"],))
    return rows(q + " order by d.deliver_date limit 60")


@app.post("/api/demands")
def mk_demand(b: Dem, u=Depends(me)):
    if u["role"] not in ("buyer", "hub", "admin"): raise HTTPException(403, "Only buyers can post a requirement")
    if b.qty <= 0 or b.price <= 0: raise HTTPException(400, "Enter a quantity and price")
    return {"id": run("insert into demands(user_id,district,qty,qty_left,price,deliver_date,deposit_pct,created) values(?,?,?,?,?,?,?,?)",
                      (u["id"], b.district, b.qty, b.qty, b.price, b.deliver_date, b.deposit_pct, dt.date.today().isoformat()))}


@app.get("/api/match/listing/{i}")
def m_l(i: int, u=Depends(me)):
    l = one("select * from listings where id=?", (i,))
    if not l: raise HTTPException(404, "Listing not found")
    return engine.rank(l, open_demands(), True)


@app.get("/api/match/demand/{i}")
def m_d(i: int, u=Depends(me)):
    d = one("select * from demands where id=?", (i,))
    if not d: raise HTTPException(404, "Requirement not found")
    return engine.rank(d, rows("select l.*, u.name farmer from listings l join users u on u.id=l.user_id where l.qty_left>0"), False)


def led(oid, kind, amt): run("insert into ledger(order_id,kind,amount,created) values(?,?,?,?)", (oid, kind, amt, dt.date.today().isoformat()))


@app.post("/api/orders")
def mk_order(b: OrderIn, u=Depends(me)):
    l = one("select * from listings where id=?", (b.listing_id,)); d = one("select * from demands where id=?", (b.demand_id,))
    if not l or not d: raise HTTPException(404, "Listing or requirement not found")
    if u["id"] not in (l["user_id"], d["user_id"]) and u["role"] != "admin": raise HTTPException(403, "You can only create orders from your own listing or requirement")
    q = min(b.qty or 10 ** 9, l["qty_left"], d["qty_left"])
    if q <= 0: raise HTTPException(400, "Nothing left to order")
    price = int(round((l["price"] + d["price"]) / 2, -2))
    oid = run("insert into orders(listing_id,demand_id,farmer_id,buyer_id,qty,price,deposit_pct,status,created) values(?,?,?,?,?,?,?,?,?)",
              (l["id"], d["id"], l["user_id"], d["user_id"], q, price, max(l["advance_pct"], d["deposit_pct"]), "agreed", dt.date.today().isoformat()))
    run("update listings set qty_left=qty_left-? where id=?", (q, l["id"])); run("update demands set qty_left=qty_left-? where id=?", (q, d["id"]))
    return {"id": oid, "qty": q, "price": price}


@app.get("/api/orders")
def orders(u=Depends(me)):
    w = "" if u["role"] == "admin" else "where o.farmer_id=? or o.buyer_id=?"
    a = () if u["role"] == "admin" else (u["id"], u["id"])
    return rows(f"select o.*, f.name farmer, b.name buyer from orders o join users f on f.id=o.farmer_id join users b on b.id=o.buyer_id {w} order by o.id desc limit 80", a)


FLOW = {"pay_deposit": ("agreed", "deposit_paid", "buyer"), "deliver": ("deposit_paid", "delivered", "farmer"), "settle": ("delivered", "settled", "buyer")}


@app.post("/api/orders/{oid}/{act}")
def order_act(oid: int, act: str, u=Depends(me)):
    o = one("select * from orders where id=?", (oid,))
    if not o: raise HTTPException(404, "Order not found")
    if u["id"] not in (o["farmer_id"], o["buyer_id"]) and u["role"] != "admin": raise HTTPException(403, "This is not your order")
    tot = o["qty"] * o["price"]; dep = round(tot * o["deposit_pct"] / 100)
    if act in FLOW:
        a, b, r = FLOW[act]
        if o["status"] != a: raise HTTPException(400, f"The order must be {a.replace('_', ' ')} first")
        who = o["buyer_id"] if r == "buyer" else o["farmer_id"]
        if u["id"] != who and u["role"] != "admin": raise HTTPException(403, f"Only the {r} can do this")
        run("update orders set status=? where id=?", (b, oid))
        if b == "deposit_paid": led(oid, "deposit_held", dep)
        if b == "settled": led(oid, "deposit_released", dep); led(oid, "final_payment", tot - dep); led(oid, "fee", round(tot * engine.FEE))
    elif act == "dispute" and o["status"] in ("deposit_paid", "delivered"):
        run("update orders set status='disputed' where id=?", (oid,))
    elif act == "cancel" and o["status"] == "agreed":
        run("update orders set status='cancelled' where id=?", (oid,))
        run("update listings set qty_left=qty_left+? where id=?", (o["qty"], o["listing_id"])); run("update demands set qty_left=qty_left+? where id=?", (o["qty"], o["demand_id"]))
    else:
        raise HTTPException(400, "That action is not allowed for this order")
    return {"ok": True}


# ---------- hub ----------
@app.get("/api/hub")
def hub(u=Depends(me)):
    raw = 600
    prods = [engine.economics(p, raw) for p in rows("select * from products")]
    b = rows("select * from batches order by id desc")
    summ = []
    for p in sorted({x["product"] for x in b}):
        z = [x for x in b if x["product"] == p]; ik = sum(x["input_kg"] for x in z); ok = sum(x["output_kg"] for x in z)
        summ.append({"product": p, "batches": len(z), "input_kg": ik, "output_kg": ok, "yield_pct": round(ok / ik * 100, 1), "margin": sum(x["revenue"] - x["cost"] for x in z)})
    return {"products": prods, "notices": rows("select * from notices"), "batches": b[:8], "summary": summ}


@app.post("/api/hub/offers")
def offer(b: Offer, u=Depends(me)):
    n = one("select * from notices where id=?", (b.notice_id,))
    if not n or b.kg < n["min_kg"]: raise HTTPException(400, f"The minimum for this notice is {n['min_kg'] if n else 0} kg")
    return {"id": run("insert into offers(user_id,notice_id,kg,status,created) values(?,?,?,?,?)", (u["id"], b.notice_id, b.kg, "pending", dt.date.today().isoformat()))}


@app.get("/api/hub/offers")
def offers(u=Depends(me)):
    w = "" if u["role"] in ("hub", "admin") else "where o.user_id=?"
    return rows(f"select o.*, u.name farmer, n.product, n.raw_price from offers o join users u on u.id=o.user_id join notices n on n.id=o.notice_id {w} order by o.id desc limit 40", () if not w else (u["id"],))


@app.post("/api/hub/offers/{i}/{act}")
def offer_act(i: int, act: str, u=Depends(me)):
    if u["role"] not in ("hub", "admin") or act not in ("accept", "reject"): raise HTTPException(403, "Only the Hub can respond to offers")
    run("update offers set status=? where id=?", ("accepted" if act == "accept" else "rejected", i)); return {"ok": True}


# ---------- information ----------
@app.get("/api/opportunities")
def opps(district: Optional[str] = None, u=Depends(me)):
    r = rows("select * from opportunities order by deadline")
    return [o for o in r if not district or district == "All" or "All" in o["districts"] or district in o["districts"]]


@app.get("/api/plans")
def plans(u=Depends(me)): return rows("select * from plans")


@app.get("/api/stats")
def stats(u=Depends(me)):
    if u["role"] != "admin": raise HTTPException(403, "Insights are for administrators")
    sc = lambda s, a=(): list(one(s, a).values())[0] or 0
    status = {x["status"]: x["n"] for x in rows("select status,count(*) n from orders group by status")}
    batches = rows("select * from batches")
    return {"farmers": sc("select count(*) from users where role='farmer'"), "buyers": sc("select count(*) from users where role='buyer'"),
            "open_listings": sc("select count(*) from listings where qty_left>0"), "open_demands": sc("select count(*) from demands where qty_left>0"),
            "orders": status, "gmv": sc("select sum(qty*price) from orders where status not in ('cancelled')"),
            "gmv_settled": sc("select sum(qty*price) from orders where status='settled'"),
            "fees": sc("select sum(amount) from ledger where kind='fee'"), "held": sc("select (select coalesce(sum(amount),0) from ledger where kind='deposit_held') - (select coalesce(sum(amount),0) from ledger where kind='deposit_released')"),
            "subscriptions_mrr": sc("select sum(p.price) from users u join plans p on p.name=u.plan"),
            "hub_margin": sum(b["revenue"] - b["cost"] for b in batches), "hub_revenue": sum(b["revenue"] for b in batches),
            "price_records": sc("select count(*) from prices"), "cases": sc("select count(*) from cases"),
            "plan_mix": rows("select plan name,count(*) n from users group by plan order by n desc")}


app.mount("/", StaticFiles(directory=os.path.join(HERE, "..", "frontend"), html=True), name="web")
