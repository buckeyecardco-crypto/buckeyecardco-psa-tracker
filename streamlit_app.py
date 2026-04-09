
import re

import pandas as pd
import plotly.express as px
import streamlit as st
from supabase import create_client

st.set_page_config(page_title="BuckeyeCardCo PSA Tracker", page_icon="🅾️", layout="wide")

SUPABASE_URL = st.secrets["SUPABASE_URL"]
SUPABASE_KEY = st.secrets["SUPABASE_KEY"]

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

st.markdown(
    """
<style>
.block-container {padding-top: 1.2rem; padding-bottom: 1.2rem;}
.brand-wrap {
    background: linear-gradient(135deg, #bb0000 0%, #7a0000 100%);
    border-radius: 18px;
    padding: 20px 24px;
    margin-bottom: 18px;
    color: white;
    box-shadow: 0 10px 28px rgba(0,0,0,0.15);
}
.brand-title {font-size: 2rem; font-weight: 800; margin: 0;}
.brand-sub {font-size: 1rem; opacity: 0.95; margin-top: 6px;}
.small-muted {color: #666; font-size: 0.92rem;}
div[data-testid="stMetric"] {
    background: #fafafa;
    border: 1px solid #ececec;
    padding: 8px 12px;
    border-radius: 14px;
}
</style>
""",
    unsafe_allow_html=True,
)


from supabase import create_client, Client

@st.cache_resource
def get_client() -> Client:
    url = st.secrets["SUPABASE_URL"].strip()
    key = st.secrets["SUPABASE_KEY"].strip()
    return create_client(url, key)

supabase = get_client()


def parse_order_id(file_name: str) -> str:
    match = re.search(r"(\d+)", str(file_name))
    return match.group(1) if match else "unknown"


def grade_num(text):
    if pd.isna(text):
        return None
    t = str(text).strip().upper()
    if t in GRADE_MAP:
        return GRADE_MAP[t]
    m = re.search(r"(\d+(?:\.\d+)?)", t)
    return float(m.group(1)) if m else None


def read_psa_csv(file_obj, source_name: str) -> pd.DataFrame:
    df = pd.read_csv(file_obj)
    for col in ["Cert #", "Grade", "Description", "After Service"]:
        if col not in df.columns:
            df[col] = ""
    df["order_id"] = parse_order_id(source_name)
    return df


def fetch_workspaces():
    try:
        res = supabase.table("workspaces").select("*").order("name").execute()
        st.write("Workspaces raw response:", res.data)
        return pd.DataFrame(res.data or [])
    except Exception as e:
        st.error(f"Supabase workspaces query failed: {e}")
        st.stop()


def create_workspace(name: str):
    name = name.strip()
    if not name:
        return None
    existing = supabase.table("workspaces").select("id,name").ilike("name", name).execute().data or []
    if existing:
        return existing[0]["id"]
    res = supabase.table("workspaces").insert({"name": name}).execute()
    return res.data[0]["id"]


def rename_workspace(workspace_id: str, new_name: str):
    supabase.table("workspaces").update({"name": new_name.strip()}).eq("id", workspace_id).execute()


def delete_workspace(workspace_id: str):
    supabase.table("cards").delete().eq("workspace_id", workspace_id).execute()
    supabase.table("orders").delete().eq("workspace_id", workspace_id).execute()
    supabase.table("workspaces").delete().eq("id", workspace_id).execute()


def reset_workspace(workspace_id: str):
    supabase.table("cards").delete().eq("workspace_id", workspace_id).execute()
    supabase.table("orders").delete().eq("workspace_id", workspace_id).execute()


def fetch_orders(workspace_id: str):
    res = supabase.table("orders").select("*").eq("workspace_id", workspace_id).order("order_id").execute()
    return pd.DataFrame(res.data or [])


def fetch_cards(workspace_id: str):
    res = supabase.table("cards").select("*").eq("workspace_id", workspace_id).order("order_id").execute()
    return pd.DataFrame(res.data or [])


def ensure_order_rows(workspace_id: str, order_ids):
    existing = fetch_orders(workspace_id)
    existing_ids = set(existing["order_id"].astype(str).tolist()) if not existing.empty else set()
    new_rows = []
    for oid in order_ids:
        oid = str(oid)
        if oid not in existing_ids:
            new_rows.append(
                {
                    "workspace_id": workspace_id,
                    "order_id": oid,
                    "psa_fees": 0,
                    "shipping": 0,
                    "revenue": 0,
                }
            )
    if new_rows:
        supabase.table("orders").insert(new_rows).execute()


