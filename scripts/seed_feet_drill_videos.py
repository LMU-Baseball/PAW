"""One-off seed: Feet Set/Feet Moving/Work Day drill videos (2026-09-22).

Brad's "Perscription Links.xlsx" (Downloads folder), sheet "Plyo, WB, Mound",
holds the real Google Drive links for the drill catalog (`FEET_DRILL_OPTIONS`
in app/data/splash_report.py -- originally sourced from a *different* file,
"PD PLANS - Pitching.xlsx"'s MENU sheet, which explains why names differ by
reps/color annotation, e.g. "CVB - Drift (x5)" here vs. "CVB - Drift" there).

DRILL_VIDEOS below maps each catalog drill name to its matched Google Drive
link (61 of 67 catalog drills matched with confidence -- the other 6 have no
unambiguous match in the sheet and are left for a coach to add by hand via
the "Manage Video Library" panel, category "Drills": CVB (Fwd Pull), Figure
8 Rocker, Heel Wedge Dry Reps, Lateral Reach, Quarter Squat w/ Reach,
Walkbacks). Several drill names share one link on purpose (e.g. "10-Toes
Figure 8" / "10-Toes Figure 8's" both point at the same clip) -- the sheet
itself repeats the same drill/link pair under multiple training-quality
sub-categories.

Idempotent: skips any drill title already present in the "Drills" video
category (checked by title, not a DB constraint -- `splash_videos` has no
unique key on title), so re-running this is safe.

Usage:  python scripts/seed_feet_drill_videos.py [--dry-run]
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.data import splash_report as SR  # noqa: E402

DRILL_VIDEOS: dict[str, str] = {
    "10-Toes Figure 8 (Blue x6)": "https://drive.google.com/file/d/1hu0EbDfOFXXYs0sjgzn7xGJX5XqdRABy/view?usp=drive_link",
    "10-Toes Figure 8's (Blue x6)": "https://drive.google.com/file/d/1hu0EbDfOFXXYs0sjgzn7xGJX5XqdRABy/view?usp=drive_link",
    "2-Step Shuffle Throws (Yellow/Baseball x4)": "https://drive.google.com/file/d/1Z8A7BQSqrqjzJG5f-ZldKhk34Dhwq_L0/view?usp=drive_link",
    "2-Step Shuffle Throws (x5)": "https://drive.google.com/file/d/1Z8A7BQSqrqjzJG5f-ZldKhk34Dhwq_L0/view?usp=drive_link",
    "Anterior Step Double Plays (Yellow/Baseball x4)": "https://drive.google.com/file/d/1lZqhP21icBUv3N6XyUe1izAArUVsp8o8/view?usp=sharing",
    "Back to Wall Banch Reach x3 breaths": "https://drive.google.com/file/d/1Ug3Z23uc1jUVoYEO26zO9QOTcSEfNcWU/view?usp=drive_link",
    "Back to Wall Bench Reach 3X breaths": "https://drive.google.com/file/d/1Ug3Z23uc1jUVoYEO26zO9QOTcSEfNcWU/view?usp=drive_link",
    "CVB - Drift (x5)": "https://drive.google.com/file/d/1_EdPL1OpwjsNkiCfxZ-fQVybzHK6BHWY/view?usp=drive_link",
    "CVB - Drive Leg (x5)": "https://drive.google.com/file/d/1ULSEvTdGQx_6gD112SB6wejuTbn9FLzv/view?usp=drive_link",
    "CVB - Feed the Flaw (x5)": "https://drive.google.com/file/d/1tNkDm-GHtV-xIVusekybB8IJd_1ksGq4/view?usp=drive_link",
    "Depth Box Drops (Yellow/Baseball x4)": "https://drive.google.com/file/d/1d8bolYpOn57GE7k5t_oiXC6UVGwgtB0P/view?usp=drive_link",
    "Ferm Drill (Yellow/Baseball x4)": "https://drive.google.com/file/d/1SyKbEMFGlEJOFTXwmmCbhW60JcsDTbyR/view?usp=drive_link",
    "Fly’s": "https://drive.google.com/file/d/1cz6ELAfLldiiR0_z7aJ9m75pJybTY9MY/view?usp=drive_link",
    "Front Foot Elevated Saucers (Blue x6)": "https://drive.google.com/file/d/1tZLgWzT-u7K3vJ2jAVzyi5VoYn_nZKH2/view?usp=sharing",
    "Front-Foot Elevated Figure 8's (Blue x6)": "https://drive.google.com/file/d/164miDB5-52HV-2PgQKuC8117IHp7UowT/view?usp=drive_link",
    "Front-Foot Elevated Rockers (Blue x6)": "https://drive.google.com/file/d/1T6A7Ldf_WZJVc6sfK_Ls62yVD2uwSYq1/view?usp=drive_link",
    "Heel-Elevated Pitches (Yellow/Baseball x4)": "https://drive.google.com/file/d/1jGyjngzeS8TRsy9Qeplf7vHlP8JaKpH3/view?usp=drive_link",
    "Hook 'Em - On Mound (Yellow/Baseball x4)": "https://drive.google.com/file/d/1uj2mNqhHhQI4xbNF-KBR9B8iewFWqzUC/view?usp=drive_link",
    "Hook’Em (Yellow/Baseball x4)": "https://drive.google.com/file/d/1uj2mNqhHhQI4xbNF-KBR9B8iewFWqzUC/view?usp=drive_link",
    "Lasso Throws (Blue x6)": "https://drive.google.com/file/d/1z-70731tG2d5EC2T1PqEm_O0HpVlGORT/view?usp=drive_link",
    "Lateral Arm Drags 5X breaths|side": "https://drive.google.com/file/d/1MYhZGZrl0zuGP-x3MexTaXQU2joTq_Uu/view?usp=drive_link",
    "Lateral Arm Drags x 5 breaths/side": "https://drive.google.com/file/d/1MYhZGZrl0zuGP-x3MexTaXQU2joTq_Uu/view?usp=drive_link",
    "Lateral Step-Back (Yellow/Baseball x4)": "https://drive.google.com/file/d/1t0WpSZW2zMbM4YCU--gM-Dc_8V1XRJpF/view?usp=drive_link",
    "Med Ball Hugs x5 (2 sets)": "https://drive.google.com/file/d/1_2uT4b-mIpA5eVIpq06UdaTyeZUTRys6/view?usp=drive_link",
    "MedBall Depth Drop Shotput (x5)": "https://drive.google.com/file/d/1dTfpIz0eJEtb0wC4bPBZSXu0xQwTB1zK/view?usp=drive_link",
    "MedBall Double Hop Shotput (x5)": "https://drive.google.com/file/d/17ZElgiIqdAotmxxefb8rPrW3bk0SBW-h/view?usp=drive_link",
    "MedBall FFE Figure 8 Shotput (x5)": "https://drive.google.com/file/d/1pWHmzWmYL4TVmAn-g_P_oViliy1NuH0D/view?usp=drive_link",
    "MedBall Hugs w/ Heel Elevated (x5)": "https://drive.google.com/file/d/1qDIz8mg2Ur50tAEfByytYOAE8woEKvkC/view?usp=drive_link",
    "MedBall Hugs w/CVB Drift (x5)": "https://drive.google.com/file/d/1TN0MLRbCkCLLsDM0MyKnSZNdeGOoAvsa/view?usp=drive_link",
    "MedBall Split Stance Shotput (x5)": "https://drive.google.com/file/d/1eEowwNivK-37Jz5zXuR_9mP4s4Jrp-8n/view?usp=drive_link",
    "MedBall Stepbacks Shotput (x5)": "https://drive.google.com/file/d/1aRa5QZUfkGMv50A6y7u_huWRmouv6nz5/view?usp=drive_link",
    "MedBall Turn & Burn Shotput (x5)": "https://drive.google.com/file/d/1Ix_oF5UHXicWH-OOjLiiX0SWyw05bFqg/view?usp=drive_link",
    "MedBall w/CVB Drift (x5)": "https://drive.google.com/file/d/1TN0MLRbCkCLLsDM0MyKnSZNdeGOoAvsa/view?usp=drive_link",
    "MedBall w/CVB Drive Leg (x5)": "https://drive.google.com/file/d/1-TqC8iKuuGPiWYAtXpx-_NiLXj9XiC8B/view?usp=drive_link",
    "MedBall w/CVB Feed the Flaw (x5)": "https://drive.google.com/file/d/19wESX_5C21tT-OT4OQ52sKwKtfCWumUK/view?usp=drive_link",
    "Partner Decels (Green x8)": "https://drive.google.com/file/d/1IGPfmKs5aZoW3J_2mNSD_4efZDrTSrUq/view?usp=drive_link",
    "Pivot Picks (Blue x6)": "https://drive.google.com/file/d/1jDRl5m_q0OQqo0LBVnvU5XCm7irl9K2A/view?usp=drive_link",
    "Posterior Step Double Plays (Yellow/Baseball x4)": "https://drive.google.com/file/d/1XWLi1w8_POPRXNOXmq7evDYLX6LBxjLG/view?usp=sharing",
    "QB Armside Rollouts (Red x4)": "https://drive.google.com/file/d/1p0m4f0a_iwMx0wSKADmwn4foli8bNGwY/view?usp=drive_link",
    "QB Gloveside Rollouts (Red x4)": "https://drive.google.com/file/d/1rHzAni0bh8Zn5_j0acAQh4LLDPsxLAPD/view?usp=drive_link",
    "QB Stepups (Red x4)": "https://drive.google.com/file/d/1_nKiZz-nnPtmUtnpraKIXzWje1bgmp7p/view?usp=drive_link",
    "Reverse Flys x3 (Left foot back)": "https://drive.google.com/file/d/1cz6ELAfLldiiR0_z7aJ9m75pJybTY9MY/view?usp=drive_link",
    "Reverse Throws (Green x8)": "https://drive.google.com/file/d/1eYj7DQWxWnn4D4Ys0cEdhx2h6zxQ0E4J/view?usp=drive_link",
    "Reverse Walkbacks x 5/side": "https://drive.google.com/file/d/1tCYz2TdrNcoT4UzoSBjEKufprz4Dxd9L/view?usp=drive_link",
    "Roll-Ins (Yellow/Baseball x4)": "https://drive.google.com/file/d/1S4JOn8J1JqHfv4qAyQt-zvjEi15lVtgG/view?usp=sharing",
    "Rotational Step Back x4": "https://drive.google.com/file/d/1WjXBhaGw00fSFMxvZ88PoL04TXhBSAcq/view?usp=drive_link",
    "Rotational StepBack (Yellow/Baseball x4)": "https://drive.google.com/file/d/1WjXBhaGw00fSFMxvZ88PoL04TXhBSAcq/view?usp=drive_link",
    "Saucers w/ Front Foot Elevated (Blue x6)": "https://drive.google.com/file/d/1tZLgWzT-u7K3vJ2jAVzyi5VoYn_nZKH2/view?usp=sharing",
    "Split Stance Figure 8's (Blue x6)": "https://drive.google.com/file/d/1_njpCZGaAviCPAwiZs_EMZP_Lcffgnjl/view?usp=drive_link",
    "Throwing Walkbacks (Red x4)": "https://drive.google.com/file/d/1pWFUpphkOl_CGzBndmq1qNj9yPPPCAJW/view?usp=drive_link",
    "Turn & Burn (Yellow/Baseball x4)": "https://drive.google.com/file/d/1pX7BJKSG4mXtrezWGhRVIB0g_PIy78HM/view?usp=drive_link",
    "Turn & Burn - On Mound (Yellow/Baseball x4)": "https://drive.google.com/file/d/1pX7BJKSG4mXtrezWGhRVIB0g_PIy78HM/view?usp=drive_link",
    "Turn and Burns x4": "https://drive.google.com/file/d/1pX7BJKSG4mXtrezWGhRVIB0g_PIy78HM/view?usp=drive_link",
    "Walking Wind Up - On Mound (Yellow/Baseball x4)": "https://drive.google.com/file/d/1I5mIfm0dSLPzkLgH3u29E3NwWFgXJ0Bk/view?usp=drive_link",
    "Walking Wind Up x4": "https://drive.google.com/file/d/1I5mIfm0dSLPzkLgH3u29E3NwWFgXJ0Bk/view?usp=drive_link",
    "Walking Windup (Yellow/Baseball x4)": "https://drive.google.com/file/d/1I5mIfm0dSLPzkLgH3u29E3NwWFgXJ0Bk/view?usp=drive_link",
    "Water Bag Foot Elevated Figure 8 (x5)": "https://drive.google.com/file/d/137mwtHpAW6dIBhGrNAmOx-HxwmuCIkJe/view?usp=sharing",
    "Water Bag Hand Held Throws (2x 30 seconds)": "https://drive.google.com/file/d/19jk-k9krgzDe8M1LsbGjxX-u69diwvq4/view?usp=sharing",
    "Water Bag Hop Back (Hot Feet) (x5)": "https://drive.google.com/file/d/1UmRjuCiURzBOjdI-5DSOQXlYjPZP9tbl/view?usp=drive_link",
    "Water Bag Kettle Bell Carry (2x60 ft)": "https://drive.google.com/file/d/1w67ZzyjL9riJKlxZywNfjVBggvsMPRr3/view?usp=sharing",
    "Water Bag Lateral Step Back (x5)": "https://drive.google.com/file/d/1wkz-9-CDZjgR_YSi0exVjGtQ_k4TOwkD/view?usp=drive_link",
}


def main(dry_run: bool) -> None:
    SR.ensure_tables()
    existing = set(SR.list_videos("Drills")["title"]) if not SR.list_videos("Drills").empty else set()
    added = 0
    for title, url in DRILL_VIDEOS.items():
        if title in existing:
            continue
        added += 1
        if dry_run:
            print(f"[dry-run] would add: {title!r} -> {url}")
            continue
        SR.add_video_link(title, "Drills", url)
        print(f"added: {title}")
    print(f"\n{added} added, {len(DRILL_VIDEOS) - added} already present, "
         f"{len(DRILL_VIDEOS)} total.")


if __name__ == "__main__":
    main(dry_run="--dry-run" in sys.argv)
