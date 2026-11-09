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
ADMIN_SECRET = os.environ.get("ADMIN_SECRET", "")

# This will check for BOTH the DATA_ prefix and the standard prefix
REDIS_URL = os.environ.get("KV_REST_API_URL") or os.environ.get("DATA_KV_REST_API_URL")
REDIS_TOKEN = os.environ.get("KV_REST_API_TOKEN") or os.environ.get("DATA_KV_REST_API_TOKEN")

if not REDIS_URL:
    print("WARNING: Redis URL not found in environment variables!")

redis = Redis(
    url=REDIS_URL or "",
    token=REDIS_TOKEN or "",
)

app = FastAPI(title="ICMR Darknet Terminal")

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
    expiry_str = expiry_dt.isoformat()
    redis.set(f"key:{key}", expiry_str, ex=days * 86400)
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
        raise HTTPException(status_code=401, detail="Unauthorized. Invalid ADMIN_SECRET.")

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
        raise HTTPException(status_code=401, detail="ACCESS_DENIED: Invalid or expired API key")

    query = f"SELECT * FROM read_parquet('{PARQUET_URL}') WHERE mobile = ? LIMIT 10"
    try:
        df = con.execute(query, [phone]).fetchdf()
        if df.empty:
            return {"message": "NO_DATA_FOUND", "phone": phone}
        return clean_records(df)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"QUERY_FAILED: {str(e)}")

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
        result = []
        now = datetime.datetime.utcnow()
        
        for k in keys:
            expires_at_str = redis.get(k)
            time_left = "Unknown"
            
            if expires_at_str:
                try:
                    # Handle possible quotes from JSON serialization
                    if isinstance(expires_at_str, str):
                        expires_at_str = expires_at_str.strip('"\'')
                    
                    expiry_dt = datetime.datetime.fromisoformat(expires_at_str)
                    delta = expiry_dt - now
                    
                    if delta.total_seconds() > 0:
                        days_left = delta.days
                        hours_left = delta.seconds // 3600
                        time_left = f"{days_left}d {hours_left}h"
                    else:
                        time_left = "Expired"
                except Exception:
                    time_left = "Invalid Date"
            
            result.append({
                "key": k.replace("key:", ""), 
                "expires_at": expires_at_str,
                "time_left": time_left
            })
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Redis error: {str(e)}")

@app.delete("/admin/revoke")
async def revoke_key(
    key: str = Query(...),
    x_admin_secret: str = Header(...),
):
    check_admin(x_admin_secret)
    redis.delete(f"key:{key}")
    return {"status": "REVOKED", "key": key}

