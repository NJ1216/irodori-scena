import type { LinePronunciation } from "../../types";

export type LineTextSnapshot = {
  text: string;
  pronunciations: LinePronunciation[];
};

export type LineTextHistoryEntry = LineTextSnapshot & { caret: number };

const MAX_LOCAL_HISTORY = 100;
const textLength = (value: string) => Array.from(value).length;

function sameSnapshot(left: LineTextSnapshot, right: LineTextSnapshot) {
  if (left.text !== right.text || left.pronunciations.length !== right.pronunciations.length) return false;
  return left.pronunciations.every((item, index) => {
    const other = right.pronunciations[index];
    return item.id === other.id && item.start === other.start && item.end === other.end && item.text === other.text && item.reading === other.reading;
  });
}

function entry(snapshot: LineTextSnapshot, caret: number): LineTextHistoryEntry {
  return { text: snapshot.text, pronunciations: snapshot.pronunciations.map((item) => ({ ...item })), caret };
}

export class LineTextLocalHistory {
  private current: LineTextHistoryEntry;
  private readonly undoEntries: LineTextHistoryEntry[] = [];
  private readonly redoEntries: LineTextHistoryEntry[] = [];

  constructor(initial: LineTextSnapshot) {
    this.current = entry(initial, textLength(initial.text));
  }

  sync(value: LineTextSnapshot) {
    if (sameSnapshot(this.current, value)) return;
    this.current = entry(value, textLength(value.text));
    this.undoEntries.length = 0;
    this.redoEntries.length = 0;
  }

  record(value: LineTextSnapshot, beforeCaret: number | null, afterCaret: number | null) {
    if (sameSnapshot(this.current, value)) return false;
    this.undoEntries.push(entry(this.current, beforeCaret ?? this.current.caret));
    if (this.undoEntries.length > MAX_LOCAL_HISTORY) this.undoEntries.shift();
    this.current = entry(value, afterCaret ?? textLength(value.text));
    this.redoEntries.length = 0;
    return true;
  }

  undo() {
    return this.move(this.undoEntries, this.redoEntries);
  }

  redo() {
    return this.move(this.redoEntries, this.undoEntries);
  }

  private move(source: LineTextHistoryEntry[], destination: LineTextHistoryEntry[]) {
    const next = source.pop();
    if (!next) return null;
    destination.push(entry(this.current, this.current.caret));
    this.current = entry(next, next.caret);
    return entry(next, next.caret);
  }
}
