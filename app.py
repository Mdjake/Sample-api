import os
import math
import secrets
import datetime
from fastapi import FastAPI, HTTPException, Query, Header
from fastapi.responses import HTMLResponse
import duckdb
from upstash_redis import Redis

# ---------------- CONFIG ----------------
PARQUET_URL = "https://huggingface.co/datasets/tfqdeadlo/Inddatainonefile/resolve/main/users_data.parquet"
ADMIN_SECRET = os.environ.get("ADMIN_SECRET", "")  # Set this in Vercel Environment Variables!

# FIXED: Using the DATA_ prefix as shown in your Vercel/Upstash dashboard
redis = Redis(
    url=os.environ.get("DATA_KV_REST_API_URL", ""),
    token=os.environ.get("DATA_KV_REST_API_TOKEN", ""),
)

app = FastAPI(title="Phone Search API")

# ---------------- DUCKDB INIT ----------------
con = duckdb.connect()
try:
    con.execute("SET home_directory = '/tmp';")
    con.execute("INSTALL httpfs;")
    con.execute("LOAD httpfs;")
    print("httpfs extension loaded successfully.")
except Exception as e:
    print(f"Failed to load httpfs: {e}")

# ---------------- HELPERS ----------------
def make_key(days: int) -> str:
    key = "sk_" + secrets.token_urlsafe(24)
    expiry_dt = datetime.datetime.utcnow() + datetime.timedelta(days=days)
    redis.set(f"key:{key}", expiry_dt.isoformat(), ex=days * 86400)
    return key

def validate_key(key: str) -> bool:
    if not key:
        return False
    try:
        return redis.get(f"key:{key}") is not None
    except Exception:
        return False

def check_admin(secret: str):
    if not ADMIN_SECRET or secret != ADMIN_SECRET:
        raise HTTPException(status_code=401, detail="Unauthorized")

def clean_records(df):
    """Cleans pandas NaN and numpy data types so FastAPI can serialize to JSON."""
    records = df.to_dict(orient="records")
    out = []
    for r in records:
        clean = {}
        for k, v in r.items():
            if isinstance(v, float) and math.isnan(v):
                clean[k] = None
            elif hasattr(v, "item"):  # numpy scalar -> python native
                clean[k] = v.item()
            else:
                clean[k] = v
        out.append(clean)
    return out

# ---------------- PUBLIC SEARCH ----------------
@app.get("/search")
async def search_by_phone(
    phone: str = Query(..., description="Phone number, e.g. 6290593159"),
    key: str = Query(..., description="Your API key"),
):
    if not validate_key(key):
        raise HTTPException(status_code=401, detail="Invalid or expired API key")

    query = f"SELECT * FROM read_parquet('{PARQUET_URL}') WHERE mobile = ? LIMIT 10"
    try:
        df = con.execute(query, [phone]).fetchdf()
        if df.empty:
            return {"message": "No matching records found", "phone": phone}
        return clean_records(df)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Query failed: {str(e)}")

# ---------------- SCHEMA DEBUG ----------------
@app.get("/schema")
async def schema(key: str = Query(...)):
    if not validate_key(key):
        raise HTTPException(status_code=401, detail="Invalid or expired API key")
    try:
        cols = con.execute(
            f"DESCRIBE SELECT * FROM read_parquet('{PARQUET_URL}')"
        ).fetchall()
        return [{"name": c[0], "type": c[1]} for c in cols]
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# ---------------- ADMIN API ----------------
@app.post("/admin/generate")
async def generate_key(
    days: int = Query(..., ge=1, le=365),
    x_admin_secret: str = Header(...),
):
    check_admin(x_admin_secret)
    key = make_key(days)
    expires = redis.get(f"key:{key}")
    return {"key": key, "days": days, "expires_at": expires}

