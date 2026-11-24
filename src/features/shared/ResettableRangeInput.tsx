import type { ComponentProps } from "react";

type Props = Omit<ComponentProps<"input">, "type" | "value" | "onChange"> & {
  value: number;
  initialValue: number;
  onValueChange: (value: number) => void;
};

export function ResettableRangeInput({ initialValue, onValueChange, title, ...props }: Props) {
  return (
    <input
      {...props}
      type="range"
      title={title ?? "右クリックで初期値に戻す"}
      onChange={(event) => onValueChange(Number(event.currentTarget.value))}
      onContextMenu={(event) => {
        event.preventDefault();
        onValueChange(initialValue);
      }}
    />
  );
}
