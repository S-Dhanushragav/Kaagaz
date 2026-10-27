"""Generate synthetic SPECIMEN households: documents, planted errors, renders, ground truth.

Usage (from the repo root, with the backend venv):
    python -m synthetic.generate --n 10 --seed 42

Writes synthetic/households/<id>/ with <doc>.png (clean render), <doc>_photo.jpg
(photo-like) and ground_truth.json. Same seed -> same households.
"""

import argparse
import hashlib
import random
import shutil
from datetime import date, timedelta
from pathlib import Path
from typing import Callable

from synthetic import names as N
from synthetic.schema import Document, ErrorType, Household, Member, Name, PlantedError

REFERENCE_DATE = date(2026, 10, 27)
OUT_DIR = Path(__file__).resolve().parent / "households"

ERROR_TYPES: tuple[ErrorType, ...] = (
    "name_mismatch", "dob_mismatch", "expired", "missing_document", "not_on_ration_card",
)

# Synthetic-only assumption, NOT a validity rule: valid income certificates are issued
# 0-60 days before the reference date, expired ones 3-5 years before, so the label holds
# for any plausible official validity period. rules/engine.py decides expiry for real.
VALID_INCOME_CERT_AGE_DAYS = (0, 60)
EXPIRED_INCOME_CERT_AGE_DAYS = (3 * 365, 5 * 365)


# ---------- dates and numbers ----------

def years_before(d: date, years: int) -> date:
    try:
        return d.replace(year=d.year - years)
    except ValueError:  # Feb 29
        return d.replace(year=d.year - years, day=28)


def age_on(dob: date, ref: date) -> int:
    return ref.year - dob.year - ((ref.month, ref.day) < (dob.month, dob.day))


def fmt_date(d: date) -> str:
    return d.strftime("%d/%m/%Y")


def _dob_for_age(age: int, rng: random.Random) -> date:
    latest = years_before(REFERENCE_DATE, age)
    earliest = years_before(REFERENCE_DATE, age + 1) + timedelta(days=1)
    return earliest + timedelta(days=rng.randrange((latest - earliest).days + 1))


def _digits(rng: random.Random, n: int) -> str:
    return "".join(rng.choice("0123456789") for _ in range(n))


def _identity_number(rng: random.Random) -> str:
    """12 digits starting with 0 or 1, so it can never be a valid real number."""
    return rng.choice("01") + _digits(rng, 11)


def _financial_year(issued: date) -> str:
    """The last completed April-March year before the issue date, e.g. '2025-26'."""
    end = issued.year if issued.month >= 4 else issued.year - 1
    return f"{end - 1}-{str(end)[2:]}"


# ---------- members ----------

def _build_members(rng: random.Random) -> list[Member]:
    size = rng.randint(2, 6)
    surname = rng.choice(N.SURNAMES)
    used: set[str] = set()

    def pick(pool: list[N.Pair]) -> N.Pair:
        choice = rng.choice([p for p in pool if p.en not in used])
        used.add(choice.en)
        return choice

    members: list[Member] = []

    def add(given: N.Pair, middle: N.Pair, relation: str, gender: str, age: int) -> Member:
        m = Member(
            id=f"m{len(members) + 1}",
            given=Name(**given._asdict()),
            middle=Name(**middle._asdict()),
            surname=Name(**surname._asdict()),
            relation=Name(**N.RELATIONS[relation]._asdict()),
            gender=gender,
            dob=_dob_for_age(age, rng),
            age=age,
        )
        members.append(m)
        return m

    head_age = rng.randint(32, 60)
    if rng.random() < 0.85:  # male head with wife
        head_father = rng.choice(N.MALE_NAMES)
        head = add(pick(N.MALE_NAMES), head_father, "self", "M", head_age)
        mother_age = head_age - rng.randint(2, 8)
        add(pick(N.FEMALE_NAMES), N.Pair(head.given.mr, head.given.en), "wife", "F", mother_age)
        if len(members) < size and head_age <= 55 and rng.random() < 0.35:
            add(pick(N.FEMALE_NAMES), head_father, "mother", "F", head_age + rng.randint(22, 30))
        child_middle = N.Pair(head.given.mr, head.given.en)
    else:  # female head (e.g. widowed)
        late_husband = rng.choice(N.MALE_NAMES)
        add(pick(N.FEMALE_NAMES), late_husband, "self", "F", head_age)
        mother_age = head_age
        if len(members) < size and head_age <= 55 and rng.random() < 0.3:
            in_law_age = head_age + rng.randint(24, 32)
            add(pick(N.FEMALE_NAMES), rng.choice(N.MALE_NAMES), "mother_in_law", "F", in_law_age)
        child_middle = late_husband

    while len(members) < size:
        gender = rng.choice("MF")
        pool = N.MALE_NAMES if gender == "M" else N.FEMALE_NAMES
        age = rng.randint(1, max(1, min(mother_age - 20, 30)))
        add(pick(pool), child_middle, "son" if gender == "M" else "daughter", gender, age)
    return members


