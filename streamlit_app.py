import hashlib
import io
import re
import shutil
from pathlib import Path

import pandas as pd
import plotly.express as px
import streamlit as st

st.set_page_config(page_title="BuckeyeCardCo PSA Workspace Tracker", page_icon="🅾️", layout="wide")

BASE_DIR = Path(__file__).parent
DATA_DIR = BASE_DIR / "data"
WORKSPACES_DIR = DATA_DIR / "workspaces"

GRADE_MAP = {
    "GEM MINT 10": 10,
    "MINT 9": 9,
    "NEAR MINT-MINT 8": 8,
    "NM-MT 8": 8,
    "NEAR MINT 7": 7,
    "EXCELLENT-MINT 6": 6,
    "EX-MT 6": 6,
    "EXCELLENT 5": 5,
    "VERY GOOD-EXCELLENT 4": 4,
    "VERY GOOD 3": 3,
    "GOOD 2": 2,
    "POOR 1": 1,
}

st.markdown("""
<style>
.block-container {padding-top: 1.2rem; padding-bottom: 1.2rem;}
.brand-wrap {
    background: linear-gradient(135deg, #bb0000 0%, #880000 100%);
    border-radius: 18px;
    padding: 20px 24px;
    margin-bottom: 18px;
    color: white;
    box-shadow: 0 10px 28px rgba(0,0,0,0.15);
}
.brand-title {
    font-size: 2rem;
    font-weight: 800;
    margin: 0;
    letter-spacing: 0.3px;
}
.brand-sub {
    font-size: 1rem;
    opacity: 0.95;
    margin-top: 6px;
}
.small-muted {
    color: #666;
    font-size: 0.92rem;
}
div[data-testid="stMetric"] {
    background: #fafafa;
    border: 1px solid #ececec;
    padding: 8px 12px;
    border-radius: 14px;
}
</style>
""", unsafe_allow_html=True)

def slugify(name: str) -> str:
    name = str(name).strip().lower()
    name = re.sub(r"[^a-z0-9]+", "_", name)
    return name.strip("_") or "workspace"

def ensure_base():
    WORKSPACES_DIR.mkdir(parents=True, exist_ok=True)

def workspace_paths(workspace_slug: str):
    ws = WORKSPACES_DIR / workspace_slug
    return {
        "root": ws,
        "raw": ws / "raw",
        "orders": ws / "order_metadata.csv",
        "cards": ws / "card_metadata.csv",
    }

def ensure_workspace(workspace_slug: str):
    paths = workspace_paths(workspace_slug)
    paths["raw"].mkdir(parents=True, exist_ok=True)
    if not paths["orders"].exists():
        pd.DataFrame(columns=[
            "order_id","customer","submission_date","return_date","psa_fees",
            "shipping_out","shipping_back","other_costs","revenue_collected","notes"
        ]).to_csv(paths["orders"], index=False)
    if not paths["cards"].exists():
        pd.DataFrame(columns=[
            "order_id","cert_no","cleaned_by_you","owner","card_cost_basis",
            "psa_fee_alloc","shipping_alloc","sold_price","notes"
        ]).to_csv(paths["cards"], index=False)

def list_workspaces():
    ensure_base()
    items = []
    for p in sorted(WORKSPACES_DIR.iterdir()):
        if p.is_dir():
            display = p.name.replace("_", " ").title()
            items.append((display, p.name))
    return items

def parse_order_id(file_name: str) -> str:
    match = re.search(r"(\d+)", str(file_name))
    return match.group(1) if match else "unknown"

def read_psa_csv(file_like, source_name: str) -> pd.DataFrame:
    df = pd.read_csv(file_like)
    df["source_file"] = source_name
    df["order_id"] = parse_order_id(source_name)
    if "Grade" in df.columns:
        df["Grade #"] = df["Grade"].astype(str).str.strip().str.upper().map(GRADE_MAP)
    else:
        df["Grade #"] = pd.NA
    if "Cert #" in df.columns:
        df["cert_no"] = df["Cert #"].astype(str)
    else:
        df["cert_no"] = ""
    return df

def file_md5_from_bytes(content: bytes) -> str:
    return hashlib.md5(content).hexdigest()

def file_md5_from_path(path: Path) -> str:
    h = hashlib.md5()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()

