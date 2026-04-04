BuckeyeCardCo PSA Tracker - Supabase Version

This version uses Supabase instead of local folders, so workspace data persists online.

Before using:
1. In Supabase, create these tables:
   - workspaces
   - orders
   - cards
2. Turn OFF RLS for now on those tables.
3. Use these columns:
   workspaces: id uuid pk, name text, created_at timestamp default now()
   orders: id uuid pk, workspace_id uuid, order_id text, psa_fees numeric, shipping numeric, revenue numeric, created_at timestamp default now()
   cards: id uuid pk, workspace_id uuid, order_id text, cert_no text, grade text, sold_price numeric, cost numeric, created_at timestamp default now()

How to run locally:
1. Open Command Prompt in this folder
2. Run:
   python -m pip install -r requirements.txt
3. Run:
   python -m streamlit run streamlit_app.py

How to deploy:
- Upload these files to GitHub
- Deploy on Streamlit Community Cloud