# ---------- documents ----------

def _address(rng: random.Random) -> dict[str, str]:
    village = rng.choice(N.VILLAGES)
    house = rng.randint(1, 250)
    return {
        "address_mr": f"घर क्र. {house}, मु. पो. {village.mr}, ता. {N.TALUKA.mr}, जि. {N.DISTRICT.mr}",
        "address_en": f"House No. {house}, At/Post {village.en}, Tal. {N.TALUKA.en}, Dist. {N.DISTRICT.en}",
    }


def _name_fields(name: Name) -> dict[str, str]:
    return {"name_mr": name.mr, "name_en": name.en}


def _ration_row(m: Member) -> dict[str, object]:
    g = N.GENDERS[m.gender]
    return {
        **_name_fields(m.full_name),
        "relation_mr": m.relation.mr, "relation_en": m.relation.en,
        "gender_mr": g.mr, "gender_en": g.en,
        "age": m.age,
    }


def _income_dates(rng: random.Random, age_days: tuple[int, int]) -> dict[str, str]:
    issued = REFERENCE_DATE - timedelta(days=rng.randint(*age_days))
    return {"issue_date": fmt_date(issued), "financial_year": _financial_year(issued)}


def _build_documents(rng: random.Random, members: list[Member]) -> list[Document]:
    head = members[0]
    address = _address(rng)
    category = rng.choice(N.RATION_CARD_CATEGORIES)
    docs = [
        Document(
            id="ration_card",
            type="ration_card",
            member_ids=[m.id for m in members],
            fields={
                "card_number": f"SPEC-RC-{_digits(rng, 8)}",
                "category_mr": category.mr, "category_en": category.en,
                "head_name_mr": head.full_name.mr, "head_name_en": head.full_name.en,
                **address,
                "members": [_ration_row(m) for m in members],
            },
        )
    ]

    id_numbers: set[str] = set()
    for m in members:
        number = _identity_number(rng)
        while number in id_numbers:
            number = _identity_number(rng)
        id_numbers.add(number)
        g = N.GENDERS[m.gender]
        docs.append(
            Document(
                id=f"identity_card_{m.id}",
                type="identity_card",
                member_ids=[m.id],
                fields={
                    **_name_fields(m.full_name),
                    "dob": fmt_date(m.dob),
                    "gender_mr": g.mr, "gender_en": g.en,
                    "id_number": number,
                },
            )
        )

    docs.append(
        Document(
            id=f"income_certificate_{head.id}",
            type="income_certificate",
            member_ids=[head.id],
            fields={
                "certificate_number": f"SPEC/INC/{_digits(rng, 6)}",
                **_name_fields(head.full_name),
                **address,
                "annual_income": rng.randrange(24, 301) * 1000,
                **_income_dates(rng, VALID_INCOME_CERT_AGE_DAYS),
                "office_mr": N.OFFICE.mr, "office_en": N.OFFICE.en,
            },
        )
    )

    caste = rng.choice(N.CASTE_CATEGORIES)
    holders = [head]
    children = [m for m in members if m.relation.en in ("Son", "Daughter")]
    if children and rng.random() < 0.5:
        holders.append(rng.choice(children))
    for m in holders:
        issued = REFERENCE_DATE - timedelta(days=rng.randint(30, min(15 * 365, m.age * 365)))
        docs.append(
            Document(
                id=f"caste_certificate_{m.id}",
                type="caste_certificate",
                member_ids=[m.id],
                fields={
                    "certificate_number": f"SPEC/CC/{_digits(rng, 6)}",
                    **_name_fields(m.full_name),
                    "dob": fmt_date(m.dob),
                    "category_mr": caste.mr, "category_en": caste.en,
                    **address,
                    "issue_date": fmt_date(issued),
                    "office_mr": N.OFFICE.mr, "office_en": N.OFFICE.en,
                },
            )
        )
    return docs