@st.cache_data(show_spinner=False)
def load_raw_data_from_disk(workspace_slug: str):
    paths = workspace_paths(workspace_slug)
    ensure_workspace(workspace_slug)
    files = sorted(paths["raw"].glob("*.csv"))
    frames = []
    for file in files:
        try:
            frames.append(read_psa_csv(file, file.name))
        except Exception as e:
            st.warning(f"Could not read {file.name}: {e}")
    if not frames:
        return pd.DataFrame(columns=["Cert #","Type","Description","Grade","After Service","Images","source_file","order_id","Grade #","cert_no"])
    return pd.concat(frames, ignore_index=True)

def load_order_meta(workspace_slug: str):
    paths = workspace_paths(workspace_slug)
    ensure_workspace(workspace_slug)
    return pd.read_csv(paths["orders"], dtype={"order_id": str})

def load_card_meta(workspace_slug: str):
    paths = workspace_paths(workspace_slug)
    ensure_workspace(workspace_slug)
    return pd.read_csv(paths["cards"], dtype={"order_id": str, "cert_no": str})

def save_order_meta(workspace_slug: str, df: pd.DataFrame):
    paths = workspace_paths(workspace_slug)
    out = df.copy()
    for col in ["psa_fees","shipping_out","shipping_back","other_costs","revenue_collected"]:
        out[col] = pd.to_numeric(out[col], errors="coerce")
    out.to_csv(paths["orders"], index=False)

def save_card_meta(workspace_slug: str, df: pd.DataFrame):
    paths = workspace_paths(workspace_slug)
    out = df.copy()
    for col in ["card_cost_basis","psa_fee_alloc","shipping_alloc","sold_price"]:
        out[col] = pd.to_numeric(out[col], errors="coerce")
    out.to_csv(paths["cards"], index=False)

def create_workspace(display_name: str):
    slug = slugify(display_name)
    ensure_workspace(slug)
    return slug

def rename_workspace(old_slug: str, new_display_name: str):
    new_slug = slugify(new_display_name)
    old_root = workspace_paths(old_slug)["root"]
    new_root = workspace_paths(new_slug)["root"]
    if new_root.exists():
        raise ValueError("A workspace with that name already exists.")
    old_root.rename(new_root)
    return new_slug

def delete_workspace(workspace_slug: str):
    root = workspace_paths(workspace_slug)["root"]
    if root.exists():
        shutil.rmtree(root)

def save_uploaded_files_permanently(workspace_slug: str, uploaded_files):
    paths = workspace_paths(workspace_slug)
    ensure_workspace(workspace_slug)
    if not uploaded_files:
        return {"saved": [], "skipped": []}
    existing_hashes = {}
    for existing in paths["raw"].glob("*.csv"):
        try:
            existing_hashes[file_md5_from_path(existing)] = existing.name
        except Exception:
            pass

    saved, skipped = [], []
    for file in uploaded_files:
        content = file.getvalue()
        md5 = file_md5_from_bytes(content)
        target = paths["raw"] / file.name

        if md5 in existing_hashes:
            skipped.append(f"{file.name} (same as {existing_hashes[md5]})")
            continue

        final_target = target
        if final_target.exists():
            stem = final_target.stem
            suffix = final_target.suffix
            counter = 2
            while final_target.exists():
                final_target = paths["raw"] / f"{stem}_{counter}{suffix}"
                counter += 1

        with open(final_target, "wb") as f:
            f.write(content)
        saved.append(final_target.name)
    return {"saved": saved, "skipped": skipped}

def reset_workspace_data(workspace_slug: str):
    paths = workspace_paths(workspace_slug)
    ensure_workspace(workspace_slug)
    for file in paths["raw"].glob("*.csv"):
        file.unlink()
    pd.DataFrame(columns=[
        "order_id","customer","submission_date","return_date","psa_fees",
        "shipping_out","shipping_back","other_costs","revenue_collected","notes"
    ]).to_csv(paths["orders"], index=False)
    pd.DataFrame(columns=[
        "order_id","cert_no","cleaned_by_you","owner","card_cost_basis",
        "psa_fee_alloc","shipping_alloc","sold_price","notes"
    ]).to_csv(paths["cards"], index=False)

