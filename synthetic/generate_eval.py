"""Generator v2: the evaluation set EV001-EV030 (synthetic/eval_households/).

Usage (from the repo root, with the backend venv):
    python -m synthetic.generate_eval              # 30 households, renders + photo-like images
    python -m synthetic.generate_eval --no-render  # ground truth only

v1 (generate.py, HH001-HH010) is unchanged; the sweep videos depend on it. Differences in v2:
- a quota schedule instead of random draws: >= 4 of each planted error type, households of 5-6
  members, incomes on every scheme boundary (21,000 / 100,000 / 150,000 / 250,000), members aged
  exactly 18 / 21 / 64 / 65 at the reference date, elderly members in low-income households
- ration cards show a colour (Yellow / Orange with a "Priority Household" stamp / White)
- Neo-Buddhist caste category; rare names and unusual spellings
- a child never gets their father's (or late father's) given name
- missing documents are planted only for adults' identity cards and the income certificate
"""

import argparse
import itertools
import random
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path

from synthetic import names as N
from synthetic import names_eval as E
from synthetic.generate import (
    ERROR_TYPES,
    REFERENCE_DATE,
    VALID_INCOME_CERT_AGE_DAYS,
    _address,
    _Ctx,
    _digits,
    _dob_for_age,
    _identity_number,
    _income_dates,
    _name_fields,
    _plant_dob_mismatch,
    _plant_expired,
    _plant_not_on_ration_card,
    _ration_row,
    fmt_date,
    write_household,
    years_before,
)
from synthetic.schema import Document, Household, Member, Name, PlantedError

SEED = 2029
N_HOUSEHOLDS = 30
OUT_DIR = Path(__file__).resolve().parent / "eval_households"

SIZES = [2, 3, 4, 5, 6, 3, 4, 5, 6, 4]
INCOMES = [12000, 21000, 21001, 60000, 100000, 100001, 150000, 150001, 250000, 250001]
COLOURS = ["yellow", "orange", "white"]
CASTES: list[N.Pair | None] = [
    N.CASTE_CATEGORIES[0],  # SC
    N.CASTE_CATEGORIES[1],  # ST
    N.CASTE_CATEGORIES[2],  # OBC
    E.NEO_BUDDHIST,
    N.CASTE_CATEGORIES[3],  # VJNT
    None,  # no caste certificate in the household
]
ELDERLY_AGES = [65, 72, 64, 80]
BOUNDARY_AGES = {18, 21, 64, 65}  # born exactly that many years before the reference date
RARE_PROBABILITY = 0.35


@dataclass(frozen=True)
class Plan:
    index: int
    size: int
    income: int
    colour: str
    caste: N.Pair | None
    elderly_age: int | None
    child_age: int | None  # an adult child aged exactly 18 or 21
    female_head: bool
    errors: tuple[str, ...]


def schedule() -> list[Plan]:
    """Deterministic plan for EV001-EV030 (no randomness here)."""
    errors = itertools.cycle(ERROR_TYPES)
    plans = []
    for i in range(N_HOUSEHOLDS):
        planted: list[str] = []
        if i % 5 != 0:  # 6 clean households, to measure false alarms
            planted.append(next(errors))
            if i % 3 == 0:
                planted.append(next(errors))
        income = INCOMES[i % len(INCOMES)]
        plans.append(Plan(
            index=i + 1,
            size=SIZES[i % len(SIZES)],
            income=income,
            colour=COLOURS[i % len(COLOURS)],
            # a date-of-birth mismatch needs a second document with a date of birth (caste certificate)
            caste=CASTES[i % len(CASTES)] or (N.CASTE_CATEGORIES[0] if "dob_mismatch" in planted else None),
            elderly_age=ELDERLY_AGES[i % len(ELDERLY_AGES)] if (income <= 21001 or i % 4 == 0) else None,
            child_age={1: 18, 3: 21}.get(i % 7),
            female_head=i % 6 == 2,
            errors=tuple(planted),
        ))
    return plans


# ---------- members ----------