# ---------- planted errors ----------

class _Ctx:
    def __init__(self, rng: random.Random, members: list[Member], docs: list[Document]) -> None:
        self.rng = rng
        self.members = {m.id: m for m in members}
        self.docs = docs
        self.used_docs: set[str] = set()
        self.used_members: set[str] = set()

    def free_docs(self, doc_type: str | None = None) -> list[Document]:
        return [
            d for d in self.docs
            if d.id not in self.used_docs
            and d.type != "ration_card"
            and (doc_type is None or d.type == doc_type)
            and not (set(d.member_ids) & self.used_members)
        ]

    def doc(self, doc_id: str) -> Document:
        return next(d for d in self.docs if d.id == doc_id)


def _plant_name_mismatch(ctx: _Ctx) -> PlantedError | None:
    options = []
    for d in ctx.free_docs():
        m = ctx.members[d.member_ids[0]]
        if not m.on_ration_card:
            continue
        for part in ("given", "surname"):
            if getattr(m, part).en in N.VARIANTS:
                options.append((d, m, part))
    if not options:
        return None
    d, m, part = ctx.rng.choice(options)
    variant = N.VARIANTS[getattr(m, part).en]
    printed = m.model_copy(update={part: Name(**variant._asdict())}).full_name
    d.fields.update(_name_fields(printed))
    return PlantedError(
        type="name_mismatch", member_id=m.id, documents=[d.id, "ration_card"], field="name",
        expected=m.full_name.model_dump(), printed=printed.model_dump(),
        note=f"{part} spelled differently",
    )


def _shift_dob(dob: date, rng: random.Random) -> date:
    options = [
        years_before(dob, rng.choice([1, 2, -1])),
        dob + timedelta(days=rng.choice([-5, -3, -1, 1, 2, 4])),
    ]
    if dob.day <= 12 and dob.day != dob.month:  # day/month swapped
        options.append(dob.replace(day=dob.month, month=dob.day))
    shifted = rng.choice(options)
    return shifted if shifted < REFERENCE_DATE else years_before(dob, 1)


def _plant_dob_mismatch(ctx: _Ctx) -> PlantedError | None:
    options = ctx.free_docs("caste_certificate")
    if not options:
        return None
    d = ctx.rng.choice(options)
    m = ctx.members[d.member_ids[0]]
    printed = fmt_date(_shift_dob(m.dob, ctx.rng))
    d.fields["dob"] = printed
    return PlantedError(
        type="dob_mismatch", member_id=m.id, documents=[d.id, f"identity_card_{m.id}"],
        field="dob", expected=fmt_date(m.dob), printed=printed,
    )


def _plant_expired(ctx: _Ctx) -> PlantedError | None:
    options = ctx.free_docs("income_certificate")
    if not options:
        return None
    d = options[0]
    d.fields.update(_income_dates(ctx.rng, EXPIRED_INCOME_CERT_AGE_DAYS))
    return PlantedError(
        type="expired", member_id=d.member_ids[0], documents=[d.id], field="issue_date",
        printed=d.fields["issue_date"],
        note="Issued 3-5 years before reference_date; expiry is decided by the rules engine.",
    )