def save_cards_from_upload(workspace_id: str, uploaded_files):
    inserted_files = []
    for file in uploaded_files:
        df = read_psa_csv(file, file.name)
        order_id = parse_order_id(file.name)
        existing = (
            supabase.table("cards")
            .select("cert_no")
            .eq("workspace_id", workspace_id)
            .eq("order_id", str(order_id))
            .execute()
            .data
            or []
        )
        existing_certs = {str(r.get("cert_no", "")) for r in existing}
        rows = []
        for _, row in df.iterrows():
            cert = str(row.get("Cert #", ""))
            if cert in existing_certs:
                continue
            rows.append(
                {
                    "workspace_id": workspace_id,
                    "order_id": str(order_id),
                    "cert_no": cert,
                    "grade": str(row.get("Grade", "")),
                    "sold_price": None,
                    "cost": None,
                }
            )
        if rows:
            supabase.table("cards").insert(rows).execute()
        ensure_order_rows(workspace_id, [order_id])
        inserted_files.append(file.name)
    return inserted_files


def update_orders(workspace_id: str, edited_df: pd.DataFrame):
    for _, row in edited_df.iterrows():
        supabase.table("orders").update(
            {
                "psa_fees": float(row["psa_fees"]) if pd.notna(row["psa_fees"]) else 0,
                "shipping": float(row["shipping"]) if pd.notna(row["shipping"]) else 0,
                "revenue": float(row["revenue"]) if pd.notna(row["revenue"]) else 0,
            }
        ).eq("id", row["id"]).eq("workspace_id", workspace_id).execute()


def update_cards(workspace_id: str, edited_df: pd.DataFrame):
    for _, row in edited_df.iterrows():
        supabase.table("cards").update(
            {
                "sold_price": float(row["sold_price"]) if pd.notna(row["sold_price"]) else None,
                "cost": float(row["cost"]) if pd.notna(row["cost"]) else None,
            }
        ).eq("id", row["id"]).eq("workspace_id", workspace_id).execute()


st.markdown(
    """
<div class="brand-wrap">
  <div class="brand-title">BuckeyeCardCo PSA Tracker</div>
  <div class="brand-sub">Supabase-backed multi-workspace grading dashboard with persistent online storage.</div>
</div>
""",
    unsafe_allow_html=True,
)

# Workspace manager
workspaces_df = fetch_workspaces()
if workspaces_df.empty:
    create_workspace("BuckeyeCardCo")
    workspaces_df = fetch_workspaces()

if "workspace_id" not in st.session_state:
    st.session_state["workspace_id"] = workspaces_df.iloc[0]["id"]

with st.sidebar:
    st.header("Workspace Manager")
    workspace_options = {row["name"]: row["id"] for _, row in workspaces_df.iterrows()}
    current_name = next(
        (name for name, wid in workspace_options.items() if wid == st.session_state["workspace_id"]),
        list(workspace_options.keys())[0],
    )
    selected_name = st.selectbox(
        "Choose workspace",
        options=list(workspace_options.keys()),
        index=list(workspace_options.keys()).index(current_name),
    )
    st.session_state["workspace_id"] = workspace_options[selected_name]
    active_workspace_id = st.session_state["workspace_id"]

    with st.expander("Create new workspace"):
        new_name = st.text_input("New workspace name")
        if st.button("Create workspace") and new_name.strip():
            st.session_state["workspace_id"] = create_workspace(new_name)
            st.rerun()

    with st.expander("Rename current workspace"):
        rename_name = st.text_input("Rename to", value=selected_name)
        if st.button("Rename workspace"):
            rename_workspace(active_workspace_id, rename_name)
            st.rerun()

    with st.expander("Danger zone"):
        confirm_reset = st.checkbox("I understand reset clears this workspace only")
        if st.button("Reset current workspace", disabled=not confirm_reset):
            reset_workspace(active_workspace_id)
            st.rerun()

        confirm_delete = st.checkbox("I understand delete removes this workspace")
        if st.button("Delete current workspace", disabled=not confirm_delete or len(workspace_options) <= 1):
            delete_workspace(active_workspace_id)
            st.session_state.pop("workspace_id", None)
            st.rerun()

    st.divider()
    st.header("Upload")
    uploaded = st.file_uploader("Upload PSA order CSVs", type=["csv"], accept_multiple_files=True)
    if uploaded and st.button("Save uploaded CSVs to database"):
        saved = save_cards_from_upload(active_workspace_id, uploaded)
        st.success("Saved: " + ", ".join(saved) if saved else "No new cards were added.")
        st.rerun()

