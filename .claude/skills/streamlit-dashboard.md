# Streamlit Dashboard Patterns

## Architecture dashboard

Le dashboard est READ-ONLY sur la DB. Il ne modifie jamais les données.
Connexion via `infra/db.py` — réutiliser les helpers existants.

## Layout standard

```python
import streamlit as st
import sqlite3
import pandas as pd
from datetime import datetime, timedelta

st.set_page_config(page_title="Polymarket Agent", layout="wide")

# Sidebar pour les filtres globaux
with st.sidebar:
    st.title("Polymarket Agent")
    date_range = st.date_input("Period", value=(datetime.now() - timedelta(days=30), datetime.now()))
    auto_refresh = st.toggle("Auto-refresh (60s)", value=False)

# Tabs principaux
tab_overview, tab_positions, tab_calibration, tab_signals = st.tabs([
    "Overview", "Positions", "Calibration", "Signals"
])
```

## Connexion DB

```python
import infra.config as cfg

@st.cache_resource
def get_db_connection() -> sqlite3.Connection:
    """Single read-only connection, cached across reruns."""
    conn = sqlite3.connect(cfg.DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")  # Read without blocking writes
    return conn

@st.cache_data(ttl=60)  # Cache 60s pour éviter les requêtes répétées
def load_trades(days: int = 30) -> pd.DataFrame:
    conn = get_db_connection()
    query = "SELECT * FROM trades WHERE timestamp > ? ORDER BY timestamp DESC"
    cutoff = (datetime.now() - timedelta(days=days)).isoformat()
    return pd.read_sql(query, conn, params=(cutoff,))
```

## Métriques clés (Overview tab)

- **P&L cumulé** — line chart (x=date, y=cumulative PnL USDC)
- **Win rate** — nombre de trades won / (won + lost)
- **Edge moyen** — moyenne de edge_net sur les trades exécutés
- **Positions ouvertes** — count + total exposure
- **Circuit breaker status** — vert/rouge

## Composants réutilisables

### KPI cards
```python
def kpi_row(metrics: dict[str, tuple[str, str]]):
    """Display a row of KPI cards. metrics = {"label": ("value", "delta")}"""
    cols = st.columns(len(metrics))
    for col, (label, (value, delta)) in zip(cols, metrics.items()):
        col.metric(label, value, delta)
```

### P&L Chart
```python
def pnl_chart(df: pd.DataFrame):
    """Cumulative P&L line chart."""
    df = df.sort_values("timestamp")
    df["cumulative_pnl"] = df["pnl"].cumsum()
    st.line_chart(df.set_index("timestamp")["cumulative_pnl"])
```

## Auto-refresh

```python
if auto_refresh:
    import time
    time.sleep(60)
    st.rerun()
```

## Règles

- NE PAS modifier la DB depuis le dashboard — read-only
- Utiliser `st.cache_data(ttl=60)` pour toutes les requêtes DB
- Utiliser `st.cache_resource` pour la connexion DB
- Layout "wide" pour maximiser l'espace
- Les graphiques doivent fonctionner avec 0 données (empty state gracieux)
- Pas de secrets dans le code Streamlit — tout via infra/config.py
- PRAGMA WAL pour lire sans bloquer l'orchestrator qui écrit
