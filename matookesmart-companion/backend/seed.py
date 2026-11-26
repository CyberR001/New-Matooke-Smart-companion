"""Builds the SQLite schema and a realistic seeded dataset."""
import os, sqlite3, random, hashlib, math, datetime as dt
import engine

SCHEMA = """
create table users(id integer primary key, name text, phone text unique, pin_hash text, salt text, role text, district text,
  plan text, acres real, harvest text, bunches integer, created text);
create table sessions(token text primary key, user_id integer);
create table prices(id integer primary key, market text, date text, price integer, source text);
create table listings(id integer primary key, user_id integer, district text, qty integer, qty_left integer, price integer,
  harvest_date text, advance_pct integer, created text);
create table demands(id integer primary key, user_id integer, district text, qty integer, qty_left integer, price integer,
  deliver_date text, deposit_pct integer, created text);
create table orders(id integer primary key, listing_id integer, demand_id integer, farmer_id integer, buyer_id integer, qty integer,
  price integer, deposit_pct integer, status text, created text);
create table ledger(id integer primary key, order_id integer, kind text, amount integer, created text);
create table opportunities(id integer primary key, title text, kind text, districts text, requirements text, deadline text,
  how text, source text, checked text);
create table products(id integer primary key, name text, yield_pct real, proc_cost integer, pack_cost integer, price_kg integer);
create table notices(id integer primary key, product text, raw_price integer, min_kg integer, districts text, quality text);
create table offers(id integer primary key, user_id integer, notice_id integer, kg integer, status text, created text);
create table batches(id integer primary key, code text, product text, input_kg integer, output_kg integer, cost integer,
  revenue integer, date text);
create table plans(name text primary key, price integer, audience text, perks text);
create table cases(id integer primary key, user_id integer, symptoms text, top text, confidence real, created text);
"""
MARKETS = {"Kampala": 16500, "Masaka": 14500, "Mpigi": 15000, "Mbarara": 13500, "Bushenyi": 13000, "Isingiro": 12500, "Kiboga": 14000, "Jinja": 15500}
FIRST = "Nakato Namukasa Kato Ssemakula Atuhaire Tumusiime Byaruhanga Nabirye Mugisha Akampurira Kyomuhendo Nalubega Ssekandi Tusiime Ainembabazi Mukasa Namatovu Kiiza Asiimwe Birungi Okello Nansubuga Muhwezi Ssebunya Nankya Turyahabwe".split()
LAST = "Ssali Kabuye Mwesigwa Nambooze Kyagulanyi Rwakaikara Babirye Lwanga Kamya Ntambi Bagonza Zawedde Sebugwawo Kisakye Nuwagaba Wamala".split()
BUY = [("Nakasero Market Stall", 1), ("Owino Fresh Traders", 1), ("Kasubi Grocers", 1), ("St. Mary’s Secondary School Kitchen", 2),
       ("Kampala Hospital Catering", 2), ("Jinja Road Restaurant", 2), ("Masaka Wholesale Depot", 1), ("Lakeview Hotel Kitchen", 2),
       ("Mbarara Town Traders", 1), ("Kiboga Produce Buyers", 1), ("Makerere Catering Unit", 2), ("Entebbe Road Eatery", 2),
       ("Bushenyi Market Women Group", 1), ("Mpigi Fresh Supplies", 1), ("Kyambogo Canteen", 2), ("Isingiro Traders Union", 1),
       ("Nile View Lodge", 2), ("Kawempe Retail Hub", 1), ("Greenfields Primary School", 2), ("Nsambya Food Court", 2),
       ("Kabalagala Matooke Dealers", 1), ("Ntinda Supermarket", 2), ("Rubaga Catering Services", 2), ("Wakiso Traders", 1)]


def hp(pin, salt):
    return hashlib.sha256((salt + pin).encode()).hexdigest()


