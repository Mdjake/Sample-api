from fastapi import FastAPI, HTTPException, Query
import duckdb
import os

app = FastAPI()

# Your remote Parquet file address
PARQUET_URL = "https://huggingface.co/datasets/tfqdeadlo/Inddatainonefile/resolve/main/users_data.parquet"

# Initialize DuckDB connection (cold start will trigger)
con = duckdb.connect()
try:
    con.execute("INSTALL httpfs;")
    con.execute("LOAD httpfs;")
    print("httpfs extension loaded.")
except Exception as e:
    # If loading fails, record the error but do not prevent the app from starting
    print(f"Failed to load httpfs: {e}")

@app.get("/search")
async def search_by_phone(phone: str = Query(..., description="Phone number to search, e.g., 6290593159")):
    """
    Search user information by phone number.
    """
    # Note: Please confirm that the column name in the actual Parquet file is 'phoneNumber'.
    # If it's another name (like 'mobile'), please modify the SQL below.
    query = f"SELECT * FROM read_parquet('{PARQUET_URL}') WHERE phoneNumber = ? LIMIT 10"
    
    try:
        # Using parameterized queries to prevent SQL injection
        result = con.execute(query, [phone]).fetchdf()
        
        if result.empty:
            return {"message": "No matching records found", "phone": phone}
        
        # Convert DataFrame to dictionary list and return
        # Note: NaN values may need handling; for simplicity, use to_dict directly here
        return result.to_dict(orient="records")
        
    except Exception as e:
        # Catch DuckDB errors (such as timeouts, file access failures)
        raise HTTPException(status_code=500, detail=f"Query failed: {str(e)}")

@app.get("/")
async def root():
    return {"message": "Phone Search API is running. Use /search?phone=..."}