workspace_id = st.session_state["workspace_id"]
orders_df = fetch_orders(workspace_id)
cards_df = fetch_cards(workspace_id)

cards_view = cards_df.copy()
if not cards_view.empty:
    cards_view["grade_num"] = cards_view["grade"].apply(grade_num)
    cards_view["gem_flag"] = cards_view["grade_num"].eq(10)
    cards_view["sold_price"] = pd.to_numeric(cards_view["sold_price"], errors="coerce")
    cards_view["cost"] = pd.to_numeric(cards_view["cost"], errors="coerce")
    cards_view["margin"] = cards_view["sold_price"].fillna(0) - cards_view["cost"].fillna(0)
else:
    cards_view = pd.DataFrame(
        columns=["order_id", "cert_no", "grade", "sold_price", "cost", "margin", "grade_num", "gem_flag"]
    )

orders_view = orders_df.copy()
if not orders_view.empty:
    orders_view["psa_fees"] = pd.to_numeric(orders_view["psa_fees"], errors="coerce").fillna(0)
    orders_view["shipping"] = pd.to_numeric(orders_view["shipping"], errors="coerce").fillna(0)
    orders_view["revenue"] = pd.to_numeric(orders_view["revenue"], errors="coerce").fillna(0)
    orders_view["total_cost"] = orders_view["psa_fees"] + orders_view["shipping"]
    orders_view["net_profit"] = orders_view["revenue"] - orders_view["total_cost"]
    if not cards_view.empty:
        order_perf = (
            cards_view.groupby("order_id")
            .agg(cards=("cert_no", "count"), psa10s=("gem_flag", "sum"), avg_grade=("grade_num", "mean"))
            .reset_index()
        )
        order_perf["gem_rate"] = order_perf["psa10s"] / order_perf["cards"]
        orders_view = orders_view.merge(order_perf, on="order_id", how="left")
    else:
        orders_view["cards"] = 0
        orders_view["psa10s"] = 0
        orders_view["avg_grade"] = None
        orders_view["gem_rate"] = 0
else:
    orders_view = pd.DataFrame(
        columns=["order_id", "psa_fees", "shipping", "revenue", "total_cost", "net_profit", "cards", "psa10s", "avg_grade", "gem_rate"]
    )

st.markdown(f"### Workspace: {selected_name}")
st.markdown(
    '<div class="small-muted">All data in this version is stored in Supabase, so it stays after restart.</div>',
    unsafe_allow_html=True,
)

tab1, tab2, tab3, tab4 = st.tabs(["Dashboard", "Card Tracker", "Order Tracker", "Uploads / Database"])

