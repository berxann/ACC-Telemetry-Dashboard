"""
Строит график телеметрии последнего записанного заезда:
- скорость по дистанции круга
- газ / тормоз под ним

Запуск: python plot_lap.py
"""

import sqlite3
import matplotlib.pyplot as plt

DB_PATH = "telemetry.db"


def get_latest_lap_id(conn):
    row = conn.execute("SELECT id, track, car FROM laps ORDER BY id DESC LIMIT 1").fetchone()
    if row is None:
        raise RuntimeError("В базе нет ни одной записанной сессии")
    return row  # (lap_id, track, car)


def load_telemetry(conn, lap_id):
    rows = conn.execute("""
        SELECT position, speed_kmh, gas, brake, current_lap_time,
               tyre_temp_fl, tyre_temp_fr, tyre_temp_rl, tyre_temp_rr
        FROM telemetry
        WHERE lap_id = ?
        ORDER BY id
    """, (lap_id,)).fetchall()
    return rows


def main():
    conn = sqlite3.connect(DB_PATH)

    lap_id, track, car = get_latest_lap_id(conn)
    rows = load_telemetry(conn, lap_id)
    conn.close()

    if not rows:
        print(f"Для lap_id={lap_id} нет данных телеметрии")
        return

    position = [r[0] for r in rows]
    speed = [r[1] for r in rows]
    gas = [r[2] for r in rows]
    brake = [r[3] for r in rows]
    lap_time = [r[4] for r in rows]
    tyre_fl = [r[5] for r in rows]
    tyre_fr = [r[6] for r in rows]
    tyre_rl = [r[7] for r in rows]
    tyre_rr = [r[8] for r in rows]

    fig, (ax1, ax2, ax3, ax4) = plt.subplots(4, 1, figsize=(12, 12), sharex=True)

    ax1.plot(position, speed, color="tab:blue")
    ax1.set_ylabel("Скорость, км/ч")
    ax1.set_title(f"Трасса: {track} | Машина: {car} | lap_id={lap_id}")
    ax1.grid(True, alpha=0.3)

    ax2.plot(position, gas, color="tab:green", label="Газ")
    ax2.plot(position, brake, color="tab:red", label="Тормоз")
    ax2.set_ylabel("Педали (0-1)")
    ax2.legend()
    ax2.grid(True, alpha=0.3)

    # Время круга по дистанции — растёт монотонно, показывает "сколько секунд прошло к этой точке"
    ax3.plot(position, lap_time, color="tab:purple")
    ax3.set_ylabel("Время круга, сек")
    ax3.grid(True, alpha=0.3)

    ax4.plot(position, tyre_fl, label="FL", color="tab:blue")
    ax4.plot(position, tyre_fr, label="FR", color="tab:orange")
    ax4.plot(position, tyre_rl, label="RL", color="tab:green")
    ax4.plot(position, tyre_rr, label="RR", color="tab:red")
    ax4.set_ylabel("Темп. шин, °C")
    ax4.set_xlabel("Позиция на круге (0.0 - 1.0)")
    ax4.legend()
    ax4.grid(True, alpha=0.3)

    plt.tight_layout()
    plt.show()


if __name__ == "__main__":
    main()
