"""Integration tests for the hitting transforms against the live DB.

These validate the R->pandas port via invariants and cross-checks (not brittle
hardcoded stat lines): swing+take reconciles to total, PA counting agrees between
two methods, spray/radial coordinates satisfy their geometry, etc.
"""
import numpy as np
import pandas as pd
import pytest

from app.data import hitting
from app.db import query_df


# --------------------------- fixtures -------------------------------------

@pytest.fixture(scope="module")
def test_batter():
    """The LMU batter with the most tracked pitches (guarantees rich data)."""
    cand = query_df(
        """
        SELECT BatterId, Batter, COUNT(*) AS pitches
          FROM GAMES
         WHERE BatterTeam = 'LOY_LIO' AND BatterId IS NOT NULL
         GROUP BY BatterId, Batter
         ORDER BY pitches DESC
         LIMIT 1
        """
    )
    return int(cand.loc[0, "BatterId"]), cand.loc[0, "Batter"]


@pytest.fixture(scope="module")
def games(test_batter):
    bid, _ = test_batter
    return hitting.games_for_batter(bid)


@pytest.fixture(scope="module")
def game_df(test_batter, games):
    """Most recent game that actually has a ball in play, for full coverage."""
    bid, _ = test_batter
    for gid in games["TrackmanGameId"]:
        df = hitting.game_pitches(gid, bid)
        if not df.empty and (df["PitchCall"] == "InPlay").any():
            return df
    return hitting.game_pitches(games.loc[0, "TrackmanGameId"], bid)


# --------------------------- queries --------------------------------------

def test_games_for_batter_nonempty(games):
    assert len(games) > 0
    assert {"GameName", "TrackmanGameId", "LMUScore", "OppScore"} <= set(games.columns)


def test_game_pitches_has_video_and_category(game_df):
    assert not game_df.empty
    for col in ("CenterField", "HomeLeft", "HomeRight", "Broadcast", "PitchCat"):
        assert col in game_df.columns
    assert set(game_df["PitchCat"].unique()) <= {"Fastball", "Offspeed"}


# --------------------------- PA numbering & batting line -------------------

def test_pa_numbering_is_faithful_to_r(game_df):
    """PA in the batting line uses R's cumsum(PitchofPA==1) method.

    Note: this can UNDERCOUNT vs grouping by (Inning, PAofInning) when a PA is
    missing its first tracked pitch (a Trackman gap). The R app has this same
    quirk (its `overall` table shows the cumsum count while QAB sums over the
    group count), so we reproduce it. cumsum count is therefore <= group count.
    """
    line = hitting.game_batting_line(game_df)
    assert line["PA"] == int((game_df["PitchofPA"] == 1).sum())
    assert line["PA"] <= len(hitting.qab_frame(game_df))


def test_batting_line_invariants(game_df):
    line = hitting.game_batting_line(game_df)
    # doubles/triples/HR are all hits, so cannot exceed H
    assert line["2B"] + line["3B"] + line["HR"] <= line["H"]
    assert 0 <= line["QAB"] <= line["PA"]
    assert line["H"] == int(((game_df["PitchCall"] == "InPlay") &
                             (game_df["PlayResult"] != "Out")).sum())


# --------------------------- batted ball ----------------------------------

def test_batted_ball_ev_split(game_df):
    prof = hitting.batted_ball_profile(game_df)
    row = prof.iloc[0]
    non_null_ev = int(game_df["ExitSpeed"].notna().sum())
    assert row["EV 90+"] + row["EV <90"] == non_null_ev


def test_batted_ball_by_pitch_type_sums(game_df):
    overall = hitting.batted_ball_profile(game_df).iloc[0]
    by_pt = hitting.batted_ball_profile(game_df, by_pitch_type=True)
    assert "Pitch Type" in by_pt.columns
    # hit-type counts must reconcile across the pitch-type split
    for col in ("FlyBall", "GroundBall", "LineDrive", "PopUp"):
        assert by_pt[col].sum() == overall[col]


# --------------------------- plate discipline -----------------------------

def test_swing_take_reconciles(game_df):
    z = hitting.swing_decisions_by_zone(game_df)
    assert (z["Swing"] + z["Take"] == z["Total"]).all()
    in_zone = game_df[game_df["Zone"].isin(hitting.ZONE_LEVELS)]
    assert z["Total"].sum() == len(in_zone)


def test_plate_discipline_percentages(game_df):
    pd_zone = hitting.plate_discipline(game_df, by="zone")
    assert list(pd_zone["Zone"]) == hitting.ZONE_LEVELS
    for _, r in pd_zone.iterrows():
        for c in ("Swing %", "Whiff %", "Take %", "Contact %"):
            assert 0.0 <= r[c] <= 100.0
        if r["Total"] > 0:
            # whiffs are a subset of swings
            assert r["Whiff %"] <= r["Swing %"] + 0.11  # rounding slack

    pd_pt = hitting.plate_discipline(game_df, by="pitch_type")
    assert "Pitch Type" in pd_pt.columns
    assert pd_pt["Total"].is_monotonic_decreasing  # arranged desc(Total)