@app.get("/admin/list")
async def list_keys(x_admin_secret: str = Header(...)):
    check_admin(x_admin_secret)
    try:
        keys = redis.keys("key:*")
        return [
            {"key": k.replace("key:", ""), "expires_at": redis.get(k)}
            for k in keys
        ]
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Redis error: {str(e)}")

@app.delete("/admin/revoke")
async def revoke_key(
    key: str = Query(...),
    x_admin_secret: str = Header(...),
):
    check_admin(x_admin_secret)
    redis.delete(f"key:{key}")
    return {"revoked": key}

# ---------------- ADMIN PANEL (HTML) ----------------
@app.get("/admin", response_class=HTMLResponse)
async def admin_panel():
    return """
<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <title>Admin Panel</title>
  <style>
    body { font-family: system-ui, sans-serif; max-width: 700px; margin: 40px auto; padding: 0 16px; }
    input, button { padding: 8px; margin: 4px 0; font-size: 14px; }
    input[type=text], input[type=password] { width: 340px; max-width: 100%; }
    pre { background: #f4f4f4; padding: 12px; border-radius: 6px; white-space: pre-wrap; overflow-x: auto; }
    table { width: 100%; border-collapse: collapse; margin-top: 12px; }
    th, td { border: 1px solid #ddd; padding: 6px; text-align: left; font-size: 13px; word-break: break-all; }
    th { background: #f0f0f0; }
    .row { margin: 16px 0; padding: 12px; border: 1px solid #ddd; border-radius: 6px; }
    button { cursor: pointer; background: #0070f3; color: white; border: none; border-radius: 4px; }
    button:hover { background: #005bb5; }
  </style>
</head>
<body>
  <h2>Admin Panel</h2>

  <div class="row">
    <h3>Admin Secret</h3>
    <input type="password" id="secret" placeholder="Enter ADMIN_SECRET" style="width:340px">
  </div>

  <div class="row">
    <h3>Generate API Key</h3>
    <input type="number" id="days" value="7" min="1" max="365" style="width:80px"> days
    <button onclick="genKey()">Generate</button>
    <pre id="genOut"></pre>
  </div>

  <div class="row">
    <h3>List Keys</h3>
    <button onclick="listKeys()">Refresh</button>
    <div id="listOut"></div>
  </div>

  <script>
    function secret() { return document.getElementById('secret').value; }

    async function genKey() {
      const days = document.getElementById('days').value;
      const r = await fetch(`/admin/generate?days=${days}`, {
        method: 'POST',
        headers: { 'x-admin-secret': secret() }
      });
      document.getElementById('genOut').textContent = await r.text();
      listKeys();
    }

    async function listKeys() {
      const r = await fetch('/admin/list', { headers: { 'x-admin-secret': secret() } });
      if (!r.ok) { document.getElementById('listOut').textContent = await r.text(); return; }
      const data = await r.json();
      if (!data || data.length === 0) { document.getElementById('listOut').innerHTML = '<p>No keys.</p>'; return; }
      
      let html = '<table><tr><th>Key</th><th>Expires At (UTC)</th><th>Action</th></tr>';
      for (const k of data) {
        html += `<tr><td>${k.key}</td><td>${k.expires_at || ''}</td>
          <td><button onclick="revoke('${k.key}')">Revoke</button></td></tr>`;
      }
      html += '</table>';
      document.getElementById('listOut').innerHTML = html;
    }

    async function revoke(key) {
      if (!confirm('Are you sure you want to revoke this key?')) return;
      await fetch(`/admin/revoke?key=${encodeURIComponent(key)}`, {
        method: 'DELETE',
        headers: { 'x-admin-secret': secret() }
      });
      listKeys();
    }

    document.getElementById('secret').addEventListener('change', listKeys);
  </script>
</body>
</html>
    """

# ---------------- ROOT ----------------
@app.get("/")
async def root():
    return {
        "message": "Phone Search API is running.",
        "search_endpoint": "/search?phone=...&key=...",
        "admin_panel": "/admin",
    }
