"""Repeatable Olist CSV loader with typed conversion and explicit orphan quarantine."""
import csv
import json
import os
from collections import Counter
from decimal import Decimal, InvalidOperation
from datetime import datetime, timezone
import hashlib
from pathlib import Path

import pandas as pd
from sqlalchemy import MetaData, Table, create_engine, text

from .exceptions import ConfigError

FILES = {
    "customers": "olist_customers_dataset.csv",
    "sellers": "olist_sellers_dataset.csv",
    "products": "olist_products_dataset.csv",
    "category_translation": "product_category_name_translation.csv",
    "orders": "olist_orders_dataset.csv",
    "order_items": "olist_order_items_dataset.csv",
    "payments": "olist_order_payments_dataset.csv",
    "reviews": "olist_order_reviews_dataset.csv",
    "geolocation": "olist_geolocation_dataset.csv",
}
TIMESTAMPS = {
    "orders": {"order_purchase_timestamp":"purchase_at", "order_approved_at":"approved_at",
        "order_delivered_carrier_date":"carrier_at", "order_delivered_customer_date":"delivered_at",
        "order_estimated_delivery_date":"estimated_delivery_at"},
    "order_items": {"shipping_limit_date":"shipping_limit_at"},
    "reviews": {"review_creation_date":"created_at", "review_answer_timestamp":"answered_at"},
}
RENAME = {
    "customers": {"customer_zip_code_prefix":"zip_prefix", "customer_city":"city", "customer_state":"state"},
    "sellers": {"seller_zip_code_prefix":"zip_prefix", "seller_city":"city", "seller_state":"state"},
    "products": {"product_name_lenght":"name_length", "product_description_lenght":"description_length",
        "product_photos_qty":"photos_qty", "product_weight_g":"weight_g", "product_length_cm":"length_cm",
        "product_height_cm":"height_cm", "product_width_cm":"width_cm"},
    "orders": {"order_status":"status"}, "order_items": {"order_item_id":"item_number"},
    "category_translation": {"product_category_name":"category_name",
        "product_category_name_english":"category_name_english"},
    "category_translation": {"product_category_name":"category_name",
        "product_category_name_english":"category_name_english"},
    "payments": {"payment_sequential":"sequence", "payment_type":"payment_type",
        "payment_installments":"installments", "payment_value":"value"},
    "reviews": {"review_comment_title":"title", "review_comment_message":"message",
        "review_score":"score"},
    "geolocation": {"geolocation_zip_code_prefix":"zip_prefix", "geolocation_lat":"lat",
        "geolocation_lng":"lon", "geolocation_city":"city", "geolocation_state":"state"},
}
RAW_NUMERIC = {
    "products":{"name_length":"product_name_lenght","description_length":"product_description_lenght",
        "photos_qty":"product_photos_qty","weight_g":"product_weight_g","length_cm":"product_length_cm",
        "height_cm":"product_height_cm","width_cm":"product_width_cm"},
    "order_items":{"item_number":"order_item_id","price":"price","freight_value":"freight_value"},
    "payments":{"sequence":"payment_sequential","installments":"payment_installments","value":"payment_value"},
    "reviews":{"score":"review_score"},"geolocation":{"lat":"geolocation_lat","lon":"geolocation_lng"}}
COLUMNS = {
    "customers": ["customer_id","customer_unique_id","zip_prefix","city","state"],
    "sellers": ["seller_id","zip_prefix","city","state"],
    "products": ["product_id","category_name","name_length","description_length","photos_qty","weight_g","length_cm","height_cm","width_cm"],
    "category_translation": ["category_name","category_name_english"],
    "orders": ["order_id","customer_id","status","purchase_at","approved_at","carrier_at","delivered_at","estimated_delivery_at"],
    "order_items": ["order_id","item_number","product_id","seller_id","shipping_limit_at","price","freight_value"],
    "payments": ["order_id","sequence","payment_type","installments","value"],
    "reviews": ["review_id","order_id","score","created_at","answered_at","title","message"],
    "geolocation": ["zip_prefix","lat","lon","city","state"],
}


