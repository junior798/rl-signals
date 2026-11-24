from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import yaml

from rl_signals.common import norm_name, norm_province
from rl_signals.score import score_companies
from rl_signals.sources import canadabuys, grants, jobbank, lmia, seao

CFG = yaml.safe_load((Path(__file__).parent.parent / "config.yaml").read_text(encoding="utf-8"))
EXCL = CFG["exclude_name_patterns"]
TODAY = date.today()
RECENT = (TODAY - timedelta(days=10)).isoformat()
OLD = (TODAY - timedelta(days=400)).isoformat()
SINCE = TODAY - timedelta(days=180)


def test_names_and_provinces():
    assert norm_name("Déneigement Lavallée Inc.") == norm_name("DENEIGEMENT LAVALLEE LTEE")
    assert norm_province("Québec") == "QC"
    assert norm_province("Ontario") == "ON"
    assert norm_province("British Columbia") == "BC"


def test_seao_keeps_snow_contract_and_drops_it_and_city():
    pkg = {"releases": [
        {"ocid": "a", "tender": {"title": "Déneigement des rues secteur 4", "items": []},
         "buyer": {"name": "Ville de Laval"},
         "parties": [{"id": "s1", "name": "Excavation Gauthier Inc.", "roles": ["supplier"],
                      "address": {"locality": "Laval", "region": "Québec"}}],
         "awards": [{"id": "1", "date": RECENT, "value": {"amount": 450000}, "suppliers": [{"id": "s1", "name": "Excavation Gauthier Inc."}]}]},
        {"ocid": "b", "tender": {"title": "Licences logicielles", "items": [{"classification": {"id": "43231500"}}]},
         "awards": [{"id": "2", "date": RECENT, "value": {"amount": 900000}, "suppliers": [{"id": "x", "name": "Logiciels ABC"}]}]},
        {"ocid": "c", "tender": {"title": "Pavage rue Principale"},
         "awards": [{"id": "3", "date": RECENT, "value": {"amount": 200000}, "suppliers": [{"id": "y", "name": "Ville de Gatineau"}]}]},
    ]}
    out = seao.parse_package(pkg, CFG["seao"], EXCL, SINCE)
    assert [s["company"] for s in out] == ["Excavation Gauthier Inc."]
    assert out[0]["province"] == "QC" and out[0]["points"] == 30 and out[0]["city"] == "Laval"


def test_canadabuys_filters_value_and_topic():
    df = pd.DataFrame({
        "title-titre-eng": ["Snow removal services", "Software licences", "Road repair"],
        "supplierLegalName-nomLegalFournisseur-eng": ["Nordic Hauling Ltd", "Big Software Corp", "Tiny Paving"],
        "contractAwardDate-dateAttributionContrat": [RECENT, RECENT, RECENT],
        "totalContractValue-valeurTotaleContrat": ["250000", "800000", "40000"],
        "unspsc": ["*76111500", "*43231500", "*72141100"],
        "supplierProvince-provinceFournisseur-eng": ["Ontario", "Ontario", "Quebec"],
    })
    out = canadabuys.parse_frame(df, CFG["canadabuys"], EXCL, SINCE)
    assert [s["company"] for s in out] == ["Nordic Hauling Ltd"]
    assert out[0]["province"] == "ON"


def test_grants_program_points_and_for_profit_only():
    df = pd.DataFrame({
        "recipient_type": ["F", "S", "F", "F"],
        "recipient_legal_name": ["9123-4567 Québec inc.", "Université Laval", "Old Co", "Acme Fab Ltd"],
        "recipient_operating_name": ["Usinage Précis", "", "", ""],
        "recipient_province": ["QC", "QC", "ON", "ON"],
        "recipient_city": ["Lévis", "Québec", "Toronto", "Hamilton"],
        "prog_name_en": ["Regional Economic Growth through Innovation", "IRAP", "CanExport SMEs", "Industrial Research Assistance Program"],
        "owner_org_title": ["CED", "NRC", "TCS", "NRC"],
        "agreement_value": [500000, 300000, 50000, 120000],
        "agreement_start_date": [RECENT, RECENT, OLD, RECENT],
        "ref_number": ["r1", "r2", "r3", "r4"],
    })
    out = grants.parse_frame(df, CFG["grants"], EXCL, SINCE)
    assert {s["company"]: s["points"] for s in out} == {"Usinage Précis": 30, "Acme Fab Ltd": 15}


