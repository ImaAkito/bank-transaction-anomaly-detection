import pandas as pd
import pytest

from app.domain.preprocessing import normalize
from app.config import DEFAULT_CURRENCY_RATES
from app.ml.ibm_loader import load_ibm, mcc_to_category

HEADER = "User,Card,Year,Month,Day,Time,Amount,Use Chip,Merchant Name,Merchant City,Merchant State,Zip,MCC,Errors?,Is Fraud?"
ROWS = [
    "0,0,2015,1,2,06:21,$134.09,Swipe Transaction,3527213246127876953,La Verne,CA,91750,5300,,No",
    "0,0,2015,1,3,23:05,$-50.00,Swipe Transaction,3527213246127876953,La Verne,CA,91750,5300,,No",
    "0,1,2015,1,4,12:00,$1,200.50,Online Transaction,-727612092139916043,ONLINE,,,5311,,Yes",
    "1,0,2009,5,6,08:30,$10.00,Chip Transaction,111,Miami,FL,33101,5411,,No",
    "1,0,2016,5,6,08:30,$10.00,Chip Transaction,111,Miami,FL,33101,5411,Bad PIN,No",
]


@pytest.fixture()
def ibm_file(tmp_path):
    path = tmp_path / "card_transaction.csv"
    path.write_text("\n".join([HEADER, *[r.replace("$1,200.50", '"$1,200.50"') for r in ROWS]]), encoding="utf-8")
    return path


def test_mapping_and_filters(ibm_file):
    df = load_ibm(ibm_file, user_fraction=1.0, from_year=2010)
    assert len(df) == 3  # возврат и строка 2009 года отброшены
    assert df.attrs["dropped_refunds"] == 1
    assert list(df["client_id"]) == ["U00000", "U00000", "U00001"]
    assert df["timestamp"].is_monotonic_increasing and str(df["timestamp"].dt.tz) == "UTC"
    assert list(df["category"]) == ["retail", "retail", "groceries"]
    assert list(df["channel"]) == ["card_swipe", "online", "card_chip"]
    fraud = df[df["is_anomaly"]].iloc[0]
    assert fraud["amount"] == 1200.5 and fraud["channel"] == "online" and fraud["anomaly_type"] == "fraud"
    assert fraud["recipient_category"] == "online"


def test_rows_pass_preprocessing(ibm_file):
    df = load_ibm(ibm_file, user_fraction=1.0, from_year=2010)
    for row in df.to_dict("records"):
        normalize({**row, "timestamp": pd.Timestamp(row["timestamp"]).to_pydatetime()}, DEFAULT_CURRENCY_RATES)


def test_user_sampling_is_deterministic_and_partial(ibm_file):
    a = load_ibm(ibm_file, user_fraction=0.5, from_year=2010, seed=1)
    b = load_ibm(ibm_file, user_fraction=0.5, from_year=2010, seed=1)
    assert a.equals(b)


def test_missing_columns_error(tmp_path):
    path = tmp_path / "bad.csv"
    path.write_text("a,b\n1,2\n")
    with pytest.raises(ValueError, match="нет колонок"):
        load_ibm(path)


def test_mcc_groups():
    assert mcc_to_category(5411) == "groceries" and mcc_to_category("7995") == "gambling"
    assert mcc_to_category(6011) == "cash_withdrawal" and mcc_to_category(9999) == "mcc_9999"
    assert mcc_to_category("abc") == "mcc_unknown"