def load_olist(data_dir="data/olist", url=None, quarantine_path="data/state/olist_quarantine.jsonl", chunksize=1000):
    """Validate references, then atomically replace Olist tables from the nine source CSVs."""
    url = url or os.environ.get("DATABASE_URL")
    if not url:
        raise ConfigError("Set DATABASE_URL to a PostgreSQL SQLAlchemy URL")
    root = Path(data_dir)
    absent = [name for name in FILES.values() if not (root/name).is_file()]
    if absent:
        raise ConfigError(f"Missing Olist CSV files in {root}: {', '.join(absent)}")
    rejected = []
    frames = {}
    for key, filename in FILES.items():
        frame = pd.read_csv(root/filename, dtype="string", keep_default_na=True)
        frame.insert(0, "_source_row", range(2, len(frame)+2))
        for raw_name, typed_name in TIMESTAMPS.get(key, {}).items():
            frame["_rawcheck_"+typed_name]=frame[raw_name].notna()
        for typed_name, raw_name in RAW_NUMERIC.get(key, {}).items():
            frame["_rawcheck_"+typed_name]=frame[raw_name].notna()
        frame = frame.rename(columns={**RENAME.get(key, {}), **TIMESTAMPS.get(key, {})})
        if key == "products":
            frame = frame.rename(columns={"product_category_name":"category_name"})
        for col in TIMESTAMPS.get(key, {}).values():
            # Source CSV timestamps have no offset: preserve the wall-clock value instead of inventing UTC.
            frame[col] = pd.to_datetime(frame[col], errors="coerce")
        numeric = {
            "products": ["name_length","description_length","photos_qty","weight_g","length_cm","height_cm","width_cm"],
            "order_items": ["item_number","price","freight_value"],
            "payments": ["sequence","installments","value"], "reviews": ["score"],
            "geolocation": ["lat","lon"],
        }.get(key, [])
        integer_columns={"products":{"name_length","description_length","photos_qty","weight_g","length_cm","height_cm","width_cm"},
                         "order_items":{"item_number"},"payments":{"sequence","installments"},"reviews":{"score"}}
        for col in numeric:
            if (key, col) in (("order_items", "price"), ("order_items", "freight_value"), ("payments", "value")):
                def decimal_or_null(value):
                    if pd.isna(value):
                        return None
                    try:
                        return Decimal(str(value))
                    except InvalidOperation:
                        return None
                frame[col] = frame[col].map(decimal_or_null)
            else:
                frame[col] = pd.to_numeric(frame[col], errors="coerce")
                if col in integer_columns.get(key, set()):
                    fractional=frame[col].notna() & (frame[col] % 1 != 0)
                    frame.loc[fractional,col]=pd.NA
                    frame[col]=frame[col].astype("Int64")
        frames[key] = frame

    def reject_mask(key, f):
        required = {
            "customers":["customer_id","customer_unique_id"], "sellers":["seller_id"],
            "products":["product_id"], "category_translation":["category_name","category_name_english"],
            "orders":["order_id","customer_id","status"],
            "order_items":["order_id","item_number","price","freight_value"],
            "payments":["order_id","sequence","value"], "reviews":["review_id","order_id"],
            "geolocation":["zip_prefix"],
        }[key]
        mask = f[required].isna().any(axis=1)
        reason = pd.Series("MISSING_REQUIRED", index=f.index)
        for raw_name, typed_name in TIMESTAMPS.get(key, {}).items():
            raw_present=f["_rawcheck_"+typed_name]
            bad=f[typed_name].isna() & raw_present
            mask |= bad; reason[bad]="INVALID_TIMESTAMP"
        numeric_fields={
            "products":["name_length","description_length","photos_qty","weight_g","length_cm","height_cm","width_cm"],
            "order_items":["item_number","price","freight_value"],
            "payments":["sequence","installments","value"],"reviews":["score"],
            "geolocation":["lat","lon"],
        }.get(key, [])
        for col in numeric_fields:
            raw_present=f["_rawcheck_"+col]
            bad=f[col].isna() & raw_present
            mask |= bad; reason[bad]="INVALID_NUMERIC"
        if key in ("orders","order_items","payments","reviews"):
            known_orders = set(frames["orders"]["order_id"].dropna())
            bad = f.order_id.notna() & ~f.order_id.isin(known_orders)
            mask |= bad; reason[bad] = "ORPHAN_ORDER"
        if key == "orders":
            bad = f.customer_id.notna() & ~f.customer_id.isin(set(frames["customers"].customer_id.dropna()))
            mask |= bad; reason[bad] = "ORPHAN_CUSTOMER"
        if key == "order_items":
            for col, ids, code in [("product_id",set(frames["products"].product_id.dropna()),"ORPHAN_PRODUCT"),
                                   ("seller_id",set(frames["sellers"].seller_id.dropna()),"ORPHAN_SELLER")]:
                bad=f[col].notna() & ~f[col].isin(ids); mask |= bad; reason[bad]=code
        if key == "reviews":
            bad=f.score.notna() & ~f.score.between(1,5); mask |= bad; reason[bad]="INVALID_SCORE"
        if key in ("order_items","payments"):
            amount = "price" if key == "order_items" else "value"
            bad=f[amount].notna() & (f[amount] < 0); mask |= bad; reason[bad]="NEGATIVE_AMOUNT"
        if key == "order_items":
            bad=f.item_number.notna() & (f.item_number <= 0); mask |= bad; reason[bad]="INVALID_ITEM_NUMBER"
            bad=f.freight_value.notna() & (f.freight_value < 0); mask |= bad; reason[bad]="NEGATIVE_FREIGHT"
        if key == "payments":
            bad=f.installments.notna() & (f.installments < 0); mask |= bad; reason[bad]="NEGATIVE_INSTALLMENTS"
            bad=f.sequence.notna() & (f.sequence <= 0); mask |= bad; reason[bad]="INVALID_PAYMENT_SEQUENCE"
        if key == "products":
            fields=["name_length","description_length","photos_qty","weight_g","length_cm","height_cm","width_cm"]
            bad=f[fields].lt(0).any(axis=1); mask |= bad; reason[bad]="NEGATIVE_PRODUCT_MEASURE"
        if key == "geolocation":
            bad=(f.lat.notna() & ~f.lat.between(-90,90)) | (f.lon.notna() & ~f.lon.between(-180,180))
            mask |= bad; reason[bad]="INVALID_COORDINATE"
        if key == "orders":
            invalid = f.delivered_at.notna() & f.purchase_at.notna() & (f.delivered_at < f.purchase_at)
            mask |= invalid; reason[invalid]="DELIVERY_BEFORE_PURCHASE"
        if key in ("customers", "sellers", "geolocation"):
            invalid_zip=f.zip_prefix.notna() & ~f.zip_prefix.str.fullmatch(r"\d{5}")
            mask |= invalid_zip; reason[invalid_zip]="INVALID_ZIP_PREFIX"
        if key in ("customers","sellers","products","category_translation","orders","order_items","payments","reviews"):
            pk = {"customers":["customer_id"],"sellers":["seller_id"],"products":["product_id"],
                  "category_translation":["category_name"],"orders":["order_id"],
                  "order_items":["order_id","item_number"],"payments":["order_id","sequence"],
                  "reviews":["review_id","order_id"]}[key]
            dup = f.duplicated(pk, keep="first")
            mask |= dup; reason[dup]="DUPLICATE_KEY"
        return mask, reason

    # Parent tables are validated first so orphan counts are computed from source keys.
    order = ["customers","sellers","products","category_translation","orders","order_items","payments","reviews","geolocation"]
    for key in order:
        f=frames[key]; mask, reasons=reject_mask(key,f)
        for idx in f.index[mask]:
            rejected.append({"dataset":key,"source_row":int(f.at[idx,"_source_row"]),
                             "reason":reasons.at[idx]})
        frames[key]=f.loc[~mask].copy()

    # Re-read only the source lines actually quarantined, preserving their original CSV fields.
    by_dataset={key:{row["source_row"]:row for row in rejected if row["dataset"]==key} for key in FILES}
    for key,filename in FILES.items():
        pending=by_dataset[key]
        if not pending:
            continue
        with (root/filename).open("r",encoding="utf-8-sig",newline="") as source:
            for line_number,raw in enumerate(csv.DictReader(source),start=2):
                if line_number in pending:
                    pending[line_number]["raw_record"]={k:(v if v!="" else None) for k,v in raw.items()}

    engine=create_engine(url, pool_pre_ping=True, future=True)
    try:
        with engine.begin() as conn:
            conn.execute(text("CREATE SCHEMA IF NOT EXISTS olist"))
            # Transactional truncate/reload: FK checks are retained and errors roll back all changes.
            conn.execute(text("TRUNCATE olist.order_items,olist.payments,olist.reviews,olist.orders,olist.products,olist.sellers,olist.customers,olist.category_translation,olist.geolocation"))
            counts={}
            for key in order:
                f=frames[key][COLUMNS[key]].copy()
                # Bind against the real PostgreSQL column types. pandas.to_sql infers
                # Decimal object columns as VARCHAR, which PostgreSQL may reject for
                # NUMERIC columns such as order_items.price and payments.value.
                table=Table(key,MetaData(),schema="olist",autoload_with=conn)
                for start in range(0,len(f),chunksize):
                    batch=f.iloc[start:start+chunksize]
                    records=[]
                    for record in batch.to_dict(orient="records"):
                        typed_record={}
                        for column,value in record.items():
                            if pd.isna(value):
                                value=None
                            elif isinstance(value,pd.Timestamp):
                                value=value.to_pydatetime()
                            elif hasattr(value,"item") and not isinstance(value,(str,bytes,Decimal)):
                                value=value.item()
                            typed_record[column]=value
                        records.append(typed_record)
                    if records:
                        conn.execute(table.insert(),records)
                counts[key]=len(f)
            # Snapshot is derived data. Rebuild all populated purchase months in this
            # same transaction so readers never observe a half-refreshed load.
            conn.execute(text("DELETE FROM analytics.monthly_sales_snapshot"))
            snapshot_months=conn.execute(text("""SELECT DISTINCT date_trunc('month',purchase_at)::date
                FROM olist.orders WHERE purchase_at IS NOT NULL ORDER BY 1""")).scalars().all()
            for month in snapshot_months:
                conn.execute(text("CALL analytics.refresh_monthly_sales(CAST(:month AS date))"),{"month":month})
            qpath=Path(quarantine_path); qpath.parent.mkdir(parents=True,exist_ok=True)
            # Publish quarantine only after database commit; write to a temp then replace.
        rejected_by_dataset=dict(Counter(row["dataset"] for row in rejected))
        rejected_by_reason=dict(Counter(row["reason"] for row in rejected))
        source_info={}
        for key,filename in FILES.items():
            file_path=root/filename
            digest=hashlib.sha256()
            with file_path.open("rb") as binary:
                for block in iter(lambda:binary.read(1024*1024),b""):
                    digest.update(block)
            source_info[key]={"path":str(file_path),"bytes":file_path.stat().st_size,"sha256":digest.hexdigest(),
                              "source_rows":len(frames[key])+rejected_by_dataset.get(key,0)}
        manifest={"finished_at_utc":datetime.now(timezone.utc).isoformat(),
                  "loaded_rows":counts,"rejected_rows":len(rejected),
                  "snapshot_months_refreshed":len(snapshot_months),
                  "rejected_by_dataset":rejected_by_dataset,"rejected_by_reason":rejected_by_reason,
                  "source_files":source_info,"quarantine_path":str(qpath)}
        tmp=qpath.with_suffix(qpath.suffix+".tmp")
        with tmp.open("w",encoding="utf-8") as stream:
            for row in rejected: stream.write(json.dumps(row,ensure_ascii=False)+"\n")
        tmp.replace(qpath)
        manifest_path=qpath.parent/"olist_load_manifest.json"
        manifest_tmp=manifest_path.with_suffix(".json.tmp")
        manifest_tmp.write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding="utf-8")
        manifest_tmp.replace(manifest_path)
        return {"loaded":counts,"rejected":len(rejected),
                "rejected_by_dataset":rejected_by_dataset,"rejected_by_reason":rejected_by_reason,
                "snapshot_months_refreshed":len(snapshot_months),
                "quarantine_path":str(qpath),"manifest_path":str(manifest_path)}
    finally:
        engine.dispose()