def test_lmia_header_detection_and_noc_filter(tmp_path):
    raw = pd.DataFrame([
        ["Employers who were issued a positive LMIA", None, None, None, None],
        ["Province/Territory", "Program Stream", "Employer", "Address", "Occupation"],
        ["Quebec", "High-wage", "Soudure Pro Inc.", "Drummondville, QC J2C 1A1", "72106-Welders and related machine operators"],
        ["Ontario", "Low-wage", "Happy Restaurant", "Toronto, ON M5V 1A1", "65201-Food counter attendants"],
    ])
    path = tmp_path / "lmia.xlsx"
    raw.to_excel(path, header=False, index=False)
    df = lmia._load(path)
    out = lmia.parse_frame(df, CFG["lmia"], EXCL, TODAY)
    assert [(s["company"], s["province"], s["city"]) for s in out] == [("Soudure Pro Inc.", "QC", "Drummondville")]


def test_jobbank_needs_three_posts():
    df = pd.DataFrame({
        "Employer Name": ["Fab Co"] * 3 + ["One Post Inc"],
        "NOC21 Code": ["72106", "72106", "73400", "72106"],
        "Province/Territory": ["Ontario"] * 4,
        "City": ["Hamilton"] * 4,
        "Job Title": ["Welder", "Welder", "Excavator operator", "Welder"],
    })
    out = jobbank.parse_frame(df, CFG["jobbank"], EXCL, TODAY)
    assert [(s["company"], s["amount"]) for s in out] == [("Fab Co", 3)]


def test_jobbank_without_employer_column_returns_nothing():
    df = pd.DataFrame({"NOC21 Code": ["72106"], "City": ["Hamilton"]})
    assert jobbank.parse_frame(df, CFG["jobbank"], EXCL, TODAY) == []


def test_scoring_stacks_sources_and_province():
    base = dict(company_key="acme fab|ON", company="Acme Fab Ltd", city="Hamilton", province="ON", url="")
    sigs = [
        dict(base, signal_id="1", source="grants", signal_type="grant", date=RECENT, amount=1, points=30, detail="g"),
        dict(base, signal_id="2", source="lmia", signal_type="lmia_hiring", date=RECENT, amount=1, points=20, detail="l"),
        dict(base, signal_id="3", source="grants", signal_type="grant", date=RECENT, amount=1, points=15, detail="g2"),
        dict(base, signal_id="4", company_key="old|QC", company="Old", province="QC", source="seao",
             signal_type="contract_award", date=OLD, amount=1, points=30, detail="x"),
    ]
    rows = score_companies(sigs, CFG)
    assert len(rows) == 1  # the 400-day-old signal expired
    r = rows[0]
    assert r["score"] == 30 + 20 + 20 + 10 and r["tier"] == "hot" and r["sources"] == "grants, lmia"


def test_situations_and_first_lines():
    from rl_signals.situations import describe
    snow = dict(signal_type="contract_award", points=30, amount=4005090,
                detail="Quebec public contract: Déneigement et entretien hivernal ($4,005,090) for Ville de Québec.")
    hire = dict(signal_type="lmia_hiring", points=20, amount=3,
                detail="Approved to hire foreign workers: 72410-Automotive service technicians, truck and bus mechanics (3 positions)")
    one = describe([snow], {"seao"})
    assert one["situation"] == "1 Snow contract"
    assert one["first_line"] == "Saw you picked up snow removal work with the City of Québec this season."
    assert one["likely_need"] == "$250K-$750K"
    two = describe([snow, hire], {"seao", "lmia"})
    assert two["situation"] == "9 Two or more lists" and "Loaders" in two["likely_equipment"]
    h = describe([hire], {"lmia"})
    assert h["first_line"] == "Saw you got approval to bring on more automotive service technicians."