def build_orders(raw_df: pd.DataFrame, order_meta: pd.DataFrame) -> pd.DataFrame:
    if raw_df.empty:
        return pd.DataFrame(columns=["order_id","cards_submitted","psa_10_count","avg_grade","gem_rate"])
    cert_col = "Cert #" if "Cert #" in raw_df.columns else "cert_no"
    summary = (
        raw_df.groupby("order_id", as_index=False)
        .agg(
            cards_submitted=(cert_col, "count"),
            psa_10_count=("Grade #", lambda s: int((s == 10).sum())),
            avg_grade=("Grade #", "mean"),
        )
    )
    summary["gem_rate"] = summary["psa_10_count"] / summary["cards_submitted"]
    orders = summary.merge(order_meta, how="left", on="order_id")
    for col in ["psa_fees","shipping_out","shipping_back","other_costs","revenue_collected"]:
        if col not in orders.columns:
            orders[col] = 0
        orders[col] = pd.to_numeric(orders[col], errors="coerce").fillna(0)
    orders["total_cost"] = orders["psa_fees"] + orders["shipping_out"] + orders["shipping_back"] + orders["other_costs"]
    orders["net_profit"] = orders["revenue_collected"] - orders["total_cost"]
    orders["submission_date"] = pd.to_datetime(orders.get("submission_date"), errors="coerce")
    orders["return_date"] = pd.to_datetime(orders.get("return_date"), errors="coerce")
    orders["turnaround_days"] = (orders["return_date"] - orders["submission_date"]).dt.days
    return orders.sort_values("order_id").reset_index(drop=True)

def build_cards(raw_df: pd.DataFrame, order_meta: pd.DataFrame, card_meta: pd.DataFrame) -> pd.DataFrame:
    if raw_df.empty:
        return pd.DataFrame()
    join_order_cols = [c for c in ["order_id","customer","submission_date","return_date"] if c in order_meta.columns]
    cards = raw_df.merge(order_meta[join_order_cols], how="left", on="order_id")
    cards = cards.merge(card_meta, how="left", on=["order_id","cert_no"])
    for col in ["card_cost_basis","psa_fee_alloc","shipping_alloc","sold_price"]:
        if col not in cards.columns:
            cards[col] = pd.NA
        cards[col] = pd.to_numeric(cards[col], errors="coerce")
    cards["total_cost"] = cards[["card_cost_basis","psa_fee_alloc","shipping_alloc"]].fillna(0).sum(axis=1)
    cards["margin"] = cards["sold_price"].fillna(0) - cards["total_cost"]
    cards["turnaround_days"] = (
        pd.to_datetime(cards.get("return_date"), errors="coerce") - pd.to_datetime(cards.get("submission_date"), errors="coerce")
    ).dt.days
    cards["gem_flag"] = cards["Grade #"].eq(10)
    return cards

# Session state
ensure_base()
workspace_items = list_workspaces()
if not workspace_items:
    create_workspace("BuckeyeCardCo")
    workspace_items = list_workspaces()

if "selected_workspace" not in st.session_state:
    st.session_state["selected_workspace"] = workspace_items[0][1]

# Branding header
st.markdown("""
<div class="brand-wrap">
  <div class="brand-title">BuckeyeCardCo PSA Workspace Tracker</div>
  <div class="brand-sub">Multi-customer grading dashboards, costs, gem rates, and profit tracking in one place.</div>
</div>
""", unsafe_allow_html=True)

