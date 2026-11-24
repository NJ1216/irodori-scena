import { useEffect, useRef, useState } from "react";
import { ResettableRangeInput } from "../shared/ResettableRangeInput";
import { DialogFooter, DialogHeader } from "../shared/overlays";

export function AvatarCropDialog({ source, saving, onSave, onClose }: { source: string; saving: boolean; onSave: (original: string, thumbnail: string) => void; onClose: () => void }) {
  const cropSize = 280;
  const imageRef = useRef<HTMLImageElement | null>(null);
  const drag = useRef<{
    x: number;
    y: number;
    offsetX: number;
    offsetY: number;
  } | null>(null);
  const [imageSize, setImageSize] = useState<{
    width: number;
    height: number;
  } | null>(null);
  const [zoom, setZoom] = useState(1);
  const [offset, setOffset] = useState({ x: 0, y: 0 });
  useEffect(() => {
    const image = new Image();
    image.onload = () => {
      imageRef.current = image;
      setImageSize({ width: image.naturalWidth, height: image.naturalHeight });
    };
    image.src = source;
    return () => {
      imageRef.current = null;
    };
  }, [source]);
  const geometry = (nextZoom = zoom) => {
    if (!imageSize) return null;
    const baseScale = Math.max(cropSize / imageSize.width, cropSize / imageSize.height);
    const width = imageSize.width * baseScale * nextZoom;
    const height = imageSize.height * baseScale * nextZoom;
    return {
      width,
      height,
      limitX: Math.max(0, (width - cropSize) / 2),
      limitY: Math.max(0, (height - cropSize) / 2),
    };
  };
  const clampOffset = (next: { x: number; y: number }, nextZoom = zoom) => {
    const size = geometry(nextZoom);
    return size
      ? {
          x: Math.max(-size.limitX, Math.min(size.limitX, next.x)),
          y: Math.max(-size.limitY, Math.min(size.limitY, next.y)),
        }
      : next;
  };
  const size = geometry();
  const left = size ? (cropSize - size.width) / 2 + offset.x : 0;
  const top = size ? (cropSize - size.height) / 2 + offset.y : 0;
  const beginDrag = (event: React.PointerEvent<HTMLDivElement>) => {
    event.currentTarget.setPointerCapture(event.pointerId);
    drag.current = {
      x: event.clientX,
      y: event.clientY,
      offsetX: offset.x,
      offsetY: offset.y,
    };
  };
  const moveDrag = (event: React.PointerEvent<HTMLDivElement>) => {
    if (!drag.current) return;
    setOffset(
      clampOffset({
        x: drag.current.offsetX + event.clientX - drag.current.x,
        y: drag.current.offsetY + event.clientY - drag.current.y,
      }),
    );
  };
  const finishDrag = () => {
    drag.current = null;
  };
  const adjustZoom = (next: number) => {
    const clamped = Math.max(1, Math.min(9, next));
    setZoom(clamped);
    setOffset((current) => clampOffset(current, clamped));
  };
  const zoomWithWheel = (event: React.WheelEvent<HTMLDivElement>) => {
    event.preventDefault();
    adjustZoom(zoom + (event.deltaY < 0 ? 0.1 : -0.1));
  };
  const save = () => {
    if (!size || !imageRef.current) return;
    const outputSize = 189;
    const ratio = outputSize / cropSize;
    const canvas = document.createElement("canvas");
    canvas.width = outputSize;
    canvas.height = outputSize;
    const context = canvas.getContext("2d");
    if (!context) return;
    context.drawImage(imageRef.current, left * ratio, top * ratio, size.width * ratio, size.height * ratio);
    onSave(source, canvas.toDataURL("image/png"));
  };
  return (
    <div className="modal-backdrop">
      <section className="modal avatar-crop-modal" role="dialog" aria-modal="true" aria-label="キャラクター画像を切り抜き">
        <DialogHeader eyebrow="CHARACTER IMAGE" title="画像を正方形に切り抜く" description="画像をドラッグして位置を調整し、拡大率を選んでください。" />
        <div className="avatar-crop-preview" onPointerDown={beginDrag} onPointerMove={moveDrag} onPointerUp={finishDrag} onPointerCancel={finishDrag} onWheel={zoomWithWheel}>
          {size && <img src={source} alt="切り抜きのプレビュー" draggable={false} style={{ width: size.width, height: size.height, left, top }} />}
        </div>
        <label className="avatar-zoom-control">
          <span>
            拡大率 <output>{zoom.toFixed(2)}×</output>
          </span>
          <ResettableRangeInput className="range-control" min={1} max={9} step={0.01} value={zoom} initialValue={1} onValueChange={adjustZoom} />
        </label>
        <DialogFooter>
          <button type="button" disabled={saving} onClick={onClose}>
            キャンセル
          </button>
          <button className="primary" disabled={!size || saving} onClick={save}>
            {saving ? "保存中…" : "この画像を設定"}
          </button>
        </DialogFooter>
      </section>
    </div>
  );
}
