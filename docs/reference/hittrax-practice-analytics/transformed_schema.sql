-- Transformed Schema for Baseball Practice Analytics
-- Customized for PlaysExport + SessionExport data structure
-- This schema contains clean, business-ready tables
-- Last updated: 2026-03-12 — added session_type, pitch coordinates, hit counts,
--   launch angle fix, swing decision fields, and expanded player summary

-- Drop tables if they exist (in reverse dependency order)
DROP TABLE IF EXISTS player_stats_summary;
DROP TABLE IF EXISTS practice_plays;
DROP TABLE IF EXISTS practice_sessions;

-- ========================================
-- PRACTICE SESSIONS TABLE
-- ========================================
CREATE TABLE IF NOT EXISTS practice_sessions (
    session_id INT AUTO_INCREMENT PRIMARY KEY,
    hittrax_session_id INT,                -- Id from SessionExport
    session_date DATE NOT NULL,
    session_timestamp DATETIME,
    team_name VARCHAR(100),
    practice_type VARCHAR(50),
    duration_minutes DECIMAL(10,1),
    total_plays INT DEFAULT 0,

    -- Player/User info for the session
    player_id INT,
    player_uuid VARCHAR(100),
    user_name VARCHAR(255),
    first_name VARCHAR(100),
    last_name VARCHAR(100),

    -- Session Classification (from SessionExport)
    -- Type values: 1=Hitting, 4=Baseline, 5=HitLab, 7=Quality Hit Game,
    --              11=Game, 12=Entertainment, 16=Drill
    session_type INT,                      -- Type
    session_tag VARCHAR(500),             -- Tag (free-text coach label)
    game_type INT,                         -- GT: 0=Baseball, 1=FP Softball, 2=SP Softball
    skill_level INT,                       -- SL: 3=College, 4=Professional

    -- Session Performance Metrics (from SessionExport)
    avg_exit_velocity DECIMAL(8,2),        -- AEV (m/s → mph)
    max_exit_velocity DECIMAL(8,2),        -- MEV (m/s → mph)
    avg_distance DECIMAL(8,2),             -- AD (meters → feet)
    max_distance DECIMAL(8,2),             -- MD (meters → feet)
    avg_ground_distance DECIMAL(8,2),      -- AGD (meters → feet)
    max_ground_distance DECIMAL(8,2),      -- MGD (meters → feet)
    avg_launch_angle DECIMAL(8,2),         -- AElv (degrees)
    avg_pitch_velocity DECIMAL(8,2),       -- APV (m/s → mph)
    max_pitch_velocity DECIMAL(8,2),       -- MPV (m/s → mph)

    -- Barrel/Impact Metrics (from SessionExport)
    avg_barrel_velocity DECIMAL(8,2),      -- ABRV (m/s → mph)
    max_barrel_velocity DECIMAL(8,2),      -- MBRV (m/s → mph)

    -- Hit Distribution (from SessionExport)
    ground_ball_pct DECIMAL(5,2),          -- GBP
    fly_ball_pct DECIMAL(5,2),             -- FBP
    line_drive_pct DECIMAL(5,2),           -- LDP
    left_infield_pct DECIMAL(5,2),         -- LIP
    right_infield_pct DECIMAL(5,2),        -- RIP
    center_infield_pct DECIMAL(5,2),       -- CIP
    left_outfield_pct DECIMAL(5,2),        -- LOP
    right_outfield_pct DECIMAL(5,2),       -- ROP
    center_outfield_pct DECIMAL(5,2),      -- COP

    -- Traditional Stats (from SessionExport)
    pitch_count INT,                       -- PC
    at_bats INT,                           -- AB
    hit_count INT,                         -- HC (total batted balls)
    singles INT,                           -- Sing
    doubles INT,                           -- Doub
    triples INT,                           -- Trip
    home_runs INT,                         -- Home
    fouls INT,                             -- Foul
    strikes INT,                           -- Strk
    balls INT,                             -- Ball
    rbi INT,                               -- RBI
    batting_avg DECIMAL(4,3),              -- AVG
    slugging_pct DECIMAL(4,3),             -- SLG
    score INT,                             -- SCR

    -- Hit Quality (from SessionExport)
    hard_hit_count INT,                    -- HHC
    hard_hit_velocity DECIMAL(8,2),        -- HHV (m/s → mph): threshold for hard hit classification

    -- Strike Zone Dimensions (from SessionExport, meters → feet)
    strike_zone_top DECIMAL(8,2),          -- SZT
    strike_zone_bottom DECIMAL(8,2),       -- SZB
    strike_zone_width DECIMAL(8,2),        -- SZW

    -- Strike Zone Performance by Zone Section (from SessionExport)
    -- Pitcher's perspective: zones 1-9 are strikes, 10-13 are balls
    --   10  11
    --  1 2 3
    --  4 5 6
    --  7 8 9
    --   12  13
    zone_avg_1 DECIMAL(8,4),               -- AHZ1
    zone_avg_2 DECIMAL(8,4),               -- AHZ2
    zone_avg_3 DECIMAL(8,4),               -- AHZ3
    zone_avg_4 DECIMAL(8,4),               -- AHZ4
    zone_avg_5 DECIMAL(8,4),               -- AHZ5
    zone_avg_6 DECIMAL(8,4),               -- AHZ6
    zone_avg_7 DECIMAL(8,4),               -- AHZ7
    zone_avg_8 DECIMAL(8,4),               -- AHZ8
    zone_avg_9 DECIMAL(8,4),               -- AHZ9
    zone_avg_10 DECIMAL(8,4),              -- AHZ10 (high-inside ball)
    zone_avg_11 DECIMAL(8,4),              -- AHZ11 (high-outside ball)
    zone_avg_12 DECIMAL(8,4),              -- AHZ12 (low-inside ball)
    zone_avg_13 DECIMAL(8,4),              -- AHZ13 (low-outside ball)

    -- Training Context (from SessionExport)
    pelotero_drill_id VARCHAR(100),        -- PeloteroDrillId
    pelotero_block_id VARCHAR(100),        -- PeloteroBlockId
    game_uuid VARCHAR(100),                -- GameUuid
    event_uuid VARCHAR(100),               -- EventUuid

    -- Source tracking
    source_file VARCHAR(255),

    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,

    -- Indexes for common queries
    INDEX idx_session_date (session_date),
    INDEX idx_player_id (player_id),
    INDEX idx_team (team_name),
    INDEX idx_hittrax_session_id (hittrax_session_id),
    INDEX idx_session_type (session_type),
    UNIQUE KEY unique_session (session_date, player_id, hittrax_session_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- ========================================
-- PRACTICE PLAYS TABLE
-- ========================================
CREATE TABLE IF NOT EXISTS practice_plays (
    id INT AUTO_INCREMENT PRIMARY KEY,
    play_id BIGINT NOT NULL,
    session_id INT,

    -- Player/User Information
    player_id INT,
    player_name VARCHAR(255),
    player_uuid VARCHAR(100),
    first_name VARCHAR(100),
    last_name VARCHAR(100),
    user_id INT,
    user_uuid VARCHAR(100),

    -- Batter handedness (Hand field: 0=Left, 1=Right)
    hand INT,

    -- Timestamp
    play_timestamp DATETIME,

    -- Ball Flight Metrics (US Customary units)
    exit_velocity DECIMAL(8,2),            -- Velo (m/s → mph): exit ball velocity magnitude
    launch_angle DECIMAL(8,2),             -- Elv (degrees): actual launch/elevation angle
    distance_feet DECIMAL(8,2),            -- Dist (meters → feet): to first impact
    ground_distance DECIMAL(8,2),          -- GD (meters → feet): true ground distance
    horizontal_angle DECIMAL(8,2),         -- HorzAngle (degrees): spray direction, neg=left, pos=right
    hang_time_ms INT,                      -- Ms: millisecond component of timestamp (play duration proxy)

    -- Exit Velocity Vector Components (m/s → mph)
    -- Coordinate system: origin at home plate, X=right, Y=up, Z=forward
    exit_velo_x DECIMAL(8,2),             -- EBV1 (m/s → mph): X component (side)
    exit_velo_y DECIMAL(8,2),             -- EBV2 (m/s → mph): Y component (vertical)
    exit_velo_z DECIMAL(8,2),             -- EBV3 (m/s → mph): Z component (forward)

    -- Hit Classification
    hit_type INT,                          -- HT: 0=none, 1=ground, 2=line drive, 3=fly ball, 4=balt.chop
    -- Result codes: -6=wild pitch, -5=swing&miss, -4=not calc, -3=foul, -2=HBP,
    --               -8=line drive out, -1=fly out, 0=out, 1=single, 2=double, 3=triple, 4=HR
    result INT,                            -- Res: play result code
    pitch_type INT,                        -- PT: -1=none, 0=ball, 1=strike
    -- Zone section 1-13 (pitcher's perspective): 1-9 strikes, 10-13 balls
    zone_section INT,                      -- QD: strike zone section of the pitch
    fielder INT,                           -- Fld: 0=none, 1=P, 2=C, 3=1B, 4=2B, 5=3B, 6=SS, 7=LF, 8=CF, 9=RF

    -- Pitch Location at Home Plate (meters → feet)
    -- PP1/PP2 are the primary coordinates for the strike zone heat map
    pitch_location_x DECIMAL(8,4),         -- PP1 (meters → feet): horizontal position (neg=inside to RHB)
    pitch_location_y DECIMAL(8,4),         -- PP2 (meters → feet): height above ground
    pitch_location_z DECIMAL(8,4),         -- PP3 (meters → feet): depth (always ~0 at plate)

    -- Pitch Metrics (US Customary)
    pitch_velocity DECIMAL(8,2),           -- RadarVelo (m/s → mph): Stalker radar velocity
    pitch_angle DECIMAL(8,2),              -- PitchAngle (degrees): incoming pitch angle at plate
    pitch_break_h DECIMAL(8,2),            -- PBH (inches): horizontal break over last 8 feet
    pitch_break_v DECIMAL(8,2),            -- PBV (inches): vertical break over last 8 feet

    -- Bat Information
    bat_id INT,
    bat_uuid VARCHAR(100),

    -- Scoring
    points INT DEFAULT 0,                  -- Points (Quality Hit Game)
    result_runs INT DEFAULT 0,             -- ResultRuns

    -- Metadata
    master_id VARCHAR(100),
    uuid VARCHAR(100),
    source_file VARCHAR(255),
    ingested_at DATETIME,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    -- Foreign Key
    FOREIGN KEY (session_id) REFERENCES practice_sessions(session_id) ON DELETE CASCADE,

    -- Indexes for analytics
    INDEX idx_play_id (play_id),
    INDEX idx_player_id (player_id),
    INDEX idx_session (session_id),
    INDEX idx_play_timestamp (play_timestamp),
    INDEX idx_hit_type (hit_type),
    INDEX idx_result (result),
    INDEX idx_exit_velocity (exit_velocity),
    INDEX idx_launch_angle (launch_angle),
    INDEX idx_distance (distance_feet),
    INDEX idx_zone_section (zone_section),
    INDEX idx_hand (hand),
    INDEX idx_pitch_location (pitch_location_x, pitch_location_y),
    UNIQUE KEY unique_play (play_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- ========================================
-- PLAYER STATISTICS SUMMARY
-- ========================================
CREATE TABLE IF NOT EXISTS player_stats_summary (
    player_id INT PRIMARY KEY,
    player_name VARCHAR(255),
    player_uuid VARCHAR(100),
    first_name VARCHAR(100),
    last_name VARCHAR(100),

    -- Volume Stats
    total_plays INT DEFAULT 0,
    total_sessions INT DEFAULT 0,
    last_practice_date DATE,

    -- Exit Velocity Stats (mph)
    avg_exit_velocity DECIMAL(8,2),
    max_exit_velocity DECIMAL(8,2),

    -- Distance Stats (feet)
    avg_distance DECIMAL(8,2),
    max_distance INT,

    -- Launch Angle (quality-filtered: LA between -10 and 50 degrees)
    avg_launch_angle DECIMAL(8,2),

    -- Traditional Batting Stats (career totals from sessions)
    total_at_bats INT DEFAULT 0,
    total_hits INT DEFAULT 0,             -- Singles + Doubles + Triples + HR
    total_singles INT DEFAULT 0,
    total_doubles INT DEFAULT 0,
    total_triples INT DEFAULT 0,
    total_home_runs INT DEFAULT 0,
    career_batting_avg DECIMAL(4,3),       -- total_hits / total_at_bats
    career_slugging_pct DECIMAL(4,3),      -- (1B + 2*2B + 3*3B + 4*HR) / AB

    -- Quality / Hard Hit Metrics
    hard_hit_count INT DEFAULT 0,          -- from sessions HHC
    hard_hit_rate DECIMAL(5,2),            -- % of quality plays (EV >= 95 mph)

    -- Hit Type Rates (from plays)
    fly_ball_rate DECIMAL(5,2),            -- % fly balls (HT=3)
    line_drive_rate DECIMAL(5,2),          -- % line drives (HT=2)

    -- Swing Decision Metrics (from result codes in plays)
    -- Swing: result in (-5, -3, -8, -1, 0, 1, 2, 3, 4)
    -- Take:  result in (-6, -4, -2) [wild pitch, not calc, HBP]
    total_swings INT DEFAULT 0,
    swing_rate DECIMAL(5,2),               -- % swings out of all pitches seen

    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,

    INDEX idx_total_plays (total_plays),
    INDEX idx_avg_exit_velo (avg_exit_velocity),
    INDEX idx_last_practice (last_practice_date)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