with st.sidebar:
    st.header("Workspace Manager")
    workspace_items = list_workspaces()
    display_to_slug = {display: slug for display, slug in workspace_items}
    slug_to_display = {slug: display for display, slug in workspace_items}
    selected_display = st.selectbox(
        "Choose workspace",
        options=list(display_to_slug.keys()),
        index=max(0, list(display_to_slug.values()).index(st.session_state["selected_workspace"])) if st.session_state["selected_workspace"] in display_to_slug.values() else 0
    )
    st.session_state["selected_workspace"] = display_to_slug[selected_display]
    active_workspace = st.session_state["selected_workspace"]
    st.caption(f"Active workspace: {slug_to_display.get(active_workspace, active_workspace)}")

    with st.expander("Create new workspace"):
        new_ws_name = st.text_input("New workspace name", key="new_workspace_name")
        if st.button("Create workspace"):
            if new_ws_name.strip():
                new_slug = create_workspace(new_ws_name)
                st.session_state["selected_workspace"] = new_slug
                st.cache_data.clear()
                st.rerun()

    with st.expander("Rename current workspace"):
        rename_name = st.text_input("Rename to", value=slug_to_display.get(active_workspace, active_workspace), key="rename_workspace_name")
        if st.button("Rename workspace"):
            try:
                new_slug = rename_workspace(active_workspace, rename_name)
                st.session_state["selected_workspace"] = new_slug
                st.cache_data.clear()
                st.rerun()
            except Exception as e:
                st.error(str(e))

    with st.expander("Danger zone"):
        reset_confirm = st.checkbox("I understand this clears the current workspace data only")
        if st.button("Reset current workspace", type="secondary", disabled=not reset_confirm):
            reset_workspace_data(active_workspace)
            st.cache_data.clear()
            st.rerun()

        delete_confirm = st.checkbox("I understand this deletes the entire current workspace")
        if st.button("Delete current workspace", type="secondary", disabled=not delete_confirm or len(workspace_items) <= 1):
            delete_workspace(active_workspace)
            remaining = list_workspaces()
            st.session_state["selected_workspace"] = remaining[0][1]
            st.cache_data.clear()
            st.rerun()
        if len(workspace_items) <= 1:
            st.caption("At least one workspace must remain.")

    st.divider()
    st.header("Upload & Filters")
    uploaded = st.file_uploader(
        "Upload PSA order CSVs",
        type=["csv"],
        accept_multiple_files=True,
        help="Upload one or more PSA CSVs, then save them permanently into the active workspace."
    )
    if uploaded:
        if st.button("Save uploaded files to this workspace"):
            results = save_uploaded_files_permanently(active_workspace, uploaded)
            st.cache_data.clear()
            if results["saved"]:
                st.success("Saved: " + ", ".join(results["saved"]))
            if results["skipped"]:
                st.warning("Skipped duplicates: " + ", ".join(results["skipped"]))
            st.rerun()

raw_df = load_raw_data_from_disk(st.session_state["selected_workspace"])
order_meta = load_order_meta(st.session_state["selected_workspace"])
card_meta = load_card_meta(st.session_state["selected_workspace"])
orders = build_orders(raw_df, order_meta)
cards = build_cards(raw_df, order_meta, card_meta)

with st.sidebar:
    order_options = sorted(cards["order_id"].dropna().astype(str).unique().tolist()) if not cards.empty else []
    selected_orders = st.multiselect("Order ID", order_options)
    grade_options = sorted(cards["Grade"].dropna().astype(str).unique().tolist()) if not cards.empty and "Grade" in cards.columns else []
    selected_grades = st.multiselect("Grade", grade_options)
    service_options = sorted(cards["After Service"].dropna().astype(str).unique().tolist()) if not cards.empty and "After Service" in cards.columns else []
    selected_service = st.multiselect("After Service", service_options)
    selected_cleaned = st.multiselect("Cleaned By You?", ["Yes", "No"])
    if st.button("Clear Streamlit cache"):
        st.cache_data.clear()
        st.rerun()

filtered_cards = cards.copy()
if not filtered_cards.empty:
    if selected_orders:
        filtered_cards = filtered_cards[filtered_cards["order_id"].astype(str).isin(selected_orders)]
    if selected_grades and "Grade" in filtered_cards.columns:
        filtered_cards = filtered_cards[filtered_cards["Grade"].isin(selected_grades)]
    if selected_service and "After Service" in filtered_cards.columns:
        filtered_cards = filtered_cards[filtered_cards["After Service"].astype(str).isin(selected_service)]
    if selected_cleaned:
        filtered_cards = filtered_cards[filtered_cards["cleaned_by_you"].fillna("").isin(selected_cleaned)]

filtered_orders = orders.copy()
if selected_orders and not filtered_orders.empty:
    filtered_orders = filtered_orders[filtered_orders["order_id"].astype(str).isin(selected_orders)]

st.markdown(f"### Workspace: {st.session_state['selected_workspace'].replace('_', ' ').title()}")
st.markdown('<div class="small-muted">Each workspace keeps its own PSA CSVs, metadata, costs, sold prices, and exports.</div>', unsafe_allow_html=True)

tab1, tab2, tab3, tab4 = st.tabs(["Dashboard", "Card Tracker", "Order Tracker", "Uploads / Export"])

