import { KeyboardEvent, PointerEvent, useRef } from "react";
import type { YearCount } from "./types";

type Props = {
  bins: YearCount[];
  start: number;
  end: number;
  disabled?: boolean;
  onChange: (start: number, end: number) => void;
  onCommit: (start: number, end: number) => void;
};

export default function YearRange({ bins, start, end, disabled, onChange, onCommit }: Props) {
  const min = bins[0].year;
  const max = bins[bins.length - 1].year;
  const span = Math.max(1, max - min);
  const peak = Math.max(1, ...bins.map((bin) => bin.count));
  const trackRef = useRef<HTMLDivElement>(null);
  const drag = useRef<"start" | "end" | null>(null);
  const latest = useRef({ start, end });
  latest.current = drag.current ? latest.current : { start, end };

  function yearAt(clientX: number) {
    const rect = trackRef.current?.getBoundingClientRect();
    if (!rect || rect.width <= 0) return min;
    const ratio = Math.min(1, Math.max(0, (clientX - rect.left) / rect.width));
    return Math.round(min + ratio * span);
  }

  function move(which: "start" | "end", year: number) {
    const clamped = Math.min(max, Math.max(min, year));
    const current = latest.current;
    const next =
      which === "start"
        ? { start: Math.min(clamped, current.end), end: current.end }
        : { start: current.start, end: Math.max(clamped, current.start) };
    if (next.start === current.start && next.end === current.end) return;
    latest.current = next;
    onChange(next.start, next.end);
  }

  function finish() {
    if (!drag.current) return;
    drag.current = null;
    onCommit(latest.current.start, latest.current.end);
  }

  function grab(which: "start" | "end", event: PointerEvent<HTMLElement>) {
    if (disabled) return;
    event.preventDefault();
    event.stopPropagation();
    drag.current = which;
    event.currentTarget.setPointerCapture(event.pointerId);
  }

  function onTrackDown(event: PointerEvent<HTMLDivElement>) {
    if (disabled || (event.target as HTMLElement).closest(".year-thumb")) return;
    const year = yearAt(event.clientX);
    const which =
      Math.abs(year - latest.current.start) <= Math.abs(year - latest.current.end) ? "start" : "end";
    grab(which, event);
    move(which, year);
  }

  function onKeyDown(which: "start" | "end", event: KeyboardEvent<HTMLButtonElement>) {
    if (disabled) return;
    const value = which === "start" ? latest.current.start : latest.current.end;
    const step = event.shiftKey ? 10 : 1;
    const jumps: Record<string, number> = {
      ArrowLeft: value - step,
      ArrowDown: value - step,
      ArrowRight: value + step,
      ArrowUp: value + step,
      Home: min,
      End: max,
    };
    if (!(event.key in jumps)) return;
    event.preventDefault();
    move(which, jumps[event.key]);
  }

  if (min === max) {
    return (
      <p className="year-caption">
        All mapped records are from <strong>{min}</strong>.
      </p>
    );
  }

  const startPct = ((start - min) / span) * 100;
  const endPct = ((end - min) / span) * 100;
  const cramped = endPct - startPct < 18;

  function labelShift(pct: number) {
    if (pct < 8) return "0";
    if (pct > 92) return "-100%";
    return "-50%";
  }

  return (
    <div className="year-range">
      <div className="year-histogram" aria-hidden="true">
        {bins.map((bin) =>
          bin.count > 0 ? (
            <span
              key={bin.year}
              className={bin.year >= start && bin.year <= end ? "in" : "out"}
              title={`${bin.year}: ${bin.count.toLocaleString()}`}
              style={{
                left: `${((bin.year - min) / span) * 100}%`,
                width: `max(2px, ${100 / (span + 1)}%)`,
                height: `${Math.max(8, (bin.count / peak) * 100)}%`,
              }}
            />
          ) : null,
        )}
      </div>
      <div
        className="year-track"
        ref={trackRef}
        onPointerDown={onTrackDown}
        onPointerMove={(event) => {
          if (drag.current) move(drag.current, yearAt(event.clientX));
        }}
        onPointerUp={finish}
        onPointerCancel={finish}
      >
        <div className="year-track-rail" />
        <div className="year-track-fill" style={{ left: `${startPct}%`, width: `${Math.max(0, endPct - startPct)}%` }} />
        <Thumb
          label="From year"
          year={start}
          min={min}
          max={end}
          pct={startPct}
          shift={labelShift(startPct)}
          showYear={!cramped}
          disabled={disabled}
          onPointerDown={(event) => grab("start", event)}
          onPointerUp={finish}
          onPointerCancel={finish}
          onKeyDown={(event) => onKeyDown("start", event)}
          onKeyUp={() => onCommit(latest.current.start, latest.current.end)}
        />
        <Thumb
          label="To year"
          year={end}
          min={start}
          max={max}
          pct={endPct}
          shift={labelShift(endPct)}
          showYear={!cramped}
          disabled={disabled}
          onPointerDown={(event) => grab("end", event)}
          onPointerUp={finish}
          onPointerCancel={finish}
          onKeyDown={(event) => onKeyDown("end", event)}
          onKeyUp={() => onCommit(latest.current.start, latest.current.end)}
        />
      </div>
      <p className="year-caption">
        From <strong>{start}</strong> to <strong>{end}</strong>
      </p>
    </div>
  );
}

function Thumb({
  label,
  year,
  min,
  max,
  pct,
  shift,
  showYear,
  disabled,
  onPointerDown,
  onPointerUp,
  onPointerCancel,
  onKeyDown,
  onKeyUp,
}: {
  label: string;
  year: number;
  min: number;
  max: number;
  pct: number;
  shift: string;
  showYear: boolean;
  disabled?: boolean;
  onPointerDown: (event: PointerEvent<HTMLButtonElement>) => void;
  onPointerUp: () => void;
  onPointerCancel: () => void;
  onKeyDown: (event: KeyboardEvent<HTMLButtonElement>) => void;
  onKeyUp: () => void;
}) {
  return (
    <button
      type="button"
      className="year-thumb"
      role="slider"
      aria-label={label}
      aria-valuemin={min}
      aria-valuemax={max}
      aria-valuenow={year}
      aria-valuetext={String(year)}
      aria-disabled={disabled || undefined}
      disabled={disabled}
      style={{ left: `${pct}%` }}
      onPointerDown={onPointerDown}
      onPointerUp={onPointerUp}
      onPointerCancel={onPointerCancel}
      onKeyDown={onKeyDown}
      onKeyUp={onKeyUp}
    >
      {showYear ? (
        <span className="year-thumb-label" style={{ transform: `translateX(${shift})` }}>
          {year}
        </span>
      ) : null}
    </button>
  );
}
