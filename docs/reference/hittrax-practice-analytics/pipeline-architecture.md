# Pipeline Architecture Documentation

## Overview

The LMU Baseball Practice Analytics Pipeline is a fully automated ELT (Extract-Load-Transform) system that processes HitTrax baseball practice data into queryable analytics tables.

---

## Architecture Diagram

```
┌──────────────────────────────────────────────────────────────────────┐
│                          DATA SOURCES                                 │
├──────────────────────────────────────────────────────────────────────┤
│  FTPS Server (FileZilla)                                             │
│  ├── PlaysExport_YYYY-MM-DD-HH-MM-SS_UTC.CSV                        │
│  │   └── Individual play-by-play records (EBV1, Dist, HT, etc.)     │
│  └── SessionExport_YYYY-MM-DD-HH-MM-SS_UTC.CSV                      │
│      └── Pre-aggregated session statistics (AEV, MEV, AD, MD, etc.) │
└──────────────────────────────────────────────────────────────────────┘
                              │
                              │ ① EXTRACT & LOAD
                              │ (scripts/practice_elt.py)
                              │
                              ▼
┌──────────────────────────────────────────────────────────────────────┐
│                       RAW DATA LAYER                                  │
├──────────────────────────────────────────────────────────────────────┤
│  MySQL Table: raw_practice_csv                                       │
│  ├── source_file VARCHAR(255)    - Original CSV filename            │
│  ├── ingested_at_utc DATETIME    - Timestamp of ingestion           │
│  ├── row_hash VARCHAR(64)        - SHA-256 hash for deduplication   │
│  └── payload JSON                - Full row as JSON object           │
│                                                                       │
│  Purpose: Immutable storage of all raw data for reprocessing        │
└──────────────────────────────────────────────────────────────────────┘
                              │
                              │ ② TRANSFORM
                              │ (scripts/practice_transform.py)
                              │
                              ▼
┌──────────────────────────────────────────────────────────────────────┐
│                     ANALYTICS LAYER                                   │
├──────────────────────────────────────────────────────────────────────┤
│  practice_sessions (2,040 records)                                   │
│  ├── Session-level aggregates from SessionExport                    │
│  ├── Performance metrics (avg/max velocities, distances)            │
│  ├── Hit distribution (GB%, FB%, LD%)                               │
│  ├── Traditional stats (AVG, SLG, RBI)                              │
│  └── Training context (drill IDs, game UUIDs)                       │
│                                                                       │
│  practice_plays (8,133 records)                                      │
│  ├── Individual play records from PlaysExport                       │
│  ├── Ball flight metrics (EV, LA, distance, hang time)              │
│  ├── Hit classification (type, result, quality)                     │
│  ├── Pitch metrics (velocity, angle)                                │
│  └── Linked to sessions via session_id FK                           │
│                                                                       │
│  player_stats_summary (aggregated)                                   │
│  ├── Player-level performance summaries                             │
│  ├── Total sessions & plays                                         │
│  ├── Avg/max velocities and distances                               │
│  └── Quality metrics (hard hit %, hit distribution)                 │
└──────────────────────────────────────────────────────────────────────┘
                              │
                              │ ③ QUERY & ANALYZE
                              │
                              ▼
┌──────────────────────────────────────────────────────────────────────┐
│                      CONSUMPTION LAYER                                │
├──────────────────────────────────────────────────────────────────────┤
│  • SQL Queries (Ad-hoc analysis)                                     │
│  • Looker Studio Dashboards (Planned)                               │
│  • Excel/CSV Exports                                                 │
│  • Python Analytics Scripts                                          │
└──────────────────────────────────────────────────────────────────────┘
```

---

## Data Flow Detail

### 1. Extract & Load Phase

**Script:** `scripts/practice_elt.py`

**Process:**
1. Connect to FTPS server via FTP_TLS
2. List all CSV files in remote directory
3. Download new files (skip if already downloaded)
4. For each CSV file:
   - Read CSV with pandas
   - Convert each row to JSON
   - Compute SHA-256 hash for deduplication
   - Insert into `raw_practice_csv` with `INSERT IGNORE`
5. Close FTPS connection

**Key Features:**
- Idempotent: Re-running won't create duplicates (row_hash UNIQUE constraint)
- Incremental: Only downloads new files
- Error handling: Skips empty/invalid CSVs