with tab1:
    if filtered_cards.empty:
        st.info("This workspace is blank. Upload PSA CSV files in the sidebar and save them to start tracking.")
    else:
        total_orders = filtered_cards["order_id"].nunique()
        total_cards = len(filtered_cards)
        gem_rate = filtered_cards["gem_flag"].mean()
        avg_grade = filtered_cards["Grade #"].mean()
        psa10 = int(filtered_cards["gem_flag"].sum())
        psa9 = int(filtered_cards["Grade #"].eq(9).sum())

        c1, c2, c3, c4, c5 = st.columns(5)
        c1.metric("Orders", f"{total_orders}")
        c2.metric("Cards", f"{total_cards}")
        c3.metric("Gem Rate", f"{gem_rate:.1%}")
        c4.metric("Avg Grade", f"{avg_grade:.2f}" if pd.notna(avg_grade) else "—")
        c5.metric("PSA 10s", f"{psa10}")

        c6, c7, c8 = st.columns(3)
        total_cost = filtered_orders["total_cost"].sum() if "total_cost" in filtered_orders.columns else 0
        net_profit = filtered_orders["net_profit"].sum() if "net_profit" in filtered_orders.columns else 0
        c6.metric("PSA 9s", f"{psa9}")
        c7.metric("Total Cost", f"${total_cost:,.2f}")
        c8.metric("Net Profit", f"${net_profit:,.2f}")

        colA, colB = st.columns(2)
        with colA:
            grade_dist = (
                filtered_cards.groupby(["Grade","Grade #"], dropna=False)
                .size()
                .reset_index(name="count")
                .sort_values("Grade #", ascending=False, na_position="last")
            )
            fig = px.bar(grade_dist, x="Grade", y="count", title="Grade Distribution", text_auto=True)
            st.plotly_chart(fig, use_container_width=True)
        with colB:
            order_perf = (
                filtered_cards.groupby("order_id")
                .agg(cards=("cert_no","count"), psa_10s=("gem_flag","sum"))
                .reset_index()
            )
            order_perf["gem_rate"] = order_perf["psa_10s"] / order_perf["cards"]
            fig2 = px.line(order_perf.sort_values("order_id"), x="order_id", y="gem_rate", markers=True,
                           title="Gem Rate by Order")
            fig2.update_yaxes(tickformat=".0%")
            st.plotly_chart(fig2, use_container_width=True)

        colC, colD = st.columns(2)
        with colC:
            top_desc = (
                filtered_cards.groupby("Description", dropna=False)
                .agg(cards=("cert_no","count"), avg_grade=("Grade #","mean"))
                .reset_index()
                .sort_values(["cards","avg_grade"], ascending=[False, False])
                .head(15)
            )
            st.subheader("Most Submitted Cards")
            st.dataframe(top_desc, use_container_width=True, hide_index=True)
        with colD:
            st.subheader("Order Performance")
            if not filtered_orders.empty:
                show_orders = filtered_orders[["order_id","cards_submitted","psa_10_count","gem_rate","avg_grade","customer","turnaround_days","total_cost","net_profit"]].copy()
                show_orders["gem_rate"] = show_orders["gem_rate"].map(lambda x: f"{x:.1%}" if pd.notna(x) else "")
                show_orders["avg_grade"] = show_orders["avg_grade"].map(lambda x: f"{x:.2f}" if pd.notna(x) else "")
                st.dataframe(show_orders, use_container_width=True, hide_index=True)

with tab2:
    st.subheader("Card Tracker")
    st.caption("Edit card-level notes, costs, sold price, and cleaning status. Save changes to the active workspace.")
    if cards.empty:
        st.info("No card data loaded for this workspace.")
    else:
        edit_cols = [
            "order_id","cert_no","Description","Grade","Grade #","After Service","customer",
            "submission_date","return_date","turnaround_days","cleaned_by_you","owner",
            "card_cost_basis","psa_fee_alloc","shipping_alloc","total_cost","sold_price","margin","notes"
        ]
        existing_edit_cols = [c for c in edit_cols if c in filtered_cards.columns]
        editable = filtered_cards[existing_edit_cols].copy()
        if "submission_date" in editable.columns:
            editable["submission_date"] = pd.to_datetime(editable["submission_date"], errors="coerce").dt.date
        if "return_date" in editable.columns:
            editable["return_date"] = pd.to_datetime(editable["return_date"], errors="coerce").dt.date

        edited = st.data_editor(
            editable,
            use_container_width=True,
            hide_index=True,
            num_rows="fixed",
            disabled=[
                c for c in [
                    "order_id","cert_no","Description","Grade","Grade #","After Service",
                    "customer","submission_date","return_date","turnaround_days","total_cost","margin"
                ] if c in editable.columns
            ],
            column_config={
                "cleaned_by_you": st.column_config.SelectboxColumn(options=["", "Yes", "No"]),
                "owner": st.column_config.SelectboxColumn(options=["", "You", "Customer", "Consignment"]),
                "card_cost_basis": st.column_config.NumberColumn(format="$%.2f"),
                "psa_fee_alloc": st.column_config.NumberColumn(format="$%.2f"),
                "shipping_alloc": st.column_config.NumberColumn(format="$%.2f"),
                "sold_price": st.column_config.NumberColumn(format="$%.2f"),
                "total_cost": st.column_config.NumberColumn(format="$%.2f", disabled=True),
                "margin": st.column_config.NumberColumn(format="$%.2f", disabled=True),
            },
            key="cards_editor"
        )

        if st.button("Save card changes"):
            save_cols = [c for c in ["order_id","cert_no","cleaned_by_you","owner","card_cost_basis","psa_fee_alloc","shipping_alloc","sold_price","notes"] if c in edited.columns]
            save_df = edited[save_cols].copy()
            save_card_meta(st.session_state["selected_workspace"], save_df)
            st.success("Card metadata saved.")
            st.cache_data.clear()
            st.rerun()

