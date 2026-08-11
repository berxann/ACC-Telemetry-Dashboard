"""
ACC Telemetry Logger
Запусти игру, встань на трассу (Hotlap/Practice/Race), затем запусти этот скрипт.
Ctrl+C — остановить запись и сохранить в SQLite.
"""

import time
import sqlite3
from datetime import datetime
from pyaccsharedmemory import accSharedMemory

DB_PATH = "telemetry.db"
LOG_INTERVAL = 0.05  # 20 записей в секунду


def init_db(conn):
    conn.execute("""
        CREATE TABLE IF NOT EXISTS laps (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_name TEXT,
            track TEXT,
            car TEXT,
            created_at TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS telemetry (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            lap_id INTEGER,
            timestamp REAL,
            position REAL,       -- normalized_car_position 0.0-1.0
            speed_kmh REAL,
            gas REAL,
            brake REAL,
            steer_angle REAL,
            gear INTEGER,
            rpm REAL,
            g_force_x REAL,
            g_force_y REAL,
            g_force_z REAL,
            tyre_temp_fl REAL,
            tyre_temp_fr REAL,
            tyre_temp_rl REAL,
            tyre_temp_rr REAL,
            wheel_slip_fl REAL,
            wheel_slip_fr REAL,
            wheel_slip_rl REAL,
            wheel_slip_rr REAL,
            current_lap_time REAL,
            delta_lap_time REAL,
            is_in_pit INTEGER,
            car_x REAL,           -- мировая координата X (для карты трассы)
            car_z REAL,           -- мировая координата Z
            FOREIGN KEY (lap_id) REFERENCES laps (id)
        )
    """)
    # Если база уже существовала без car_x/car_z (со старой версии скрипта) — добавляем колонки
    existing_cols = [row[1] for row in conn.execute("PRAGMA table_info(telemetry)").fetchall()]
    if "car_x" not in existing_cols:
        conn.execute("ALTER TABLE telemetry ADD COLUMN car_x REAL")
    if "car_z" not in existing_cols:
        conn.execute("ALTER TABLE telemetry ADD COLUMN car_z REAL")
    conn.commit()


def main():
    conn = sqlite3.connect(DB_PATH)
    init_db(conn)

    asm = accSharedMemory()

    # Ждём первый валидный снапшот, чтобы достать название трассы/машины
    print("Жду данные из ACC... (встань на трассу в игре)")
    sm = None
    while sm is None:
        sm = asm.read_shared_memory()
        time.sleep(0.5)

    track = sm.Static.track.split("\x00")[0].strip()
    raw_car = sm.Static.car_model.name if hasattr(sm.Static.car_model, "name") else str(sm.Static.car_model)
    car = raw_car.split("\x00")[0].strip()

    cur = conn.execute(
        "INSERT INTO laps (session_name, track, car, created_at) VALUES (?, ?, ?, ?)",
        (f"session_{datetime.now():%Y%m%d_%H%M%S}", track, car, datetime.now().isoformat())
    )
    lap_id = cur.lastrowid
    conn.commit()

    print(f"Записываю телеметрию: трасса={track}, машина={car}")
    print("Ctrl+C — остановить и сохранить")

    rows = []
    try:
        while True:
            sm = asm.read_shared_memory()
            if sm is not None:
                p, g = sm.Physics, sm.Graphics

                # Координаты своей машины: ищем свой ID в списке car_id, берём координаты по тому же индексу
                try:
                    idx = g.car_id.index(g.player_car_id)
                    car_x, car_z = g.car_coordinates[idx].x, g.car_coordinates[idx].z
                except (ValueError, IndexError):
                    car_x, car_z = None, None

                rows.append((
                    lap_id,
                    time.time(),
                    g.normalized_car_position,
                    p.speed_kmh,
                    p.gas,
                    p.brake,
                    p.steer_angle,
                    p.gear,
                    p.rpm,
                    p.g_force.x, p.g_force.y, p.g_force.z,
                    p.tyre_core_temp.front_left, p.tyre_core_temp.front_right,
                    p.tyre_core_temp.rear_left, p.tyre_core_temp.rear_right,
                    p.wheel_slip.front_left, p.wheel_slip.front_right,
                    p.wheel_slip.rear_left, p.wheel_slip.rear_right,
                    g.current_time,
                    g.delta_lap_time,
                    int(g.is_in_pit),
                    car_x, car_z,
                ))

                # Пишем пачками по 100 записей, чтобы не дёргать диск каждый кадр
                if len(rows) >= 100:
                    flush(conn, rows)
                    rows = []

            time.sleep(LOG_INTERVAL)

    except KeyboardInterrupt:
        if rows:
            flush(conn, rows)
        asm.close()
        conn.close()
        print("\nОстановлено. Данные сохранены в telemetry.db")


def flush(conn, rows):
    conn.executemany("""
        INSERT INTO telemetry (
            lap_id, timestamp, position, speed_kmh, gas, brake, steer_angle,
            gear, rpm, g_force_x, g_force_y, g_force_z,
            tyre_temp_fl, tyre_temp_fr, tyre_temp_rl, tyre_temp_rr,
            wheel_slip_fl, wheel_slip_fr, wheel_slip_rl, wheel_slip_rr,
            current_lap_time, delta_lap_time, is_in_pit, car_x, car_z
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
    """, rows)
    conn.commit()


if __name__ == "__main__":
    main()