def _members(plan: Plan, rng: random.Random) -> list[Member]:
    surname = rng.choice(E.RARE_SURNAMES if rng.random() < RARE_PROBABILITY else N.SURNAMES)
    used: set[str] = set()  # every given AND middle name in the family, so no child repeats one

    def pick(common: list[N.Pair], rare: list[N.Pair]) -> N.Pair:
        pool = rare if rng.random() < RARE_PROBABILITY else common
        choice = rng.choice([p for p in pool if p.en not in used] or [p for p in common + rare if p.en not in used])
        used.add(choice.en)
        return choice

    def male() -> N.Pair:
        return pick(N.MALE_NAMES, E.RARE_MALE_NAMES)

    def female() -> N.Pair:
        return pick(N.FEMALE_NAMES, E.RARE_FEMALE_NAMES)

    members: list[Member] = []

    def add(given: N.Pair, middle: N.Pair, relation: str, gender: str, age: int) -> Member:
        rel = N.RELATIONS.get(relation) or E.RELATIONS_EXTRA[relation]
        dob = years_before(REFERENCE_DATE, age) if age in BOUNDARY_AGES else _dob_for_age(age, rng)
        m = Member(
            id=f"m{len(members) + 1}", given=Name(**given._asdict()), middle=Name(**middle._asdict()),
            surname=Name(**surname._asdict()), relation=Name(**rel._asdict()), gender=gender, dob=dob, age=age,
        )
        members.append(m)
        return m

    child_age = plan.child_age
    head_age = rng.randint(42, 58) if child_age else rng.randint(30, 58)
    if plan.elderly_age:
        head_age = min(head_age, plan.elderly_age - 22)
        if child_age and head_age - 4 - 19 < child_age:
            child_age = None  # not enough generations to fit both; keep the elderly member
    if plan.female_head:
        late_husband = male()
        add(female(), late_husband, "self", "F", head_age)
        mother_age = head_age
        if plan.elderly_age and len(members) < plan.size:
            add(female(), male(), "mother_in_law", "F", plan.elderly_age)
        child_middle = late_husband
    else:
        head_father = male()
        head = add(male(), head_father, "self", "M", head_age)
        mother_age = head_age - 3
        if len(members) < plan.size and (not plan.elderly_age or plan.size >= 3):
            mother_age = head_age - rng.randint(2, 4)
            add(female(), N.Pair(head.given.mr, head.given.en), "wife", "F", mother_age)
        if plan.elderly_age and len(members) < plan.size:
            if rng.random() < 0.5:
                add(female(), head_father, "mother", "F", plan.elderly_age)
            else:
                add(head_father, male(), "father", "M", plan.elderly_age)
        child_middle = N.Pair(head.given.mr, head.given.en)

    first = True
    while len(members) < plan.size:
        gender = rng.choice("MF")
        given = male() if gender == "M" else female()
        oldest = max(1, min(mother_age - 19, 30))
        age = child_age if (first and child_age and child_age <= mother_age - 19) else rng.randint(1, oldest)
        first = False
        add(given, child_middle, "son" if gender == "M" else "daughter", gender, age)
    return members


# ---------- documents ----------

def _documents(plan: Plan, rng: random.Random, members: list[Member]) -> list[Document]:
    head = members[0]
    address = _address(rng)
    card = E.CARD_COLOURS[plan.colour]
    docs = [Document(
        id="ration_card", type="ration_card", member_ids=[m.id for m in members],
        fields={
            "card_number": f"SPEC-RC-{_digits(rng, 8)}",
            "card_colour": plan.colour,
            "category_mr": card["category"].mr, "category_en": card["category"].en,
            "head_name_mr": head.full_name.mr, "head_name_en": head.full_name.en,
            **address,
            "members": [_ration_row(m) for m in members],
        },
    )]
    numbers: set[str] = set()
    for m in members:
        number = _identity_number(rng)
        while number in numbers:
            number = _identity_number(rng)
        numbers.add(number)
        g = N.GENDERS[m.gender]
        docs.append(Document(
            id=f"identity_card_{m.id}", type="identity_card", member_ids=[m.id],
            fields={**_name_fields(m.full_name), "dob": fmt_date(m.dob), "gender_mr": g.mr, "gender_en": g.en,
                    "id_number": number},
        ))
    docs.append(Document(
        id=f"income_certificate_{head.id}", type="income_certificate", member_ids=[head.id],
        fields={"certificate_number": f"SPEC/INC/{_digits(rng, 6)}", **_name_fields(head.full_name), **address,
                "annual_income": plan.income, **_income_dates(rng, VALID_INCOME_CERT_AGE_DAYS),
                "office_mr": N.OFFICE.mr, "office_en": N.OFFICE.en},
    ))
    if plan.caste is not None:
        holders = [head]
        others = [m for m in members[1:] if m.age >= 5]
        if others and rng.random() < 0.6:
            holders.append(rng.choice(others))
        for m in holders:
            issued = REFERENCE_DATE - timedelta(days=rng.randint(30, min(15 * 365, m.age * 365)))
            docs.append(Document(
                id=f"caste_certificate_{m.id}", type="caste_certificate", member_ids=[m.id],
                fields={"certificate_number": f"SPEC/CC/{_digits(rng, 6)}", **_name_fields(m.full_name),
                        "dob": fmt_date(m.dob), "category_mr": plan.caste.mr, "category_en": plan.caste.en,
                        **address, "issue_date": fmt_date(issued), "office_mr": N.OFFICE.mr, "office_en": N.OFFICE.en},
            ))
    return docs


