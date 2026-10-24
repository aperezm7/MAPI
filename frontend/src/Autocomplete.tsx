import { KeyboardEvent, useEffect, useId, useRef, useState } from "react";

type Option = { label: string; detail?: string };

type Props<T> = {
  value: string;
  onChange: (value: string) => void;
  fetchOptions: (q: string, signal: AbortSignal) => Promise<T[]>;
  describe: (item: T) => Option;
  getKey: (item: T) => string | number;
  onPick: (item: T) => void;
  onEnter: () => void;
  placeholder?: string;
  emptyHint?: string;
  minChars?: number;
  invalid?: boolean;
  describedBy?: string;
};

export default function Autocomplete<T>({
  value,
  onChange,
  fetchOptions,
  describe,
  getKey,
  onPick,
  onEnter,
  placeholder,
  emptyHint,
  minChars = 2,
  invalid,
  describedBy,
}: Props<T>) {
  const listId = useId();
  const [options, setOptions] = useState<T[]>([]);
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(-1);
  const [searching, setSearching] = useState(false);
  const [searched, setSearched] = useState("");
  const typed = useRef(false);
  const pending = useRef<AbortController | null>(null);
  const fetchRef = useRef(fetchOptions);
  fetchRef.current = fetchOptions;

  useEffect(() => {
    if (!typed.current) return;
    const q = value.trim();
    if (q.length < minChars) {
      setOptions([]);
      setSearched("");
      setOpen(false);
      return;
    }
    const controller = new AbortController();
    pending.current = controller;
    const timer = window.setTimeout(() => {
      setSearching(true);
      fetchRef
        .current(q, controller.signal)
        .then((items) => {
          setOptions(items);
          setSearched(q);
          setActive(-1);
          setOpen(true);
        })
        .catch(() => {
          if (!controller.signal.aborted) setOptions([]);
        })
        .finally(() => {
          if (!controller.signal.aborted) setSearching(false);
        });
    }, 250);
    return () => {
      window.clearTimeout(timer);
      controller.abort();
    };
  }, [value, minChars]);

  function close() {
    typed.current = false;
    pending.current?.abort();
    setOpen(false);
    setActive(-1);
    setSearching(false);
  }

  function pick(item: T) {
    close();
    onPick(item);
  }

  function onKeyDown(event: KeyboardEvent<HTMLInputElement>) {
    if (event.key === "ArrowDown" || event.key === "ArrowUp") {
      if (!options.length) return;
      event.preventDefault();
      setOpen(true);
      const step = event.key === "ArrowDown" ? 1 : -1;
      setActive((current) => (current + step + options.length) % options.length);
    } else if (event.key === "Enter") {
      event.preventDefault();
      if (open && active >= 0 && options[active]) {
        pick(options[active]);
      } else {
        close();
        onEnter();
      }
    } else if (event.key === "Escape" && open) {
      event.preventDefault();
      close();
    }
  }

  const showEmpty = open && !searching && options.length === 0 && searched === value.trim() && Boolean(emptyHint);

  return (
    <div className="autocomplete">
      <input
        type="text"
        role="combobox"
        aria-expanded={open && options.length > 0}
        aria-controls={listId}
        aria-autocomplete="list"
        aria-activedescendant={open && active >= 0 ? `${listId}-${active}` : undefined}
        aria-invalid={invalid || undefined}
        aria-describedby={describedBy}
        autoComplete="off"
        spellCheck={false}
        value={value}
        placeholder={placeholder}
        onChange={(e) => {
          typed.current = true;
          onChange(e.target.value);
        }}
        onKeyDown={onKeyDown}
        onFocus={() => {
          if (options.length && searched === value.trim()) setOpen(true);
        }}
        onBlur={() => setOpen(false)}
      />
      {searching ? <span className="autocomplete-spinner" aria-hidden="true" /> : null}
      {open && options.length > 0 ? (
        <ul className="autocomplete-list" id={listId} role="listbox">
          {options.map((item, index) => {
            const option = describe(item);
            return (
              <li
                key={getKey(item)}
                id={`${listId}-${index}`}
                role="option"
                aria-selected={index === active}
                className={index === active ? "active" : ""}
                onMouseDown={(e) => e.preventDefault()}
                onMouseEnter={() => setActive(index)}
                onClick={() => pick(item)}
              >
                {option.label}
                {option.detail ? <small>{option.detail}</small> : null}
              </li>
            );
          })}
        </ul>
      ) : null}
      {showEmpty ? (
        <div className="autocomplete-list autocomplete-empty" role="status">
          {emptyHint}
        </div>
      ) : null}
    </div>
  );
}