**Code Sample:**
```python
# Extract from FTPS
ftps = ftplib.FTP_TLS()
ftps.connect(FTPS_HOST, FTPS_PORT)
ftps.auth()
ftps.login(FTPS_USER, FTPS_PASSWORD)
ftps.prot_p()

csv_files = [f for f in ftps.nlst() if f.endswith('.csv')]

for filename in csv_files:
    local_path = os.path.join(staging_dir, filename)
    with open(local_path, 'wb') as f:
        ftps.retrbinary(f'RETR {filename}', f.write)

# Load to MySQL
df = pd.read_csv(local_path)
for _, row in df.iterrows():
    payload = row.to_dict()
    row_hash = hashlib.sha256(
        json.dumps(payload, sort_keys=True).encode()
    ).hexdigest()

    conn.execute("""
        INSERT IGNORE INTO raw_practice_csv
        (source_file, ingested_at_utc, row_hash, payload)
        VALUES (?, ?, ?, CAST(? AS JSON))
    """, [filename, datetime.utcnow(), row_hash, json.dumps(payload)])
```

---

### 2. Transform Phase

**Script:** `scripts/practice_transform.py`

**Process:**

#### 2.1 SessionExport Processing

1. Query raw table for SessionExport records
2. Parse JSON payloads into DataFrame
3. Transform fields:
   - Convert velocities: m/s → mph (× 2.23694)
   - Convert distances: meters → feet (× 3.28084)
   - Map HitTrax field names to schema columns
4. Load to `practice_sessions` table

**Code Sample:**
```python
# Extract SessionExport
query = """
    SELECT source_file, payload
    FROM raw_practice_csv
    WHERE source_file LIKE '%%SessionExport%%'
"""
raw_sessions = pd.read_sql(query, engine)

# Parse and normalize JSON
raw_sessions['data'] = raw_sessions['payload'].apply(json.loads)
sessions_normalized = pd.json_normalize(raw_sessions['data'])

# Transform with unit conversions
sessions_transformed = pd.DataFrame()
sessions_transformed['avg_exit_velocity'] = sessions_normalized['AEV'].apply(
    lambda x: mps_to_mph(safe_numeric(x))
)
sessions_transformed['avg_distance'] = sessions_normalized['AD'].apply(
    lambda x: meters_to_feet(safe_numeric(x))
)

# Load to database
sessions_transformed.to_sql(
    'practice_sessions',
    engine,
    if_exists='append',
    index=False
)
```

#### 2.2 PlaysExport Processing

1. Query raw table for PlaysExport records
2. Parse JSON payloads into DataFrame
3. Transform fields with unit conversions
4. Map session_ids by joining on (player_id, session_date)
5. Load to `practice_plays` table

**Code Sample:**
```python
# Extract PlaysExport
query = """
    SELECT source_file, payload
    FROM raw_practice_csv
    WHERE source_file LIKE 'PlaysExport%%'
"""
raw_plays = pd.read_sql(query, engine)

# Parse and transform
plays_normalized = pd.json_normalize(raw_plays['payload'].apply(json.loads))

transformed = pd.DataFrame()
transformed['exit_velocity'] = plays_normalized['EBV1'].apply(
    lambda x: mps_to_mph(safe_numeric(x))
)
transformed['distance_feet'] = plays_normalized['Dist'].apply(
    lambda x: meters_to_feet(safe_numeric(x))
)

# Map to sessions
transformed['session_date'] = transformed['play_timestamp'].dt.date

sessions_with_ids = pd.read_sql(
    "SELECT session_id, session_date, player_id FROM practice_sessions",
    engine
)

transformed = transformed.merge(
    sessions_with_ids,
    on=['session_date', 'player_id'],
    how='left'
)
```

#### 2.3 Player Stats Aggregation

1. Aggregate plays by player_id
2. Calculate performance metrics:
   - Avg/max exit velocity
   - Avg/max distance
   - Hard hit rate (EV >= 95 mph)
   - Hit distribution (GB%, FB%, LD%)
3. Upsert to `player_stats_summary`

**Code Sample:**
```python
stats_query = """
    INSERT INTO player_stats_summary
    (player_id, total_plays, avg_exit_velocity, max_exit_velocity, ...)
    SELECT
        player_id,
        COUNT(*) as total_plays,
        AVG(CASE WHEN exit_velocity > 0 THEN exit_velocity END) as avg_ev,
        MAX(exit_velocity) as max_ev,
        SUM(CASE WHEN exit_velocity >= 95 THEN 1 ELSE 0 END) * 100.0 / COUNT(*) as hard_hit_rate
    FROM practice_plays
    WHERE player_id IS NOT NULL
    GROUP BY player_id
    ON DUPLICATE KEY UPDATE
        total_plays = VALUES(total_plays),
        avg_exit_velocity = VALUES(avg_exit_velocity),
        ...
"""
```