with tab3:
    st.subheader("Order Tracker")
    st.caption("Enter customer, dates, and order-level cost and revenue totals for the active workspace.")
    if orders.empty:
        st.info("No order data loaded for this workspace.")
    else:
        order_cols = [
            "order_id","cards_submitted","psa_10_count","gem_rate","avg_grade","customer","submission_date","return_date",
            "turnaround_days","psa_fees","shipping_out","shipping_back","other_costs","total_cost","revenue_collected","net_profit","notes"
        ]
        order_edit = filtered_orders[[c for c in order_cols if c in filtered_orders.columns]].copy()
        if "submission_date" in order_edit.columns:
            order_edit["submission_date"] = pd.to_datetime(order_edit["submission_date"], errors="coerce").dt.date
        if "return_date" in order_edit.columns:
            order_edit["return_date"] = pd.to_datetime(order_edit["return_date"], errors="coerce").dt.date

        edited_orders = st.data_editor(
            order_edit,
            use_container_width=True,
            hide_index=True,
            disabled=[c for c in ["order_id","cards_submitted","psa_10_count","gem_rate","avg_grade","turnaround_days","total_cost","net_profit"] if c in order_edit.columns],
            column_config={
                "psa_fees": st.column_config.NumberColumn(format="$%.2f"),
                "shipping_out": st.column_config.NumberColumn(format="$%.2f"),
                "shipping_back": st.column_config.NumberColumn(format="$%.2f"),
                "other_costs": st.column_config.NumberColumn(format="$%.2f"),
                "total_cost": st.column_config.NumberColumn(format="$%.2f", disabled=True),
                "revenue_collected": st.column_config.NumberColumn(format="$%.2f"),
                "net_profit": st.column_config.NumberColumn(format="$%.2f", disabled=True),
            },
            key="orders_editor"
        )

        if st.button("Save order changes"):
            save_cols = [c for c in ["order_id","customer","submission_date","return_date","psa_fees","shipping_out","shipping_back","other_costs","revenue_collected","notes"] if c in edited_orders.columns]
            save_df = edited_orders[save_cols].copy()
            save_order_meta(st.session_state["selected_workspace"], save_df)
            st.success("Order metadata saved.")
            st.cache_data.clear()
            st.rerun()

with tab4:
    st.subheader("Uploads / Export")
    paths = workspace_paths(st.session_state["selected_workspace"])
    raw_files = sorted([p.name for p in paths["raw"].glob("*.csv")])
    st.write(f"Saved CSV files in this workspace: {len(raw_files)}")
    if raw_files:
        st.dataframe(pd.DataFrame({"Saved CSV Files": raw_files}), use_container_width=True, hide_index=True)

    col1, col2 = st.columns(2)
    with col1:
        if not filtered_cards.empty:
            csv_bytes = filtered_cards.to_csv(index=False).encode("utf-8")
            st.download_button("Download filtered card data (CSV)", data=csv_bytes, file_name=f"{st.session_state['selected_workspace']}_cards_export.csv", mime="text/csv")
    with col2:
        if not filtered_orders.empty:
            csv_bytes_orders = filtered_orders.to_csv(index=False).encode("utf-8")
            st.download_button("Download filtered order data (CSV)", data=csv_bytes_orders, file_name=f"{st.session_state['selected_workspace']}_orders_export.csv", mime="text/csv")

    st.markdown("""
**How workspaces work**
- Each workspace stores its own PSA CSV uploads
- Each workspace keeps separate order and card metadata
- Reset only clears the active workspace
- Delete removes only the active workspace
""")