def _plant_not_on_ration_card(ctx: _Ctx) -> PlantedError | None:
    options = [
        m for m in list(ctx.members.values())[1:]
        if m.id not in ctx.used_members and f"identity_card_{m.id}" not in ctx.used_docs
    ]
    if not options:
        return None
    m = ctx.rng.choice(options)
    m.on_ration_card = False
    card = ctx.doc("ration_card")
    card.fields["members"] = [
        row for row in card.fields["members"] if row["name_en"] != m.full_name.en
    ]
    card.member_ids.remove(m.id)
    return PlantedError(
        type="not_on_ration_card", member_id=m.id,
        documents=["ration_card", f"identity_card_{m.id}"],
    )


def _plant_missing_document(ctx: _Ctx) -> PlantedError | None:
    options = ctx.free_docs()
    if not options:
        return None
    d = ctx.rng.choice(options)
    ctx.docs.remove(d)
    return PlantedError(
        type="missing_document", member_id=d.member_ids[0], documents=[d.id],
        expected=d.type, note="Document intentionally not generated.",
    )


PLANTERS: dict[ErrorType, Callable[[_Ctx], PlantedError | None]] = {
    "name_mismatch": _plant_name_mismatch,
    "dob_mismatch": _plant_dob_mismatch,
    "expired": _plant_expired,
    "not_on_ration_card": _plant_not_on_ration_card,
    "missing_document": _plant_missing_document,
}


def _plant_errors(rng: random.Random, members: list[Member], docs: list[Document]) -> list[PlantedError]:
    types = rng.sample(ERROR_TYPES, rng.randint(0, 3))
    # Plant the missing document last so it never removes a document another error lives on.
    types.sort(key=lambda t: t == "missing_document")
    ctx = _Ctx(rng, members, docs)
    errors = []
    for t in types:
        err = PLANTERS[t](ctx)
        if err is None:
            continue
        errors.append(err)
        ctx.used_docs.update(err.documents)
        ctx.used_members.add(err.member_id)
    return errors


# ---------- households ----------

def build_household(seed: int, index: int) -> Household:
    """Pure function of (seed, index): no files, no rendering."""
    hh_id = f"HH{index:03d}"
    rng = random.Random(f"{seed}:{hh_id}")
    members = _build_members(rng)
    docs = _build_documents(rng, members)
    errors = _plant_errors(rng, members, docs)
    return Household(
        id=hh_id, seed=seed, reference_date=REFERENCE_DATE,
        members=members, documents=docs, planted_errors=errors,
    )


def _photo_seed(seed: int, hh_id: str, doc_id: str) -> int:
    return int(hashlib.sha256(f"{seed}:{hh_id}:{doc_id}".encode()).hexdigest()[:16], 16)


def write_household(hh: Household, out_dir: Path, renderer: "Renderer") -> None:  # noqa: F821
    import numpy as np

    from synthetic.photo import photo_like

    hh_dir = out_dir / hh.id
    if hh_dir.exists():
        if any(hh_dir.iterdir()) and not (hh_dir / "ground_truth.json").exists():
            raise RuntimeError(f"Refusing to overwrite {hh_dir}: not a generated household")
        shutil.rmtree(hh_dir)
    hh_dir.mkdir(parents=True)

    for doc in hh.documents:
        png = renderer.render(doc.type, doc.fields)
        (hh_dir / f"{doc.id}.png").write_bytes(png)
        photo, params = photo_like(png, np.random.default_rng(_photo_seed(hh.seed, hh.id, doc.id)))
        (hh_dir / f"{doc.id}_photo.jpg").write_bytes(photo)
        doc.files = {"clean": f"{doc.id}.png", "photo": f"{doc.id}_photo.jpg"}
        doc.photo = params

    (hh_dir / "ground_truth.json").write_text(hh.model_dump_json(indent=2), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate synthetic SPECIMEN households")
    parser.add_argument("--n", type=int, default=10)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--out", type=Path, default=OUT_DIR)
    args = parser.parse_args()

    from synthetic.render import Renderer

    households = [build_household(args.seed, i) for i in range(1, args.n + 1)]
    with Renderer() as renderer:
        for hh in households:
            write_household(hh, args.out, renderer)
            errors = ", ".join(e.type for e in hh.planted_errors) or "none"
            print(f"{hh.id}: {len(hh.members)} members, {len(hh.documents)} documents, errors: {errors}")


if __name__ == "__main__":
    main()