# --------------------------- QAB ------------------------------------------

def test_qab_flag_is_binary(game_df):
    q = hitting.qab_frame(game_df)
    assert set(q["QAB"].unique()) <= {0, 1}


def test_season_qab_rate_range(test_batter):
    bid, _ = test_batter
    rate = hitting.season_qab_rate(bid)
    assert rate is None or 0.0 <= rate <= 1.0


# --------------------------- last 27 & kpi --------------------------------

def test_last_27_pa_cap(test_batter, games):
    bid, _ = test_batter
    gname = games.loc[0, "GameName"]
    last = hitting.last_27_pa_pitches(bid, gname)
    if not last.empty:
        assert last["PA"].max() <= 27
        assert last["PlateLocSide"].notna().all()


def test_kpi_dates_subset(test_batter, games):
    bid, _ = test_batter
    last = hitting.last_27_pa_pitches(bid, games.loc[0, "GameName"])
    dates = list(last["Date"].unique()) if not last.empty else []
    kpi = hitting.kpi_by_date(bid, dates)
    assert set(kpi["Date"]) <= set(dates)


# --------------------------- geometry -------------------------------------

def test_spray_geometry(game_df):
    spray = hitting.spray_coordinates(game_df)
    if not spray.empty:
        r2 = spray["spray_x"] ** 2 + spray["spray_y"] ** 2
        assert np.allclose(r2, spray["Distance"] ** 2, rtol=1e-6)


def test_radial_geometry(game_df):
    rad = hitting.radial_coordinates(game_df)
    rad = rad[rad["ExitSpeed"].notna() & rad["Angle"].notna()]
    if not rad.empty:
        r = np.sqrt(rad["Xcoord"] ** 2 + rad["Ycoord"] ** 2)
        assert np.allclose(r, rad["ExitSpeed"] / 120, rtol=1e-6)


def test_avg_ev_intervals_sorted(test_batter):
    bid, _ = test_batter
    season = hitting.season_pitches(bid)
    ev = hitting.avg_ev_intervals(season)
    if not ev.empty:
        assert ev["Interval_Date"].is_monotonic_increasing
        assert ev["Avg_EV"].notna().all()


# --------------------------- empty-input safety ---------------------------

def test_transforms_handle_empty():
    empty = pd.DataFrame(columns=["PitchCall", "PlayResult", "ExitSpeed", "Zone",
                                  "TaggedPitchType", "TaggedHitType", "PitchofPA",
                                  "Distance", "Direction", "Bearing", "Angle",
                                  "KorBB", "RunsScored", "GameID", "Inning",
                                  "PAofInning", "Strikes", "Balls", "PitchNo",
                                  "QC", "PathQ", "HangTime"])
    assert hitting.game_batting_line(empty)["PA"] == 0
    assert hitting.batted_ball_profile(empty).empty
    assert len(hitting.swing_decisions_by_zone(empty)) == 4  # 4 zone rows, zeros
    assert hitting.plate_discipline(empty, by="zone").empty
    assert hitting.spray_coordinates(empty).empty


def test_slash_counts_matches_slash_from_pas_and_breaks_out_extra_bases():
    """_slash_counts (Phase 4 precalc) returns the int counts behind the slash
    line, sharing _slash_from_pas's exact AB/H/BB definitions so precalc can't
    drift, and additionally breaks out doubles/triples/hr/so/pa."""
    pas = pd.DataFrame([
        {"KorBB": "Walk",      "PlayResult": None,      "PitchCall": "BallCalled"},
        {"KorBB": None,        "PlayResult": "Single",  "PitchCall": "InPlay"},
        {"KorBB": None,        "PlayResult": "HomeRun", "PitchCall": "InPlay"},
        {"KorBB": None,        "PlayResult": "Double",  "PitchCall": "InPlay"},
        {"KorBB": "Strikeout", "PlayResult": "Out",     "PitchCall": "StrikeSwinging"},
        {"KorBB": None,        "PlayResult": "Out",     "PitchCall": "InPlay"},
    ])
    c = hitting._slash_counts(pas)
    assert c["pa"] == 6 and c["ab"] == 5 and c["h"] == 3
    assert c["doubles"] == 1 and c["triples"] == 0 and c["hr"] == 1
    assert c["bb"] == 1 and c["so"] == 1 and c["tb"] == 1 + 4 + 2
    # _slash_from_pas display is unchanged (delegates to the same counts).
    assert hitting._slash_from_pas(pas) == {"BA": ".600", "SLG": "1.400", "OBP": ".667"}
