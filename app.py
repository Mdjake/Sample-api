from fastapi import FastAPI, HTTPException, Query
import duckdb

app = FastAPI()

PARQUET_URL = "https://huggingface.co/datasets/tfqdeadlo/Inddatainonefile/resolve/main/users_data.parquet"

con = duckdb.connect()

# --- FIX 1: Set a writable home directory for Vercel ---
try:
    con.execute("SET home_directory = '/tmp';")
    con.execute("INSTALL httpfs;")
    con.execute("LOAD httpfs;")
    print("httpfs extension loaded successfully.")
except Exception as e:
    print(f"Failed to load httpfs: {e}")


@app.get("/search")
async def search_by_phone(phone: str = Query(..., description="Phone number, e.g. 6290593159")):
    # --- FIX 2: Use the correct column name 'mobile' ---
    query = f"SELECT * FROM read_parquet('{PARQUET_URL}') WHERE mobile = ? LIMIT 10"

    try:
        result = con.execute(query, [phone]).fetchdf()

        if result.empty:
            return {"message": "No matching records found", "phone": phone}

        return result.to_dict(orient="records")

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Query failed: {str(e)}")


@app.get("/")
async def root():
    return {"message": "Phone Search API is running. Use /search?phone=..."}
