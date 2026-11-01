import pandas as pd
from src.merge import norm_id, norm_phone, norm_email, standardize, assign_ids, golden_records, score
from src.generate_data import generate


def test_normalizers():
    assert norm_id("NT0123456") == "0123456"
    assert norm_id("123456") == "0123456"      # leading zero restored
    assert norm_id("") == ""
    assert norm_phone("(214) 555-0199") == norm_phone("214.555.0199") == "2145550199"
    assert norm_email("  JDoe@Example.EDU ") == "jdoe@example.edu"
    assert norm_email("not an email") == ""


def tiny():
    reg = pd.DataFrame({"Student ID": ["1234567"], "First Name": ["James"], "Last Name": ["Garcia"],
                        "Email": ["jgarcia@x.edu"], "Major": ["Biology"], "Expected Grad": ["2027"]})
    adv = pd.DataFrame({"ID #": ["", ""], "Name": ["GARCIA, James  ", "Garcia, James"],
                        "E-mail": ["jgarcia@x.edu", "other@x.edu"], "Phone": ["214-555-0100", "972-555-0111"],
                        "Advisor": ["Kaur", "Kaur"]})
    ea = pd.DataFrame({"STUDENT_NUM": [""], "FIRST": ["Jim"], "LAST": ["GARCIA"], "EMAIL_ADDR": [""],
                       "PHONE": ["(214) 555-0100"], "ALERT_REASON": ["Missed classes"]})
    return reg, adv, ea


def test_same_name_different_person_is_not_merged():
    m, _ = assign_ids(standardize(*tiny()))
    keys = m.set_index(["source", "row"]).match_key
    assert keys[("advising", 0)] == "1234567"        # matched by email
    assert keys[("advising", 1)] != "1234567"        # same name, different email: a different James
    assert keys[("early_alert", 0)] == "1234567"     # nickname "Jim" + same phone


def test_golden_record_prefers_registrar():
    m, _ = assign_ids(standardize(*tiny()))
    g = golden_records(m).set_index("student_id")
    assert g.loc["1234567", "major"] == "Biology"
    assert g.loc["1234567", "phone"] == "2145550100"
    assert g.loc["1234567", "source_rows"] == 3


def test_full_merge_scores_well():
    g = generate(seed=5)
    as_text = lambda d: d.astype(str).replace("nan", "")
    m, _ = assign_ids(standardize(as_text(g["registrar"]), as_text(g["advising"]), as_text(g["early_alert"])))
    q = score(m, g["truth"])
    assert q["pair_precision"] >= 0.999
    assert q["pair_recall"] >= 0.99