# ---------- planted errors (v2 rules) ----------

def _plant_name_mismatch_v2(ctx: _Ctx) -> PlantedError | None:
    """As v1, but rare names have spelling variants too."""
    options = []
    for d in ctx.free_docs():
        m = ctx.members[d.member_ids[0]]
        if m.on_ration_card:
            options += [(d, m, part) for part in ("given", "surname") if getattr(m, part).en in E.ALL_VARIANTS]
    if not options:
        return None
    d, m, part = ctx.rng.choice(options)
    printed = m.model_copy(update={part: Name(**E.ALL_VARIANTS[getattr(m, part).en]._asdict())}).full_name
    d.fields.update(_name_fields(printed))
    return PlantedError(type="name_mismatch", member_id=m.id, documents=[d.id, "ration_card"], field="name",
                        expected=m.full_name.model_dump(), printed=printed.model_dump(),
                        note=f"{part} spelled differently")


def _plant_missing_document_v2(ctx: _Ctx) -> PlantedError | None:
    """Only an adult's identity card or the income certificate (the documents that are always expected)."""
    options = [d for d in ctx.free_docs()
               if d.type == "income_certificate"
               or (d.type == "identity_card" and ctx.members[d.member_ids[0]].age >= 18)]
    if not options:
        return None
    d = ctx.rng.choice(options)
    ctx.docs.remove(d)
    return PlantedError(type="missing_document", member_id=d.member_ids[0], documents=[d.id],
                        expected=d.type, note="Document intentionally not generated.")


PLANTERS = {
    "name_mismatch": _plant_name_mismatch_v2,
    "dob_mismatch": _plant_dob_mismatch,
    "expired": _plant_expired,
    "not_on_ration_card": _plant_not_on_ration_card,
    "missing_document": _plant_missing_document_v2,
}


def build_eval_household(plan: Plan, seed: int = SEED, max_attempts: int = 200) -> Household:
    """Deterministic for (seed, plan). Retries with a new sub-seed until every scheduled error fits."""
    hh_id = f"EV{plan.index:03d}"
    for attempt in range(max_attempts):
        rng = random.Random(f"{seed}:{hh_id}:{attempt}")
        members = _members(plan, rng)
        docs = _documents(plan, rng, members)
        ctx = _Ctx(rng, members, docs)
        planted = []
        for t in sorted(plan.errors, key=lambda t: t == "missing_document"):
            err = PLANTERS[t](ctx)
            if err is None:
                break
            planted.append(err)
            ctx.used_docs.update(err.documents)
            ctx.used_members.add(err.member_id)
        else:
            return Household(id=hh_id, seed=seed, reference_date=REFERENCE_DATE, members=members,
                             documents=docs, planted_errors=planted)
    raise RuntimeError(f"{hh_id}: could not plant {plan.errors} in {max_attempts} attempts")


def build_eval_set(seed: int = SEED) -> list[Household]:
    return [build_eval_household(p, seed) for p in schedule()]


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate the v2 evaluation households EV001-EV030")
    parser.add_argument("--no-render", action="store_true")
    parser.add_argument("--out", type=Path, default=OUT_DIR)
    args = parser.parse_args()

    households = build_eval_set()
    if args.no_render:
        args.out.mkdir(parents=True, exist_ok=True)
        for hh in households:
            (args.out / hh.id).mkdir(exist_ok=True)
            (args.out / hh.id / "ground_truth.json").write_text(hh.model_dump_json(indent=2), encoding="utf-8")
    else:
        from synthetic.render import Renderer

        with Renderer() as renderer:
            for hh in households:
                write_household(hh, args.out, renderer)
    from collections import Counter

    errors = Counter(e.type for hh in households for e in hh.planted_errors)
    sizes = Counter(len(hh.members) for hh in households)
    print(f"{len(households)} households, {sum(len(h.documents) for h in households)} documents")
    print(f"planted errors: {dict(errors)}; clean households: {sum(not h.planted_errors for h in households)}")
    print(f"household sizes: {dict(sorted(sizes.items()))}")


if __name__ == "__main__":
    main()