---

## Unit Conversion System

### Problem
HitTrax exports data in **metric units** (m/s, meters), but coaches and analysts expect **US Customary units** (mph, feet).

### Solution
Conversion functions applied during transformation:

```python
def mps_to_mph(mps):
    """Convert meters per second to miles per hour"""
    if mps is None or pd.isna(mps):
        return None
    return round(mps * 2.23694, 2)

def meters_to_feet(meters):
    """Convert meters to feet"""
    if meters is None or pd.isna(meters):
        return None
    return round(meters * 3.28084, 2)
```

### Applied To
- **Velocities:** exit_velocity, pitch_velocity, radar_velocity, peak_velocity, hard_hit_velocity
- **Distances:** distance_feet, ground_distance, avg_distance, max_distance
- **Strike Zone:** strike_zone_top, strike_zone_bottom, strike_zone_width

### Verification
```python
# Test case
raw_value = 28.61  # m/s from HitTrax
converted = mps_to_mph(raw_value)
# Output: 64.01 mph ✓
```

---

## Session-to-Play Mapping Logic

### Challenge
Link individual plays to their parent sessions when:
- Multiple sessions per player per day
- Timestamps may not align perfectly
- SessionExport and PlaysExport are separate files

### Solution
```python
# Step 1: Create sessions from SessionExport
sessions = load_session_export_data()
sessions.to_sql('practice_sessions', engine, if_exists='append')

# Step 2: Fetch sessions with auto-generated IDs
sessions_with_ids = pd.read_sql(
    "SELECT session_id, session_date, player_id FROM practice_sessions",
    engine
)

# Step 3: Map plays to sessions
plays['session_date'] = plays['play_timestamp'].dt.date

# Dedupe to prevent duplicate plays (one session per player per day)
sessions_deduped = sessions_with_ids.drop_duplicates(
    subset=['session_date', 'player_id'],
    keep='first'
)

# Merge on date + player
plays = plays.merge(
    sessions_deduped[['session_id', 'session_date', 'player_id']],
    on=['session_date', 'player_id'],
    how='left'
)
```

### Results
- **96.3% mapping success rate**
- 3.7% unmapped plays (no matching session)
- Prevents duplicate play records

---

## Data Quality Checks

### Foreign Key Integrity

**Problem:** `TRUNCATE TABLE` fails when child tables have foreign keys

**Solution:**
```python
with engine.begin() as conn:
    conn.execute(text("SET FOREIGN_KEY_CHECKS = 0"))
    conn.execute(text("TRUNCATE TABLE practice_sessions"))
    conn.execute(text("TRUNCATE TABLE practice_plays"))
    conn.execute(text("TRUNCATE TABLE player_stats_summary"))
    conn.execute(text("SET FOREIGN_KEY_CHECKS = 1"))
```

### NULL Handling

**Problem:** Missing values converted to 0 instead of NULL, skewing averages

**Solution:**
```python
# WRONG: Converts missing to 0
transformed['exit_velocity'] = data['EBV1'].apply(
    lambda x: safe_numeric(x, default=0)  # ❌ Bad!
)

# RIGHT: Converts missing to NULL
transformed['exit_velocity'] = data['EBV1'].apply(
    lambda x: safe_numeric(x)  # ✅ Good!
)
```

### Deduplication

**Problem:** Re-running pipeline creates duplicate records

**Solution:**
- Raw layer: `row_hash UNIQUE` constraint with `INSERT IGNORE`
- Analytics layer: `TRUNCATE` before load (full replace)
- Play records: `play_id UNIQUE` constraint

---

## Automation via GitHub Actions

### Workflow Configuration

**File:** `.github/workflows/etl.yml`

```yaml
name: Run ETL Pipeline

on:
  push:
    branches: [main]
  schedule:
    - cron: '10 13 * * 1-6'   # Mon-Sat 13:10 UTC
  workflow_dispatch:           # Manual trigger

jobs:
  build:
    runs-on: ubuntu-latest

    steps:
      - name: Initialize database schema
        run: python -c "..."   # Create tables

      - name: Extract and load from FTPS
        run: python scripts/practice_elt.py

      - name: Transform to analytics tables
        run: python scripts/practice_transform.py

      - name: Validate transformation
        run: python -c "..."   # Check row counts
```

### Environment Secrets