with tab1:
    if cards_view.empty:
        st.info("This workspace is blank. Upload PSA CSV files in the sidebar and save them to the database.")
    else:
        total_orders = cards_view["order_id"].nunique()
        total_cards = len(cards_view)
        gem_rate = cards_view["gem_flag"].mean() if total_cards else 0
        avg_grade = cards_view["grade_num"].dropna().mean()
        psa10 = int(cards_view["gem_flag"].sum())
        psa9 = int(cards_view["grade_num"].eq(9).sum())

        c1, c2, c3, c4, c5 = st.columns(5)
        c1.metric("Orders", f"{total_orders}")
        c2.metric("Cards", f"{total_cards}")
        c3.metric("Gem Rate", f"{gem_rate:.1%}")
        c4.metric("Avg Grade", f"{avg_grade:.2f}" if pd.notna(avg_grade) else "—")
        c5.metric("PSA 10s", f"{psa10}")

        c6, c7, c8 = st.columns(3)
        total_revenue = float(orders_view["revenue"].sum()) if not orders_view.empty else 0
        net_profit = float(orders_view["net_profit"].sum()) if not orders_view.empty else 0
        c6.metric("PSA 9s", f"{psa9}")
        c7.metric("Revenue", f"${total_revenue:,.2f}")
        c8.metric("Net Profit", f"${net_profit:,.2f}")

        col1, col2 = st.columns(2)
        with col1:
            grade_dist = cards_view.groupby("grade").size().reset_index(name="count").sort_values("count", ascending=False)
            fig = px.bar(grade_dist, x="grade", y="count", title="Grade Distribution", text_auto=True)
            st.plotly_chart(fig, use_container_width=True)
        with col2:
            order_chart = orders_view[["order_id", "gem_rate"]].copy()
            order_chart["gem_rate"] = pd.to_numeric(order_chart["gem_rate"], errors="coerce").fillna(0)
            fig2 = px.line(order_chart.sort_values("order_id"), x="order_id", y="gem_rate", markers=True, title="Gem Rate by Order")
            fig2.update_yaxes(tickformat=".0%")
            st.plotly_chart(fig2, use_container_width=True)

        st.subheader("Order Performance")
        show = orders_view[["order_id", "cards", "psa10s", "gem_rate", "avg_grade", "total_cost", "revenue", "net_profit"]].copy()
        show["gem_rate"] = show["gem_rate"].map(lambda x: f"{x:.1%}" if pd.notna(x) else "")
        show["avg_grade"] = show["avg_grade"].map(lambda x: f"{x:.2f}" if pd.notna(x) else "")
        st.dataframe(show, use_container_width=True, hide_index=True)

with tab2:
    st.subheader("Card Tracker")
    if cards_view.empty:
        st.info("No card data loaded for this workspace.")
    else:
        editable = cards_view[["id", "order_id", "cert_no", "grade", "cost", "sold_price", "margin"]].copy()
        edited = st.data_editor(
            editable,
            use_container_width=True,
            hide_index=True,
            disabled=["order_id", "cert_no", "grade", "margin"],
            column_config={
                "cost": st.column_config.NumberColumn(format="$%.2f"),
                "sold_price": st.column_config.NumberColumn(format="$%.2f"),
                "margin": st.column_config.NumberColumn(format="$%.2f", disabled=True),
            },
            key="cards_editor",
        )
        if st.button("Save card changes"):
            update_cards(workspace_id, edited[["id", "sold_price", "cost"]])
            st.success("Card changes saved.")
            st.rerun()

with tab3:
    st.subheader("Order Tracker")
    if orders_view.empty:
        st.info("No order data loaded for this workspace.")
    else:
        editable = orders_view[["id", "order_id", "psa_fees", "shipping", "revenue", "total_cost", "net_profit"]].copy()
        edited = st.data_editor(
            editable,
            use_container_width=True,
            hide_index=True,
            disabled=["order_id", "total_cost", "net_profit"],
            column_config={
                "psa_fees": st.column_config.NumberColumn(format="$%.2f"),
                "shipping": st.column_config.NumberColumn(format="$%.2f"),
                "revenue": st.column_config.NumberColumn(format="$%.2f"),
                "total_cost": st.column_config.NumberColumn(format="$%.2f", disabled=True),
                "net_profit": st.column_config.NumberColumn(format="$%.2f", disabled=True),
            },
            key="orders_editor",
        )
        if st.button("Save order changes"):
            update_orders(workspace_id, edited[["id", "psa_fees", "shipping", "revenue"]])
            st.success("Order changes saved.")
            st.rerun()

with tab4:
    st.subheader("Uploads / Database")
    st.write(f"Workspace rows in database: {len(cards_view)} cards, {len(orders_view)} orders")
    if not cards_view.empty:
        st.download_button(
            "Download cards CSV",
            data=cards_view.to_csv(index=False).encode("utf-8"),
            file_name=f"{selected_name.lower().replace(' ', '_')}_cards.csv",
            mime="text/csv",
        )
    if not orders_view.empty:
        st.download_button(
            "Download orders CSV",
            data=orders_view.to_csv(index=False).encode("utf-8"),
            file_name=f"{selected_name.lower().replace(' ', '_')}_orders.csv",
            mime="text/csv",
        )
    st.markdown(
        """
**How this version works**
- Workspaces are stored in Supabase
- Uploaded PSA CSVs are parsed and written into the database
- Order costs and card sale prices save online
- Your data stays there after restart
"""
    )
