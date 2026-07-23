# LMU Baseball Analytics Dashboard Prototypes

Three different dashboard prototypes for coach review. Each focuses on different features to help determine which capabilities should be prioritized in the final Looker dashboard.

## 🎯 Prototype Overview

### **Prototype 1: Team Overview** (`app.py`)
**Focus:** High-level team metrics and basic player analysis

**Features:**
- Team Overview tab
  - Total plays, sessions, active players KPIs
  - Top 10 players by total plays (bar chart)
  - Hit type distribution (pie chart)
  - Exit velocity leaderboard (grouped bar chart)
- Player Analysis tab
  - Individual player metrics and KPIs
  - Exit velocity and distance trends over time
  - Hit type breakdown
- Session Browser tab
  - Date range filtering
  - Sessions per week visualization
  - Searchable sessions table

**Best for:** General team overview and basic player tracking

---

### **Prototype 2: Advanced Analytics** (`app2.py`)
**Focus:** Deep analytics, player comparisons, correlations, distributions

**Features:**
- Player Comparison tab
  - Side-by-side comparison of 2-3 players
  - Metrics comparison table
  - Exit velocity and distance comparisons
  - Hit type distribution comparison
- Trend Analysis tab
  - Multi-player performance trends
  - Moving averages (3-session)
  - Exit velocity and distance trends over time
- Performance Distribution tab
  - Histogram distributions (exit velocity, distance)
  - Box plots comparing top players
- Correlations tab
  - Exit velocity vs distance scatter plots with trendlines
  - Launch angle vs distance analysis
  - Correlation matrix heatmap

**Best for:** Coaches who want deep statistical analysis and player comparisons

---

### **Prototype 3: Player Development** (`app3.py`)
**Focus:** Progress tracking, improvement metrics, consistency analysis

**Features:**
- Player Progress Report tab
  - Individual player improvement metrics
  - First-half vs second-half comparison
  - Consistency metrics
  - Session-by-session progress with trend lines
- Weekly Summary tab
  - Week selector for historical review
  - Weekly KPIs (sessions, plays, active players)
  - Top performers of the week
  - Daily practice activity
  - Player participation table
- Consistency Metrics tab
  - Player consistency rankings
  - Performance vs consistency scatter plots
  - Standard deviation analysis
- Practice Insights tab
  - Most active players (last 30 days)
  - Players needing attention (14+ days inactive)
  - Team performance trends by week
  - Participation rate metrics

**Best for:** Coaches focused on player development and tracking improvement over time

---

## 🚀 Running the Dashboards

### Prerequisites
```bash
# Install dependencies (if not already done)
source .venv/bin/activate
pip install -r requirements.txt

# Ensure your .env file has MySQL credentials
MYSQL_HOST=your_host
MYSQL_PORT=3306
MYSQL_DB=your_database
MYSQL_USER=your_user
MYSQL_PASSWORD=your_password
```

### Launch Each Prototype

**Prototype 1 - Team Overview:**
```bash
streamlit run dashboard/app.py
```

**Prototype 2 - Advanced Analytics:**
```bash
streamlit run dashboard/app2.py
```

**Prototype 3 - Player Development:**
```bash
streamlit run dashboard/app3.py
```

Each dashboard will open at `http://localhost:8501`

---

## 📋 Decision Matrix for Coaches

Use this to decide which features to include in the final Looker dashboard:

| Feature | Prototype 1 | Prototype 2 | Prototype 3 |
|---------|-------------|-------------|-------------|
| Team overview & KPIs | ✅ | ❌ | ❌ |
| Basic player stats | ✅ | ❌ | ❌ |
| Session browser | ✅ | ❌ | ❌ |
| Player comparisons | ❌ | ✅ | ❌ |
| Statistical correlations | ❌ | ✅ | ❌ |
| Performance distributions | ❌ | ✅ | ❌ |
| Trend analysis | ❌ | ✅ | ❌ |
| Progress tracking | ❌ | ❌ | ✅ |
| Improvement metrics | ❌ | ❌ | ✅ |
| Consistency analysis | ❌ | ❌ | ✅ |
| Weekly summaries | ❌ | ❌ | ✅ |
| Practice insights | ❌ | ❌ | ✅ |

---

## 💡 Recommendations

**For initial coach feedback meeting:**
1. Start with **Prototype 1** - familiar, straightforward interface
2. Show **Prototype 3** - emphasize player development features
3. End with **Prototype 2** - demonstrate advanced capabilities

**Questions to ask coaches:**
- Which metrics do you look at most often?
- Do you prefer comparing players side-by-side or tracking individual progress?
- How important are correlations and statistical analysis?
- Would you use weekly summaries regularly?
- What features are "must-have" vs "nice-to-have"?

---

## 🔄 Next Steps

After coach review:
1. Document preferred features from each prototype
2. Create combined feature list for Looker dashboard
3. Prioritize features by coaching value
4. Design final Looker dashboard layout
5. Implement in Looker Studio

---

## 📝 Notes

- All prototypes share the same database connection
- Data refreshes daily via GitHub Actions (Mon-Sat 13:10 UTC)
- Test accounts can be filtered out via sidebar checkbox
- Each prototype is fully independent (can run separately)
