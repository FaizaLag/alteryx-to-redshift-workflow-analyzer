"""Generate synthetic test data for the Alteryx-to-Redshift Workflow Analyzer.

All data is invented. No real people, organizations, or codes.
Run: python tests/generate_test_data.py  (writes CSVs to tests/data/)
"""
import csv
import random
from datetime import date, timedelta
from pathlib import Path

random.seed(42)  # same data every run
OUT = Path(__file__).parent / "data"
OUT.mkdir(parents=True, exist_ok=True)

TODAY = date(2026, 9, 28)
REGIONS = ["North", "South", "East", "West"]
PLANS = ["PPO", "HMO", "HDHP"]
PROGRAMS = ["Care Navigation", "Surgery Support", "Second Opinion", "Maternity Support"]
NAVIGATORS = [f"N{i:02d}" for i in range(1, 7)]


def rand_date(start, end):
    return start + timedelta(days=random.randint(0, (end - start).days))


def write(name, header, rows):
    with open(OUT / name, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(header)
        w.writerows(rows)


# ---------- members.csv (WF1, WF2, WF4) ----------
members = []
for i in range(1, 41):
    enroll = rand_date(date(2022, 1, 1), date(2026, 6, 30))
    active = random.random() < 0.8
    term = "" if active else rand_date(enroll + timedelta(days=30), TODAY).isoformat()
    members.append([f"M{i:04d}", random.randint(1945, 2002), random.choice(REGIONS),
                    random.choice(PLANS), "Active" if active else "Termed",
                    enroll.isoformat(), term])
write("members.csv",
      ["member_id", "birth_year", "region", "plan_type", "status", "enroll_date", "term_date"],
      members)
member_ids = [m[0] for m in members]

# ---------- cases.csv (WF2, WF4) ----------
cases = []
for i in range(1, 61):
    opened = rand_date(date(2026, 1, 5), date(2026, 9, 20))
    is_open = random.random() < 0.25
    closed = "" if is_open else min(opened + timedelta(days=random.randint(5, 60)), TODAY).isoformat()
    cases.append([f"C{1000 + i}", random.choice(member_ids), random.choice(PROGRAMS),
                  opened.isoformat(), closed, "Open" if is_open else "Closed",
                  random.choice(NAVIGATORS)])
write("cases.csv",
      ["case_id", "member_id", "program", "open_date", "close_date", "status", "navigator_id"],
      cases)

# ---------- monthly extracts (WF3) ----------
def month_rows(n, year, month, start_id):
    rows = []
    for k in range(n):
        d = rand_date(date(year, month, 1), date(year, month, 28))
        rows.append([f"C{start_id + k}", random.choice(member_ids), random.choice(PROGRAMS),
                     d, random.choice(["Open", "Closed"])])
    return rows

jul = month_rows(18, 2026, 7, 2001)
aug = month_rows(20, 2026, 8, 2101)
sep = month_rows(20, 2026, 9, 2201)

# July: US text dates MM/DD/YYYY
write("cases_2026_07.csv", ["case_id", "member_id", "program", "open_date", "status"],
      [[r[0], r[1], r[2], r[3].strftime("%m/%d/%Y"), r[4]] for r in jul])

# August: ISO dates, one missing member_id
aug_out = [[r[0], r[1], r[2], r[3].isoformat(), r[4]] for r in aug]
aug_out[7][1] = ""
write("cases_2026_08.csv", ["case_id", "member_id", "program", "open_date", "status"], aug_out)

# September: renamed column, DD-Mon-YYYY dates, lowercase status, 2 cases carried over from August
sep_out = [[r[0], r[1], r[2], r[3].strftime("%d-%b-%Y"), r[4].lower()] for r in sep]
for src in (aug[2], aug[5]):
    sep_out.append([src[0], src[1], src[2], src[3].strftime("%d-%b-%Y"), "closed"])
write("cases_2026_09.csv", ["case_id", "member_id", "program_name", "open_date", "status"], sep_out)

# ---------- claims.csv (WF4) ----------
procs = [f"PROC-{c}" for c in range(101, 111)]
closed_cases = [c for c in cases if c[5] == "Closed"]
claims = []
for i in range(1, 61):
    case = random.choice(closed_cases)
    proc = "PROC-111" if i in (17, 44) else random.choice(procs)  # code missing from benchmarks
    amount = round(random.uniform(250, 18000), 2)
    amount_txt = f"${amount:,.2f}" if i % 10 == 3 else f"{amount:.2f}"  # some formatted as currency text
    steered = random.random() < 0.6
    ref = random.randint(1, 999)
    if not steered:
        note = "Member chose original provider"
    elif i % 7 == 0:
        note = f"ref#nav-2026-{ref}; moved to lower cost site"      # lowercase, no zero padding
    elif i % 11 == 0:
        note = "Steered to in-network facility, ref pending"          # no reference at all
    else:
        note = f"Ref NAV-2026-{ref:04d}: steered to in-network facility"
    claims.append([f"CL{50000 + i}", case[1], case[0],
                   rand_date(date.fromisoformat(case[3]), TODAY).isoformat(),
                   proc, amount_txt, "Y" if steered else "N", note])
write("claims.csv",
      ["claim_id", "member_id", "case_id", "service_date", "proc_code",
       "allowed_amount", "steered_flag", "navigator_note"],
      claims)

# ---------- benchmarks.csv (WF4) ----------
write("benchmarks.csv", ["proc_code", "benchmark_cost"],
      [[p, round(random.uniform(1500, 22000), 2)] for p in procs])

print("Wrote:", ", ".join(sorted(p.name for p in OUT.glob("*.csv"))))