Configured in GitHub repo settings:
- `MYSQL_HOST`, `MYSQL_USER`, `MYSQL_PASSWORD`, `MYSQL_DB`
- `FTPS_HOST`, `FTPS_USER`, `FTPS_PASSWORD`, `FTPS_REMOTE_DIR`
- `RAW_TABLE`

### Execution

- **Trigger:** Code push, schedule, or manual
- **Duration:** ~5-6 minutes average
- **Notifications:** GitHub UI, email on failure

---

## Error Handling

### FTPS Connection Errors

```python
try:
    ftps = ftplib.FTP_TLS()
    ftps.connect(FTPS_HOST, FTPS_PORT, timeout=30)
    ftps.auth()
    ftps.login(FTPS_USER, FTPS_PASSWORD)
    ftps.prot_p()
except Exception as e:
    print(f"❌ FTPS connection failed: {e}")
    raise
finally:
    try:
        ftps.quit()
    except:
        ftps.close()
```

### Database Connection Errors

```python
engine = create_engine(
    f"mysql+pymysql://{USER}:{PASS}@{HOST}:{PORT}/{DB}",
    pool_pre_ping=True,        # Verify connections before use
    connect_args={'connect_timeout': 30}
)
```

### Empty/Invalid CSV Handling

```python
if os.path.getsize(csv_path) < 10:
    print(f"Skipping empty file: {filename}")
    return 0

try:
    df = pd.read_csv(csv_path)
except pd.errors.EmptyDataError:
    print(f"Skipping unreadable CSV: {filename}")
    return 0

if df.shape[1] == 0:
    print(f"Skipping CSV with no columns: {filename}")
    return 0
```

---

## Performance Optimization

### Batch Loading

```python
# Load in chunks instead of row-by-row
df.to_sql(
    'practice_plays',
    engine,
    if_exists='append',
    index=False,
    method='multi',     # Use multi-row inserts
    chunksize=1000      # 1000 rows per insert
)
```

### SQL Optimization

```sql
-- Use indexes for common queries
CREATE INDEX idx_session_date ON practice_sessions(session_date);
CREATE INDEX idx_player_id ON practice_plays(player_id);
CREATE INDEX idx_play_timestamp ON practice_plays(play_timestamp);

-- Unique constraints prevent duplicates
UNIQUE KEY unique_play (play_id);
UNIQUE KEY unique_session (session_date, player_id, hittrax_session_id);
```

### Connection Pooling

```python
# SQLAlchemy manages connection pooling automatically
engine = create_engine(
    connection_string,
    pool_pre_ping=True,
    pool_size=5,
    max_overflow=10
)
```

---

## Monitoring & Observability

### Pipeline Health Metrics

```sql
-- Check data freshness
SELECT
    MAX(ingested_at_utc) as last_ingestion,
    COUNT(*) as total_records
FROM raw_practice_csv;

-- Validate transformation completeness
SELECT
    (SELECT COUNT(*) FROM practice_sessions) as sessions,
    (SELECT COUNT(*) FROM practice_plays) as plays,
    (SELECT COUNT(*) FROM player_stats_summary) as players;

-- Check mapping success rate
SELECT
    COUNT(CASE WHEN session_id IS NOT NULL THEN 1 END) * 100.0 / COUNT(*) as mapping_pct
FROM practice_plays;
```

### GitHub Actions Logs

```bash
# View recent runs
gh run list --limit 5

# View specific run logs
gh run view <run-id> --log

# Filter for failures
gh run list --status failure
```

---

## Future Enhancements

### Planned Improvements

1. **Incremental Transformation**
   - Currently: Full table truncate/reload
   - Proposed: Process only new records since last run
   - Benefit: Faster processing, preserve historical corrections

2. **Data Lineage Tracking**
   - Add metadata: transformation_timestamp, pipeline_version
   - Track which raw records produced which analytics records
   - Enable audit trails and debugging

3. **Real-time Streaming**
   - Current: Batch processing (daily)
   - Proposed: Stream processing as files arrive
   - Benefit: Near real-time analytics

4. **Data Quality Dashboard**
   - Automated anomaly detection
   - Data freshness monitoring
   - Mapping success rate trends

---

## References

- **HitTrax System:** Baseball/softball training technology
- **ELT Pattern:** Extract-Load-Transform (vs ETL)
- **Metric Conversions:** NIST SI/US Customary conversion factors
- **GitHub Actions:** https://docs.github.com/en/actions

---

*Last updated: February 11, 2026*