# ---------------- ADMIN PANEL (HACKER UI) ----------------
@app.get("/admin", response_class=HTMLResponse)
async def admin_panel():
    return """
<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <title>ROOT@ADMIN:~#</title>
  <link href="https://fonts.googleapis.com/css2?family=Fira+Code:wght@400;600&display=swap" rel="stylesheet">
  <style>
    :root {
      --bg: #0a0a0a;
      --term-green: #00ff41;
      --term-dark: #003b00;
      --alert: #ff3333;
    }
    body {
      background-color: var(--bg);
      color: var(--term-green);
      font-family: 'Fira Code', monospace;
      margin: 0;
      padding: 20px;
      line-height: 1.5;
      text-shadow: 0 0 5px rgba(0, 255, 65, 0.5);
    }
    .container { max-width: 900px; margin: 0 auto; }
    .header {
      border-bottom: 2px solid var(--term-green);
      padding-bottom: 10px;
      margin-bottom: 20px;
      font-size: 24px;
      font-weight: 600;
      letter-spacing: 2px;
    }
    .panel {
      border: 1px solid var(--term-dark);
      background: rgba(0, 59, 0, 0.1);
      padding: 20px;
      margin-bottom: 20px;
      box-shadow: 0 0 10px rgba(0, 255, 65, 0.1);
      border-radius: 4px;
    }
    h3 { margin-top: 0; color: var(--term-green); font-size: 16px; }
    input, button {
      background: black;
      color: var(--term-green);
      border: 1px solid var(--term-green);
      padding: 8px 12px;
      font-family: 'Fira Code', monospace;
      font-size: 14px;
      outline: none;
      transition: all 0.2s;
    }
    input:focus { box-shadow: 0 0 8px var(--term-green); }
    button { cursor: pointer; font-weight: 600; margin-left: 5px; }
    button:hover { background: var(--term-green); color: black; }
    button.danger { border-color: var(--alert); color: var(--alert); text-shadow: 0 0 5px var(--alert); }
    button.danger:hover { background: var(--alert); color: black; box-shadow: 0 0 8px var(--alert); }
    .input-group { display: flex; gap: 10px; align-items: center; flex-wrap: wrap; }
    pre {
      background: #000;
      border: 1px solid var(--term-dark);
      padding: 15px;
      color: var(--term-green);
      overflow-x: auto;
      margin-top: 15px;
    }
    table { width: 100%; border-collapse: collapse; margin-top: 15px; font-size: 13px; }
    th, td { border: 1px solid var(--term-dark); padding: 8px; text-align: left; word-break: break-all; }
    th { background: rgba(0, 255, 65, 0.1); text-transform: uppercase; }
    tr:hover { background: rgba(0, 255, 65, 0.05); }
    .status-ok { color: #00ff41; }
    .status-warn { color: #ffcc00; text-shadow: 0 0 5px #ffcc00; }
    .status-err { color: var(--alert); text-shadow: 0 0 5px var(--alert); }
    .key-text { color: #88ff88; }
    /* Matrix typing cursor animation */
    .cursor::after {
      content: "█";
      animation: blink 1s step-start infinite;
    }
    @keyframes blink { 50% { opacity: 0; } }
  </style>
</head>
<body>
  <div class="container">
    <div class="header">SYSTEM.ADMIN // ACCESS_GRANTED<span class="cursor"></span></div>

    <div class="panel">
      <h3>> AUTHENTICATE_ROOT</h3>
      <div class="input-group">
        <input type="password" id="secret" placeholder="Enter ADMIN_SECRET" style="width:300px" autocomplete="off">
      </div>
    </div>

    <div class="panel">
      <h3>> GENERATE_ACCESS_KEY</h3>
      <div class="input-group">
        <span>LIFESPAN:</span>
        <input type="number" id="days" value="7" min="1" max="365" style="width:80px"> <span>DAYS</span>
        <button onclick="genKey()">EXECUTE</button>
      </div>
      <pre id="genOut" style="display:none;"></pre>
    </div>

    <div class="panel">
      <h3>> ACTIVE_KEYS_DATABASE</h3>
      <button onclick="listKeys()">REFRESH_QUERY</button>
      <div id="listOut"></div>
    </div>
  </div>

  <script>
    function secret() { return document.getElementById('secret').value; }

    async function genKey() {
      if (!secret()) { alert("ROOT ACCESS REQUIRED. ENTER SECRET."); return; }
      const days = document.getElementById('days').value;
      const btn = event.target;
      btn.innerText = "EXECUTING...";
      
      const r = await fetch(`/admin/generate?days=${days}`, {
        method: 'POST',
        headers: { 'x-admin-secret': secret() }
      });
      
      btn.innerText = "EXECUTE";
      const outBox = document.getElementById('genOut');
      outBox.style.display = 'block';
      
      if (!r.ok) {
        outBox.innerHTML = `<span class="status-err">ERROR: ${await r.text()}</span>`;
        return;
      }
      
      const data = await r.json();
      outBox.innerHTML = `
        <div class="status-ok">[+] KEY_GENERATED_SUCCESSFULLY</div>
        <br>
        <b>KEY:</b> <span class="key-text">${data.key}</span><br>
        <b>EXPIRES:</b> ${data.expires_at}<br>
      `;
      listKeys();
    }

    async function listKeys() {
      if (!secret()) { return; }
      const out = document.getElementById('listOut');
      out.innerHTML = '<span class="status-warn">Fetching records from Redis...</span>';
      
      const r = await fetch('/admin/list', { headers: { 'x-admin-secret': secret() } });
      
      if (!r.ok) { 
        out.innerHTML = `<span class="status-err">ACCESS_DENIED: ${await r.text()}</span>`; 
        return; 
      }
      
      const data = await r.json();
      if (!data || data.length === 0) { 
        out.innerHTML = '<span class="status-warn">NO_ACTIVE_KEYS_FOUND</span>'; 
        return; 
      }
      
      let html = '<table><tr><th>Access Key</th><th>Expires In</th><th>Action</th></tr>';
      for (const k of data) {
        let timeClass = "status-ok";
        if (k.time_left === "Expired") timeClass = "status-err";
        else if (k.time_left.includes("0d")) timeClass = "status-warn";

        html += `<tr>
          <td class="key-text">${k.key}</td>
          <td class="${timeClass}">${k.time_left}</td>
          <td><button class="danger" onclick="revoke('${k.key}')">TERMINATE</button></td>
        </tr>`;
      }
      html += '</table>';
      out.innerHTML = html;
    }

    async function revoke(key) {
      if (!confirm('WARNING: PURGE KEY? THIS ACTION IS IRREVERSIBLE.')) return;
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
        "status": "ONLINE",
        "message": "Search endpoint is active.",
        "auth": "API Key Required",
        "admin_portal": "/admin"
    }