def build(path):
    if os.path.exists(path):
        os.remove(path)
    c = sqlite3.connect(path); c.executescript(SCHEMA)
    R = random.Random(7); today = dt.date.today(); now = today.isoformat()
    D = list(MARKETS)

    def user(name, phone, role, district, plan, **k):
        salt = "s%d" % R.randint(1000, 9999)
        cur = c.execute("insert into users(name,phone,pin_hash,salt,role,district,plan,acres,harvest,bunches,created) values(?,?,?,?,?,?,?,?,?,?,?)",
                        (name, phone, hp("1234", salt), salt, role, district, plan, k.get("acres"), k.get("harvest"), k.get("bunches"),
                         (today - dt.timedelta(days=R.randint(10, 300))).isoformat()))
        return cur.lastrowid

    user("MatookeSmart Admin", "0700000000", "admin", "Kampala", "Professional Farmer")
    user("MatookeSmart Hub", "0700000001", "hub", "Masaka", "Buyer / Institution")
    first_d = ["Masaka", "Masaka", "Mbarara", "Mpigi", "Bushenyi", "Jinja", "Kiboga", "Isingiro"]
    farmers = []
    for i in range(60):
        d = first_d[i] if i < 8 else D[i % len(D)]
        plan = R.choices(["Basic Farmer", "Smart Farmer", "Professional Farmer"], [78, 17, 5])[0]
        farmers.append(user(f"{R.choice(FIRST)} {R.choice(LAST)}", "07720%05d" % (i + 1), "farmer", d, plan, acres=round(R.uniform(0.8, 6), 1),
                            harvest=(today + dt.timedelta(days=R.randint(8, 56))).isoformat(), bunches=R.randint(40, 420)))
    buyers = []
    bd0 = ["Masaka", "Kampala", "Jinja", "Mpigi"]
    for i, (n, inst) in enumerate(BUY):
        buyers.append(user(n, "07820%05d" % (i + 1), "buyer", bd0[i] if i < 4 else D[i % len(D)], "Buyer / Institution" if inst == 2 else "Buyer Basic"))
    start = today - dt.timedelta(days=today.weekday())
    for m, base in MARKETS.items():
        phase = R.uniform(-5, 5)
        for t in range(104):
            day = start - dt.timedelta(weeks=103 - t)
            w = day.isocalendar()[1]
            season = 1 + 0.13 * math.sin(2 * math.pi * (w - 8 + phase) / 52)
            p = base * season * (1 + 0.0007 * t) * (1 + R.gauss(0, 0.03))
            c.execute("insert into prices(market,date,price,source) values(?,?,?,?)", (m, day.isoformat(), round(p, -2), R.choice(["Market survey", "Trader report", "Farmer report"])))
    udist = {r[0]: r[1] for r in c.execute("select id,district from users")}
    for i in range(95):
        f = R.choice(farmers); fu = udist[f]; q = R.randint(30, 300)
        c.execute("insert into listings(user_id,district,qty,qty_left,price,harvest_date,advance_pct,created) values(?,?,?,?,?,?,?,?)",
                  (f, fu, q, q, round(MARKETS[fu] * R.uniform(0.9, 1.05), -2), (today + dt.timedelta(days=R.randint(5, 70))).isoformat(), R.choice([15, 20, 25, 30, 40]),
                   (today - dt.timedelta(days=R.randint(0, 40))).isoformat()))
    for i in range(60):
        b = R.choice(buyers); bd = udist[b]; q = R.randint(40, 350)
        c.execute("insert into demands(user_id,district,qty,qty_left,price,deliver_date,deposit_pct,created) values(?,?,?,?,?,?,?,?)",
                  (b, bd, q, q, round(MARKETS[bd] * R.uniform(0.92, 1.12), -2), (today + dt.timedelta(days=R.randint(5, 70))).isoformat(), R.choice([15, 20, 25, 30]),
                   (today - dt.timedelta(days=R.randint(0, 40))).isoformat()))
    c.row_factory = sqlite3.Row
    L = [dict(x) for x in c.execute("select * from listings")]; Dm = [dict(x) for x in c.execute("select * from demands")]
    c.row_factory = None
    made = 0
    for l in R.sample(L, len(L)):
        if made >= 42:
            break
        cand = engine.rank(l, Dm, True)
        if not cand:
            continue
        d = next(x for x in Dm if x["id"] == cand[0]["id"]); q = min(l["qty_left"], d["qty_left"])
        if q <= 0:
            continue
        price = int(round((l["price"] + d["price"]) / 2, -2)); dep = max(l["advance_pct"], d["deposit_pct"])
        st = R.choices(["agreed", "deposit_paid", "delivered", "settled", "disputed"], [9, 10, 6, 15, 1])[0]
        when = (today - dt.timedelta(days=R.randint(1, 80))).isoformat()
        oid = c.execute("insert into orders(listing_id,demand_id,farmer_id,buyer_id,qty,price,deposit_pct,status,created) values(?,?,?,?,?,?,?,?,?)",
                        (l["id"], d["id"], l["user_id"], d["user_id"], q, price, dep, st, when)).lastrowid
        l["qty_left"] -= q; d["qty_left"] -= q
        c.execute("update listings set qty_left=? where id=?", (l["qty_left"], l["id"])); c.execute("update demands set qty_left=? where id=?", (d["qty_left"], d["id"]))
        tot = q * price; depa = round(tot * dep / 100)
        if st != "agreed":
            c.execute("insert into ledger(order_id,kind,amount,created) values(?,?,?,?)", (oid, "deposit_held", depa, when))
        if st == "settled":
            for k, a in (("deposit_released", depa), ("final_payment", tot - depa), ("fee", round(tot * engine.FEE))):
                c.execute("insert into ledger(order_id,kind,amount,created) values(?,?,?,?)", (oid, k, a, when))
        made += 1
    for i, f in enumerate(farmers[:8]):
        fu = udist[f]
        c.execute("insert into listings(user_id,district,qty,qty_left,price,harvest_date,advance_pct,created) values(?,?,?,?,?,?,?,?)",
                  (f, fu, 120 + 30 * i, 120 + 30 * i, MARKETS[fu] - 500, (today + dt.timedelta(days=21 + 3 * i)).isoformat(), 25, now))
    for i, b in enumerate(buyers[:4]):
        bd = udist[b]
        c.execute("insert into demands(user_id,district,qty,qty_left,price,deliver_date,deposit_pct,created) values(?,?,?,?,?,?,?,?)",
                  (b, bd, 150 + 40 * i, 150 + 40 * i, MARKETS[bd] + 300, (today + dt.timedelta(days=24 + 4 * i)).isoformat(), 25, now))
    for p in [("Matooke flour", 20, 180, 400, 8000), ("Dried matooke chips", 22, 160, 350, 7000), ("Matooke crisps", 12, 400, 700, 14000), ("Peeled matooke (ready to cook)", 62, 120, 250, 2600)]:
        c.execute("insert into products(name,yield_pct,proc_cost,pack_cost,price_kg) values(?,?,?,?,?)", p)
    for n in [("Matooke flour", 650, 100, "Masaka,Mpigi,Bushenyi,Mbarara", "Mature green bunches, no rot, delivered within 24 hours of cutting"),
              ("Dried matooke chips", 600, 150, "Masaka,Mpigi,Kiboga", "Peeled and sun-dried to below 12% moisture, clean and mould free"),
              ("Matooke crisps", 700, 80, "Kampala,Mpigi,Jinja", "Firm green fingers, uniform size, no bruising"),
              ("Peeled matooke (ready to cook)", 620, 200, "Kampala,Jinja,Mpigi", "Fresh bunches cut within 48 hours of delivery")]:
        c.execute("insert into notices(product,raw_price,min_kg,districts,quality) values(?,?,?,?,?)", n)
    pr = {"Matooke flour": (20, 8000), "Dried matooke chips": (22, 7000), "Matooke crisps": (12, 14000), "Peeled matooke (ready to cook)": (62, 2600)}
    for i in range(16):
        p = R.choice(list(pr)); y, price = pr[p]; ik = R.randint(300, 1400); ok = round(ik * (y / 100) * R.uniform(0.9, 1.08))
        cost = round(ik * 830 + ok * 400 * R.uniform(0.9, 1.1)); rev = round(ok * price * R.uniform(0.88, 1.0))
        c.execute("insert into batches(code,product,input_kg,output_kg,cost,revenue,date) values(?,?,?,?,?,?,?)",
                  ("B%03d" % (i + 1), p, ik, ok, cost, rev, (today - dt.timedelta(days=5 * (16 - i))).isoformat()))
    for i in range(8):
        c.execute("insert into offers(user_id,notice_id,kg,status,created) values(?,?,?,?,?)",
                  (R.choice(farmers), R.randint(1, 4), R.randint(100, 800), R.choice(["pending", "pending", "accepted", "rejected"]), (today - dt.timedelta(days=R.randint(0, 20))).isoformat()))
    for t, k, dd, req, how, src in [
        ("Tissue-culture banana planting material distribution", "Planting material", "Masaka,Mpigi,Bushenyi", "Registered farmers with at least 1 acre", "Register with the sub-county agricultural officer", "District Production Office"),
        ("Banana disease management training", "Training", "All", "Open to all farmers; farmer groups get priority", "Sign up at the sub-county office or through the app", "District Agricultural Office"),
        ("Farmer group input support", "Inputs", "Mbarara,Isingiro,Bushenyi", "Organised groups of 15 or more", "Submit group registration and member list", "District Production Office"),
        ("Matooke value-addition skills workshop", "Training", "Kampala,Jinja,Mpigi", "Farmers and youth interested in processing", "Register by phone with the organiser", "Agricultural Training Partner"),
        ("Agricultural enterprise grant for young farmers", "Grant", "All", "Farmers aged 18 to 35 with a business plan", "Submit a short application with ID and plan", "Youth Livelihood Programme"),
        ("Extension officer farm visits", "Extension", "Kiboga,Mpigi,Masaka", "Farmers reporting suspected disease", "Request a visit through the sub-county office", "District Extension Service"),
        ("Mulching and soil fertility field day", "Training", "Masaka,Bushenyi,Mbarara", "Open to all farmers", "Attend the field day at the host farm", "Farmer Cooperative"),
        ("Cooperative membership drive", "Extension", "All", "Farmers growing matooke commercially", "Visit the nearest cooperative office", "Farmer Cooperative"),
        ("Post-harvest handling and storage training", "Training", "Kampala,Jinja,Kiboga", "Farmers and traders", "Register through the organiser", "Agricultural Training Partner"),
        ("Irrigation starter support", "Inputs", "Isingiro,Mbarara", "Farmers with a reliable water source", "Apply through the district production office", "District Production Office"),
        ("Matooke export readiness briefing", "Extension", "Kampala,Jinja", "Traders and processors", "Register for the briefing", "Trade Promotion Partner"),
        ("Farmer savings and record-keeping training", "Training", "All", "Open to all farmers", "Sign up at the sub-county office", "Community Development Office")]:
        c.execute("insert into opportunities(title,kind,districts,requirements,deadline,how,source,checked) values(?,?,?,?,?,?,?,?)",
                  (t, k, dd, req, (today + dt.timedelta(days=R.randint(10, 90))).isoformat(), how, src, now))
    for p in [("Basic Farmer", 0, "farmer", "Prices, disease guidance, opportunities, marketplace"), ("Smart Farmer", 5000, "farmer", "Price alerts, farm records, extra advice"),
              ("Professional Farmer", 15000, "farmer", "Analytics, priority buyers, business reports"), ("Buyer Basic", 0, "buyer", "Browse supply, post requirements"),
              ("Buyer / Institution", 50000, "buyer", "Supplier discovery, bulk and recurring orders, order history")]:
        c.execute("insert into plans values(?,?,?,?)", p)
    c.commit(); c.close()


if __name__ == "__main__":
    p = os.environ.get("DB_PATH", os.path.join(os.path.dirname(os.path.abspath(__file__)), "matookesmart.db"))
    build(p); print("Seeded", p)
