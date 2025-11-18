"""
Simple serial-based CNC simulator for CIRQWizard.

The simulator opens COM8 at 57600 baud (default), mirrors the G-code protocol used by
the STM32 CNC controller, prints every command/response pair, and visualizes tool
motion in a live 3D plot (unless --no-plot is given).
"""

from __future__ import annotations

import argparse
import datetime as _dt
import queue
import sys
import textwrap
import threading
from typing import Iterable, Optional, Tuple

import matplotlib.pyplot as plt
from matplotlib import cm
from mpl_toolkits.mplot3d import Axes3D  # noqa: F401
import serial


def timestamp() -> str:
    return _dt.datetime.now().strftime("%H:%M:%S")


def log(direction: str, payload: str) -> None:
    clean = payload.replace("\r", "").rstrip("\n")
    for line in clean.splitlines() or [""]:
        print(f"[{timestamp()}] {direction:<12} {line}")
    sys.stdout.flush()


class CNCSimulator:
    def __init__(self, visualizer: Optional["Visualizer"] = None) -> None:
        self.spindle_on = False
        self.syringe_on = False
        self.vacuum_on = False
        self.workspace = "G54"
        self.wcs_offset = {"X": 0.0, "Y": 0.0, "Z": 0.0}
        self.position = {"X": 0.0, "Y": 0.0, "Z": 0.0}
        self.visualizer = visualizer

    def handle(self, command: str) -> Iterable[str]:
        cmd = command.strip()
        if not cmd:
            return []
        upper = cmd.upper()
        code = _normalize_g_code(cmd)

        if upper.startswith("$$$RESET"):
            self._reset_state()
            return ["ok"]

        if code == "G53":
            self.workspace = "G53"
            return ["ok"]
        if code == "G54":
            self.workspace = "G54"
            return ["ok"]
        if code == "G92":
            self._set_wcs_offset(cmd)
            return ["ok"]

        if code in {"G0", "G1"}:
            self._process_motion(cmd, rapid=(code == "G0"))
            return ["ok"]
        if code == "G4":
            return ["ok"]

        if "M3" in upper:
            self.spindle_on = True
        if "M5" in upper:
            self.spindle_on = False
        if "M7" in upper and "M70" not in upper:
            self.vacuum_on = True
        if "M8" in upper:
            self.syringe_on = True
        if "M9" in upper:
            self.syringe_on = False
            self.vacuum_on = False

        return ["ok"]

    def _process_motion(self, command: str, rapid: bool) -> None:
        coords = _parse_axes(command)
        if not coords:
            return
        machine_coords = self._resolve_target(coords)
        target = self.position.copy()
        for axis, value in machine_coords.items():
            target[axis] = value
        travel = self._vector_distance(self.position, target)
        self.position = target
        if self.visualizer is not None:
            self.visualizer.enqueue_move(
                (target.get("X", 0.0), target.get("Y", 0.0), target.get("Z", 0.0)),
                rapid=rapid,
            )

    def _vector_distance(self, src: dict, dst: dict) -> float:
        dx = dst.get("X", src.get("X", 0.0)) - src.get("X", 0.0)
        dy = dst.get("Y", src.get("Y", 0.0)) - src.get("Y", 0.0)
        dz = dst.get("Z", src.get("Z", 0.0)) - src.get("Z", 0.0)
        return (dx ** 2 + dy ** 2 + dz ** 2) ** 0.5

    def _apply_reset(self) -> None:
        self.wcs_offset = {"X": 0.0, "Y": 0.0, "Z": 0.0}
        self.position = {"X": 0.0, "Y": 0.0, "Z": 0.0}
        self.workspace = "G54"
        if self.visualizer is not None:
            self.visualizer.reset_plot()

    def _set_wcs_offset(self, command: str) -> None:
        coords = _parse_axes(command)
        if not coords:
            return
        for axis, value in coords.items():
            current = self.position.get(axis, 0.0)
            self.wcs_offset[axis] = current - value

    def _resolve_target(self, coords: dict[str, float]) -> dict[str, float]:
        resolved: dict[str, float] = {}
        for axis, value in coords.items():
            if self.workspace == "G53":
                resolved[axis] = value
            else:
                resolved[axis] = value + self.wcs_offset.get(axis, 0.0)
        return resolved

    def _reset_state(self) -> None:
        self._apply_reset()


def _normalize_g_code(cmd: str) -> str | None:
    text = cmd.strip().upper()
    if not text:
        return None
    word = text.split()[0]
    if not word.startswith("G"):
        return None
    digits = ""
    for ch in word[1:]:
        if ch.isdigit():
            digits += ch
        else:
            break
    if not digits:
        return None
    return f"G{int(digits)}"


def _parse_axes(cmd: str) -> dict[str, float]:
    axes: dict[str, float] = {}
    for token in cmd.split():
        if not token:
            continue
        letter = token[0].upper()
        if letter in ("X", "Y", "Z"):
            try:
                axes[letter] = float(token[1:])
            except ValueError:
                continue
    return axes


class Visualizer:
    def __init__(self, bed_width: float, bed_height: float, bed_depth: float = 50.0) -> None:
        self.bed_width = bed_width
        self.bed_height = bed_height
        self.bed_depth = bed_depth
        self.queue: "queue.Queue[Tuple[str, Tuple[float, float, float], bool]]" = queue.Queue()
        self.points: list[Tuple[float, float, float, bool]] = []
        self._stop = threading.Event()

    def enqueue_move(self, position: Tuple[float, float, float], rapid: bool) -> None:
        self.queue.put(("move", position, rapid))

    def reset_plot(self) -> None:
        self.queue.put(("reset", (0.0, 0.0, 0.0), False))

    def run_forever(self) -> None:
        plt.ion()
        fig = plt.figure(figsize=(7, 7))
        ax = fig.add_subplot(111, projection="3d")
        ax.set_title("Virtual CNC Volume")
        ax.set_xlabel("X (mm)")
        ax.set_ylabel("Y (mm)")
        ax.set_zlabel("Z (mm)")
        ax.set_xlim(0, self.bed_width)
        ax.set_ylim(0, self.bed_height)
        ax.set_zlim(-self.bed_depth, 0)
        ax.grid(True, linestyle=":")
        tool_plot = ax.scatter([], [], [], color="green", s=50)
        path_plot = ax.plot([], [], [], color="red")[0]
        rapid_plot = ax.plot([], [], [], color="blue", linestyle="dashed")[0]
        fig.canvas.mpl_connect("close_event", lambda event: self._stop.set())
        plt.show(block=False)

        while not self._stop.is_set():
            try:
                event, position, rapid = self.queue.get(timeout=0.05)
            except queue.Empty:
                plt.pause(0.01)
                continue

            if event == "reset":
                self.points.clear()
                path_plot.set_data([], [])
                path_plot.set_3d_properties([])
                rapid_plot.set_data([], [])
                rapid_plot.set_3d_properties([])
                tool_plot._offsets3d = ([], [], [])
                fig.canvas.draw_idle()
                plt.pause(0.01)
                continue

            if event == "move":
                x, y, z = position
                self.points.append((x, y, z, rapid))
                xs_feed = [p[0] for p in self.points if not p[3]]
                ys_feed = [p[1] for p in self.points if not p[3]]
                zs_feed = [p[2] for p in self.points if not p[3]]
                xs_rapid = [p[0] for p in self.points if p[3]]
                ys_rapid = [p[1] for p in self.points if p[3]]
                zs_rapid = [p[2] for p in self.points if p[3]]
                path_plot.set_data(xs_feed, ys_feed)
                path_plot.set_3d_properties(zs_feed)
                rapid_plot.set_data(xs_rapid, ys_rapid)
                rapid_plot.set_3d_properties(zs_rapid)
                tool_plot._offsets3d = ([x], [y], [z])
                fig.canvas.draw_idle()
                plt.pause(0.01)

        plt.close(fig)

    def stop(self) -> None:
        self._stop.set()


def reader_loop(
    port: serial.Serial,
    handler: CNCSimulator,
    log_responses: bool,
) -> None:
    buffer = ""
    while True:
        raw = port.read(1)
        if not raw:
            continue
        buffer += raw.decode(errors="ignore")
        if "\n" not in buffer:
            continue
        line, buffer = buffer.split("\n", 1)
        line = line.rstrip("\r")
        log("HOST ➜ SIM", line)
        for reply in handler.handle(line):
            port.write((reply + "\n").encode())
            if log_responses:
                log("SIM ➜ HOST", reply)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="CIRQWizard CNC serial simulator",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=textwrap.dedent(
            """\
            Example:
              python cnc_simulator.py --port COM8 --baud 57600
            """
        ),
    )
    parser.add_argument("--port", default="COM8")
    parser.add_argument("--baud", type=int, default=57600)
    parser.add_argument("--timeout", type=float, default=0.1)
    parser.add_argument("--bed-width", type=float, default=200.0)
    parser.add_argument("--bed-height", type=float, default=200.0)
    parser.add_argument(
        "--no-plot",
        action="store_true",
        help="Disable the live 3D visualization (terminal chat only)",
    )
    parser.add_argument(
        "--no-log-responses",
        action="store_false",
        dest="log_responses",
        help="Suppress printing simulator replies (serial data still sent)",
    )
    parser.set_defaults(log_responses=True)
    args = parser.parse_args()

    visualizer = None if args.no_plot else Visualizer(args.bed_width, args.bed_height)
    handler = CNCSimulator(visualizer=visualizer)
    print(f"Opening {args.port} @ {args.baud} baud. Press Ctrl+C to stop.")
    with serial.Serial(args.port, args.baud, timeout=args.timeout) as port:
        if visualizer:
            worker = threading.Thread(
                target=reader_loop,
                args=(port, handler, args.log_responses),
                daemon=True,
            )
            worker.start()
            try:
                visualizer.run_forever()
            except KeyboardInterrupt:
                print("Stopping simulator...")
            finally:
                visualizer.stop()
                worker.join(timeout=1.0)
        else:
            try:
                reader_loop(port, handler, args.log_responses)
            except KeyboardInterrupt:
                print("Simulator stopped.")


if __name__ == "__main__":
    main()
